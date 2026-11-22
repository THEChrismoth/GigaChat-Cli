"""Инструменты просмотра исходников без записи в проект."""

import codecs
import os
import subprocess
from pathlib import Path
from typing import Iterator

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from gigachat_cli.core.file_edit import FileEditError, read_project_prefix


_IGNORED_DIRS = {"__pycache__", "node_modules", "venv"}
_REVIEW_IGNORED_DIRS = {"build", "dist", "vendor"}
_SUFFIXES = set(".py .pyi .js .jsx .ts .tsx .mjs .cjs .json .md .txt .toml .yaml .yml .ini .cfg .go .rs "
                ".java .kt .c .cpp .h .hpp .sh .ps1 .html .css .sql .rb .php .cs .xml .vue .svelte".split())
_FILE_BYTES = 256 * 1024
_SEARCH_BYTES = 8 * 1024 * 1024
_MAX_FILES = 5000


def iter_project_files(project_path: str, *, review: bool = False) -> Iterator[tuple[str, str]]:
    """Обойти проект в стабильном порядке и ограничить число результатов."""
    count = 0
    ignored = _IGNORED_DIRS | _REVIEW_IGNORED_DIRS if review else _IGNORED_DIRS
    for root, dirs, files in os.walk(project_path):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in ignored)
        if review:
            dirs[:] = [d for d in dirs if not os.path.isjunction(os.path.join(root, d))]
        for name in sorted(files):
            if name.startswith("."):
                continue
            path = os.path.join(root, name)
            if review and (os.path.islink(path) or not os.path.isfile(path)):
                continue
            yield os.path.relpath(path, project_path), path
            count += 1
            if count >= _MAX_FILES:
                return


class _Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _ListFiles(_Arguments):
    prefix: str = Field(default="", max_length=512, description="Относительный путь к папке или пустая строка")
    offset: int = Field(default=0, ge=0, description="Смещение для следующей страницы")


class _SearchCode(_Arguments):
    query: str = Field(min_length=1, max_length=200, description="Буквальная подстрока, без регулярных выражений")
    prefix: str = Field(default="", max_length=512, description="Папка или файл относительно корня проекта")


class _ReadFile(_Arguments):
    path: str = Field(min_length=1, max_length=512, description="Относительный путь к файлу")
    start_line: int = Field(default=1, ge=1, description="Первая строка, нумерация с единицы")
    line_count: int = Field(default=60, ge=1, le=100, description="Число строк")


_TOOLS = {
    "list_files": (_ListFiles, "Показать страницу списка файлов проекта"),
    "search_code": (_SearchCode, "Найти буквальную подстроку и номера строк в коде проекта"),
    "read_file": (_ReadFile, "Прочитать диапазон строк текстового файла проекта"),
}

REVIEW_TOOLS = [
    {"name": name, "description": description, "parameters": schema.model_json_schema()}
    for name, (schema, description) in _TOOLS.items()
]


def _relative(value: str) -> str:
    """Принять только относительный путь внутри проекта."""
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized or ".." in normalized.split("/"):
        raise FileEditError("Укажите путь внутри проекта.")
    path = normalized.rstrip("/")
    return path.removeprefix("./") if path != "." else ""


def _git_ignored(root: Path, paths: list[str]) -> set[str]:
    """Получить исключения Git одним запросом без запуска оболочки."""
    markers = (parent / ".git" for parent in (root, *root.parents))
    if not paths or not any(marker.is_file() or (marker / "HEAD").is_file() for marker in markers):
        return set()
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"], cwd=root,
            capture_output=True, timeout=5,
        )
    except FileNotFoundError:
        raise FileEditError("Для проверки исключений при ревью нужен Git.") from None
    if inside.returncode != 0 or inside.stdout.strip() != b"true":
        raise FileEditError("Не удалось проверить исключения Git.")
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-z", "--stdin"], cwd=root,
        input=b"\0".join(os.fsencode(path) for path in paths) + b"\0",
        capture_output=True, timeout=5,
    )
    if result.returncode not in (0, 1):
        raise FileEditError("Не удалось проверить исключения Git.")
    return {os.fsdecode(path) for path in result.stdout.split(b"\0") if path}


