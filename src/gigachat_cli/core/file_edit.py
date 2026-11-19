"""Снимки текстовых файлов, предпросмотр изменений и запись после подтверждения."""

import codecs
from dataclasses import dataclass, replace
from difflib import unified_diff
from io import StringIO
import os
from pathlib import Path
import stat
from tempfile import NamedTemporaryFile


MAX_EDIT_BYTES = 15_000
_METADATA_DIRS = {".git", ".hg", ".svn"}


class FileEditError(ValueError):
    """Файл нельзя прочитать, изменить или восстановить в текущем состоянии."""


def _validate_text(text: str) -> str:
    """Исключить управляющие символы, несовместимые с текстовым предпросмотром."""
    if any(
        (ord(char) < 32 or 127 <= ord(char) <= 159) and char not in "\n\r\t"
        for char in text
    ):
        raise FileEditError("Поддерживаются только текстовые файлы UTF-8.")
    if "\r" in text.replace("\r\n", ""):
        raise FileEditError("Поддерживаются только окончания строк LF и CRLF.")
    return text


def _decode(data: bytes) -> str:
    """Прочитать ограниченный UTF-8 текст, не меняя окончания строк."""
    if len(data) > MAX_EDIT_BYTES:
        raise FileEditError(f"Файл превышает {MAX_EDIT_BYTES} байт.")
    try:
        return _validate_text(data.decode("utf-8-sig"))
    except UnicodeError as error:
        raise FileEditError("Поддерживаются только текстовые файлы UTF-8.") from error


@dataclass(frozen=True)
class FileSnapshot:
    """Исходное состояние одного файла, привязанное к выбранной директории."""

    root: Path
    relative_path: Path
    data: bytes | None

    @property
    def text(self) -> str:
        """Вернуть исходный текст или пустую строку для нового файла."""
        return _decode(self.data or b"")

    def propose(self, content: str) -> "FileEdit":
        """Подготовить замену, сохранив BOM и единый стиль окончаний строк."""
        _validate_text(content)
        original = self.text
        if self.data is not None and "\r\n" in original and "\n" not in original.replace("\r\n", ""):
            content = content.replace("\r\n", "\n").replace("\n", "\r\n")
        try:
            data = content.encode("utf-8")
        except UnicodeError as error:
            raise FileEditError("Модель вернула некорректный текст UTF-8.") from error
        if self.data is not None and self.data.startswith(codecs.BOM_UTF8):
            data = codecs.BOM_UTF8 + data
        _decode(data)
        return FileEdit(self, data)


def _target(root: Path, relative_path: Path) -> Path:
    """Проверить границы проекта и исключить ссылки, перенаправления и метаданные VCS."""
    if relative_path.anchor or not relative_path.parts or ".." in relative_path.parts:
        raise FileEditError("Укажите относительный путь к файлу внутри проекта.")
    for part in relative_path.parts:
        name = part.casefold()
        if name in _METADATA_DIRS or name == ".env" or name.startswith(".env."):
            raise FileEditError("Этот путь исключён из редактирования.")
        if ":" in part or part.endswith((".", " ")) or any(ord(char) < 32 for char in part):
            raise FileEditError("Недопустимое имя файла.")
        if os.name == "nt" and os.path.isreserved(part):
            raise FileEditError("Недопустимое имя файла.")

    path = root
    if root.resolve(strict=True) != root:
        raise FileEditError("Директория проекта изменилась.")
    for index, part in enumerate(relative_path.parts):
        path = path / part
        last = index == len(relative_path.parts) - 1
        try:
            info = path.lstat()
        except FileNotFoundError:
            if last:
                return path
            raise FileEditError("Родительский каталог файла должен существовать.") from None
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise FileEditError("Ссылки и перенаправления в пути не поддерживаются.")
        if not (stat.S_ISREG(info.st_mode) if last else stat.S_ISDIR(info.st_mode)):
            raise FileEditError("Укажите путь к обычному файлу.")
    return path


def _read(path: Path) -> bytes | None:
    """Прочитать ограниченный снимок файла, отличая отсутствие от пустого файла."""
    try:
        with path.open("rb") as stream:
            return stream.read(MAX_EDIT_BYTES + 1)
    except FileNotFoundError:
        return None


def read_snapshot(root: Path, path: str) -> FileSnapshot:
    """Зафиксировать содержимое одного файла из рабочей директории чата."""
    if path.endswith(("/", os.sep)):
        raise FileEditError("Укажите путь к файлу без завершающего разделителя.")
    root = root.resolve(strict=True)
    if any(part.casefold() in _METADATA_DIRS for part in root.parts):
        raise FileEditError("Этот путь исключён из редактирования.")
    relative_path = Path(path)
    data = _read(_target(root, relative_path))
    if data is not None:
        _decode(data)
    return FileSnapshot(root, relative_path, data)


@dataclass(frozen=True)
class FileEdit:
    """Предложение, применимое только к исходному состоянию файла."""

    before: FileSnapshot
    after: bytes | None

    def diff(self) -> str:
        """Показать изменения, включая создание пустого файла и отсутствие LF в конце."""
        if self.before.data == self.after:
            return ""
        name = self.before.relative_path.as_posix()
        old = self.before.data
        new = self.after
        old_name = f"a/{name}" if old is not None else "/dev/null"
        new_name = f"b/{name}" if new is not None else "/dev/null"
        # Сравниваем строки с их окончаниями, чтобы изменение LF/CRLF не исчезло из diff.
        lines = unified_diff(
            list(StringIO(self.before.text)),
            list(StringIO(_decode(new or b""))),
            fromfile=old_name,
            tofile=new_name,
        )
        rendered = []
        for line in lines:
            if line.endswith("\r\n"):
                rendered.append(line[:-2] + " ␍\n")
            elif line.endswith("\n"):
                rendered.append(line)
            else:
                rendered.append(line + "\n\\ Нет перевода строки в конце файла\n")
        return "".join(rendered) or f"--- {old_name}\n+++ {new_name}\n"

    def apply(self) -> "FileEdit":
        """Записать подтверждённое изменение и вернуть предложение для отката."""
        root, relative = self.before.root, self.before.relative_path
        path = _target(root, relative)
        self._check_current(path)
        if self.after is None:
            path.unlink()
        else:
            mode = stat.S_IMODE(path.stat().st_mode) if self.before.data is not None else None
            with NamedTemporaryFile(dir=path.parent, prefix=".gigachat-", delete=False) as stream:
                temporary = Path(stream.name)
                try:
                    stream.write(self.after)
                    stream.close()
                    if mode is not None:
                        temporary.chmod(mode)
                    self._check_current(_target(root, relative))
                    if self.before.data is None:
                        # Публикация нового файла не должна перезаписать появившийся файл.
                        try:
                            if os.name == "nt":
                                temporary.rename(path)
                            else:
                                os.link(temporary, path)
                        except FileExistsError as error:
                            raise FileEditError("Файл появился после подготовки изменений.") from error
                    else:
                        temporary.replace(path)
                finally:
                    stream.close()
                    temporary.unlink(missing_ok=True)
        return FileEdit(replace(self.before, data=self.after), self.before.data)

    def _check_current(self, path: Path) -> None:
        """Отклонить изменение, если текущее содержимое отличается от снимка."""
        if _read(path) != self.before.data:
            raise FileEditError("Файл изменился после подготовки изменений. Создайте новое предложение.")