class ReviewWorkspace:
    """Выполнять только операции чтения из контекста текущего проекта."""

    def __init__(self, directory: str) -> None:
        """Собрать индекс путей, доступных для просмотра."""
        self.root = Path(directory).resolve(strict=True)
        candidates = sorted(
            Path(relative).as_posix() for relative, _ in iter_project_files(str(self.root), review=True)
            if Path(relative).suffix.casefold() in _SUFFIXES or Path(relative).name in {"Dockerfile", "Makefile"}
        )
        ignored = _git_ignored(self.root, candidates)
        self.paths = [path for path in candidates if path not in ignored]
        self._paths = set(self.paths)
        self.read_paths: list[str] = []

    def call(self, name: str, args: dict) -> dict:
        """Проверить имя и аргументы, затем вернуть результат разрешённой операции."""
        spec = _TOOLS.get(name)
        if spec is None:
            return {"error": "В ревью доступны только список, поиск и чтение файлов."}
        try:
            request = spec[0].model_validate(args)
            if isinstance(request, _ListFiles):
                return self.list_files(request)
            if isinstance(request, _SearchCode):
                return self.search_code(request)
            return self.read_file(request)
        except ValidationError:
            return {"error": "Некорректные аргументы инструмента."}
        except (FileEditError, OSError, UnicodeError):
            return {"error": "Не удалось прочитать указанный путь внутри проекта."}

    def _under(self, prefix: str) -> list[str]:
        """Выбрать файлы по точному пути или префиксу папки."""
        prefix = _relative(prefix)
        return [path for path in self.paths if not prefix or path == prefix or path.startswith(prefix + "/")]

    def _source(self, path: str) -> tuple[list[str], bool, int]:
        """Прочитать ограниченный объём UTF-8 и отметить усечённый файл."""
        if path not in self._paths:
            raise FileEditError("Файл недоступен для ревью.")
        data = read_project_prefix(self.root, Path(path), _FILE_BYTES + 1)
        truncated = len(data) > _FILE_BYTES
        source = codecs.getincrementaldecoder("utf-8-sig")().decode(data[:_FILE_BYTES], final=not truncated)
        if "\0" in source:
            raise FileEditError("Файл не является текстом.")
        return source.splitlines(), truncated, len(data)

    def list_files(self, request: _ListFiles) -> dict:
        """Вернуть одну страницу списка файлов."""
        paths = self._under(request.prefix)
        end = request.offset + 70
        return {"files": paths[request.offset:end], "next_offset": end if end < len(paths) else None}

    def search_code(self, request: _SearchCode) -> dict:
        """Найти первые совпадения в пределах бюджета чтения."""
        matches = []
        remaining = _SEARCH_BYTES
        truncated = False
        query = request.query.casefold()
        for path in self._under(request.prefix):
            if remaining <= 0:
                truncated = True
                break
            try:
                lines, partial, size = self._source(path)
            except (FileEditError, OSError, UnicodeError):
                truncated = True
                remaining -= _FILE_BYTES
                continue
            truncated |= partial
            remaining -= size
            for number, line in enumerate(lines, 1):
                if query in line.casefold():
                    matches.append({"path": path, "line": number, "text": line[:240]})
                    if len(matches) == 20:
                        return {"matches": matches, "truncated": True}
        return {"matches": matches, "truncated": truncated}

    def read_file(self, request: _ReadFile) -> dict:
        """Вернуть пронумерованный диапазон строк одного файла."""
        path = _relative(request.path)
        lines, truncated, _ = self._source(path)
        start = request.start_line - 1
        end = start + request.line_count
        page = []
        remaining = 6500
        for number, line in enumerate(lines[start:end], start + 1):
            text = line[:300]
            remaining -= len(text) + 1
            if remaining < 0:
                break
            truncated |= len(text) < len(line)
            page.append({"line": number, "text": text})
        if page and path not in self.read_paths:
            self.read_paths.append(path)
        next_index = start + len(page)
        return {
            "path": path,
            "lines": page,
            "truncated": truncated,
            "next_line": next_index + 1 if next_index < len(lines) else None,
        }
