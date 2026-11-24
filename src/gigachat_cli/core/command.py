"""Терминальные команды: разбор командной строки, экранирование аргументов и выполнение."""

import asyncio
from contextlib import suppress
import signal
import shlex
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import List, Tuple, Optional


IS_WINDOWS = os.name == 'nt'

# Правила разбора командной строки: POSIX (shlex) или cmd.exe на Windows
POSIX_PARSING = not IS_WINDOWS
_OUTPUT_PREVIEW_BYTES = 8192


@dataclass
class CommandArgument:
    """Аргумент командной строки."""

    start: int                    # Позиция начала аргумента в исходной строке
    value: str                    # Значение без кавычек и экранирования
    quote: Optional[str] = None   # Кавычка, которой открыт аргумент (если есть)


def split_command_arguments(text: str, posix: bool = POSIX_PARSING) -> List[CommandArgument]:
    r"""Разбор командной строки на аргументы с учетом кавычек и экранирования.

    В отличие от shlex.split не завершается ошибкой на незакрытой кавычке или
    завершающем обратном слеше: строка разбирается в процессе ввода.
    Если строка заканчивается пробелом вне кавычек, добавляется пустой аргумент,
    который пользователь начинает вводить.

    Args:
        text: Командная строка
        posix: Правила POSIX-shell (кавычки ' и ", экранирование \)
            или cmd.exe (только кавычки ", обратный слеш - обычный символ)

    Returns:
        List[CommandArgument]: Аргументы в порядке следования
    """
    arguments: List[CommandArgument] = []
    current: Optional[CommandArgument] = None
    quote: Optional[str] = None
    quote_chars = ('"', "'") if posix else ('"',)
    index = 0

    while index < len(text):
        char = text[index]

        if quote is None and char.isspace():
            current = None
            index += 1
            continue

        if current is None:
            current = CommandArgument(start=index, value="", quote=char if char in quote_chars else None)
            arguments.append(current)

        if quote is None:
            if char in quote_chars:
                quote = char
            elif posix and char == '\\':
                # Экранированный символ добавляется как есть
                index += 1
                if index < len(text):
                    current.value += text[index]
            else:
                current.value += char
        elif char == quote:
            quote = None
        elif posix and quote == '"' and char == '\\' and text[index + 1:index + 2] in ('\\', '"', '$', '`'):
            # Внутри двойных кавычек POSIX-shell экранирует только \ " $ `
            index += 1
            current.value += text[index]
        else:
            current.value += char
        index += 1

    # Строка закончилась пробелом вне кавычек - начат новый аргумент
    if arguments and current is None:
        arguments.append(CommandArgument(start=len(text), value=""))

    return arguments


# Символы, требующие экранирования в POSIX-shell
_POSIX_SPECIAL_CHARS = set(' \t\n\'"\\$`&|;<>()*?[]{}#!')

# Символы, требующие кавычек в cmd.exe
_CMD_SPECIAL_CHARS = set(' \t&()[]{}^=;!\'+,`')


def quote_command_argument(value: str, quote: Optional[str] = None, posix: bool = POSIX_PARSING) -> str:
    """Экранирование аргумента для командной строки.

    Args:
        value: Значение аргумента
        quote: Предпочитаемая кавычка (та, которой пользователь начал аргумент)
        posix: Правила POSIX-shell или cmd.exe

    Returns:
        str: Аргумент, который split_command_arguments разберет обратно в value
    """
    if not posix:
        if quote == '"' or any(char in _CMD_SPECIAL_CHARS for char in value):
            return f'"{value}"'
        return value

    if quote == "'":
        return "'" + value.replace("'", "'\\''") + "'"
    if quote == '"':
        escaped = ''.join('\\' + char if char in '\\"$`' else char for char in value)
        return f'"{escaped}"'
    return ''.join('\\' + char if char in _POSIX_SPECIAL_CHARS else char for char in value)


# Команды, работающие с файлами: для их аргументов показывается автодополнение путей
FILE_COMMANDS = ['cd', 'ls', 'cp', 'mv', 'rm', 'mkdir', 'cat', 'touch', 'find', 'grep']
if IS_WINDOWS:
    FILE_COMMANDS += ['dir', 'type', 'copy', 'move', 'del', 'rmdir', 'md']


def _decode_output(data: bytes) -> str:
    """Декодирование вывода команды.

    Вывод читается как UTF-8; на Windows при ошибке - в OEM-кодировке консоли,
    в которой пишут cmd.exe и встроенные команды.

    Args:
        data: Байты вывода команды

    Returns:
        str: Текст вывода
    """
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        if IS_WINDOWS:
            import ctypes
            return data.decode(f"cp{ctypes.windll.kernel32.GetOEMCP()}", errors='replace')
        return data.decode('utf-8', errors='replace')


class _CommandOutput:
    """Хранить хвост вывода и дописывать длинный вывод во временный файл."""

    def __init__(self) -> None:
        """Начать сбор вывода без создания файла."""
        self._tail = b""
        self._pending = b""
        self._key = os.fsencode(os.getenv("GIGACHAT_API_KEY", ""))
        self._truncated = False
        self._log = None

    def _append(self, data: bytes, *, final: bool = False) -> None:
        """Скрыть ключ, включая совпадения на границе двух порций."""
        if self._key:
            parts = (self._pending + data).split(self._key)
            tail = parts.pop()
            keep = 0 if final else min(len(tail), len(self._key) - 1)
            end = len(tail) - keep
            data = b"***".join([*parts, tail[:end]])
            self._pending = tail[end:]

        combined = self._tail + data
        if not self._truncated and len(combined) > _OUTPUT_PREVIEW_BYTES:
            self._truncated = True
            try:
                self._log = NamedTemporaryFile(prefix="gigachat-output-", suffix=".log", delete=False)
                self._log.write(self._tail)
            except OSError:
                self.close()
        if self._log is not None:
            try:
                self._log.write(data)
            except OSError:
                self.close()
        # До трёх дополнительных байт нужны для проверки границы UTF-8.
        self._tail = combined[-(_OUTPUT_PREVIEW_BYTES + 3):]

    async def collect(self, process: asyncio.subprocess.Process) -> int:
        """Освобождать канал вывода порциями до завершения процесса."""
        stream = process.stdout
        assert stream is not None
        while data := await stream.read(_OUTPUT_PREVIEW_BYTES):
            self._append(data)
        return await process.wait()

    def close(self, *, keep: bool = False) -> Path | None:
        """Закрыть полный лог и вернуть путь к успешно сохранённому файлу."""
        log, self._log = self._log, None
        if log is None:
            return None
        path = Path(log.name)
        try:
            log.close()
        except OSError:
            keep = False
        if keep:
            return path
        with suppress(OSError):
            path.unlink()
        return None

    def render(self) -> str:
        """Вернуть ограниченный предпросмотр и путь к полному выводу."""
        self._append(b"", final=True)
        path = self.close(keep=True)
        offset = max(0, len(self._tail) - _OUTPUT_PREVIEW_BYTES)
        if offset and 0x80 <= self._tail[offset] <= 0xBF:
            start = end = offset
            while start and 0x80 <= self._tail[start] <= 0xBF:
                start -= 1
            while end < len(self._tail) and 0x80 <= self._tail[end] <= 0xBF:
                end += 1
            with suppress(UnicodeDecodeError):
                self._tail[start:end].decode("utf-8")
                offset = end
        preview = _decode_output(self._tail[offset:])
        if path is not None:
            return f"Вывод сокращён.\n{preview}\n\nПолный вывод: {path}"
        if self._truncated:
            return f"Вывод сокращён. Не удалось сохранить полный вывод.\n{preview}"
        return preview


class CommandUtils:
    """Выполнение терминальных команд в текущей директории чата.

    Текущая директория хранится здесь, а не в процессе: ее меняет !cd,
    и от нее же зависят поиск файлов и анализ проекта.
    """

    def __init__(self, command_timeout: float = 60):
        """Создание утилиты с текущей директорией процесса.

        Args:
            command_timeout: Ограничение времени выполнения команды, в секундах
        """
        self.current_directory = Path.cwd()
        self.command_timeout = command_timeout
        self.file_commands = FILE_COMMANDS

    async def execute_system_command(self, command: str | tuple[str, ...], *, env: dict[str, str] | None = None) -> Tuple[bool, str, int]:
        r"""Выполнение команды в текущей директории.

        На Windows команда выполняется через cmd.exe (доступны dir, type и пути с \),
        в остальных ОС - напрямую, без shell. Ввод с клавиатуры недоступен,
        время выполнения ограничено, при отмене задачи процесс завершается.

        Args:
            command: Команда без префикса ! или аргументы для запуска без оболочки.
            env: Явное окружение дочернего процесса.

        Returns:
            Tuple[bool, str, int]: Успех, предпросмотр вывода и код возврата.

        Raises:
            asyncio.CancelledError: Выполнение отменено (процесс при этом завершается)
        """
        stripped = command.strip() if isinstance(command, str) else ""
        if not (stripped or isinstance(command, tuple) and command):
            return False, "Пустая команда", 1

        program = command[0] if isinstance(command, tuple) else stripped.split()[0]

        try:
            # cd меняет директорию чата, а не дочернего процесса
            if stripped == 'cd' or stripped.startswith(('cd ', 'cd\t')):
                return await self._handle_cd_command(stripped)

            # Stdin закрыт, чтобы интерактивные команды не перехватывали терминал TUI.
            options = dict(
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT, cwd=self.current_directory, env=env,
            )
            output = _CommandOutput()
            if isinstance(command, tuple):
                process = await asyncio.create_subprocess_exec(
                    *command, start_new_session=not IS_WINDOWS, **options,
                )
            elif IS_WINDOWS:
                process = await asyncio.create_subprocess_shell(stripped, **options)
            else:
                args = shlex.split(stripped)
                if not args:
                    return False, "Не удалось разобрать команду", 1

                process = await asyncio.create_subprocess_exec(*args, start_new_session=True, **options)

            collector = asyncio.create_task(output.collect(process))
            try:
                return_code = await asyncio.wait_for(asyncio.shield(collector), timeout=self.command_timeout)
                return return_code == 0, output.render(), return_code
            except asyncio.TimeoutError:
                await self._kill_process(process)
                preview = output.render()
                message = f"Превышено время выполнения команды ({self.command_timeout} с)"
                return False, f"{message}\n{preview}" if preview else message, 124
            except (asyncio.CancelledError, OSError):
                await self._kill_process(process)
                raise
            finally:
                collector.cancel()
                await asyncio.gather(collector, return_exceptions=True)
                output.close()

        except FileNotFoundError:
            return False, f"Команда '{program}' не найдена", 127
        except ValueError as e:
            # shlex.split: незакрытая кавычка
            return False, f"Не удалось разобрать команду: {e}", 1
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return False, f"Ошибка выполнения: {e}", 126

    @staticmethod
    async def _kill_process(process: asyncio.subprocess.Process) -> None:
        """Принудительное завершение процесса вместе с дочерними (на Windows).

        Args:
            process: Запущенный процесс
        """
        if not IS_WINDOWS:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()
            return
        if process.returncode is None:
            try:
                if IS_WINDOWS:
                    # Завершаем все дерево процессов, иначе останутся дочерние процессы cmd.exe
                    killer = await asyncio.create_subprocess_exec(
                        'taskkill', '/F', '/T', '/PID', str(process.pid),
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL
                    )
                    await killer.wait()
            except ProcessLookupError:
                pass
            await process.wait()

    async def _handle_cd_command(self, command: str) -> Tuple[bool, str, int]:
        """Смена текущей директории чата.

        Поддерживаются относительные и абсолютные пути, ~ и cd без аргументов
        (переход в домашнюю директорию).

        Args:
            command: Команда cd с аргументом

        Returns:
            Tuple[bool, str, int]: (успех, сообщение, код возврата)
        """
        try:
            # Те же правила разбора, что и при автодополнении: "My Docs", My\ Docs, "My Docs"/sub
            args = [argument.value for argument in split_command_arguments(command)]

            target_dir = args[1] if len(args) > 1 else "~"

            target_path = Path(os.path.expanduser(target_dir))
            if not target_path.is_absolute():
                target_path = self.current_directory / target_path

            resolved_path = target_path.resolve()

            if not resolved_path.exists():
                return False, f"cd: {target_dir}: Директория не существует", 1

            if not resolved_path.is_dir():
                return False, f"cd: {target_dir}: Не является директорией", 1

            self.current_directory = resolved_path

            return True, f"Директория изменена на: {resolved_path}", 0

        except Exception as e:
            return False, f"cd: ошибка: {e}", 1

    def get_current_directory(self) -> Path:
        """Получение текущей директории чата.

        Returns:
            Path: Текущая директория
        """
        return self.current_directory

    @staticmethod
    def is_terminal_command(text: str) -> Tuple[bool, Optional[str]]:
        """Проверка, является ли сообщение терминальной командой (начинается с !).

        Args:
            text: Текст сообщения

        Returns:
            Tuple[bool, Optional[str]]: (является ли командой, команда без префикса !)
        """
        text = text.strip()
        if text.startswith('!'):
            return True, text[1:].strip()
        return False, None

    @staticmethod
    def format_command_output(output: str, success: bool, return_code: int) -> str:
        """Форматирование вывода команды в Markdown.

        Args:
            output: Вывод команды
            success: Успешность выполнения
            return_code: Код возврата

        Returns:
            str: Вывод в блоке кода и строка со статусом
        """
        status_text = "Выполнено" if success else f"Завершено с кодом {return_code}"

        return (
            f"```\n{output}\n```\n"
            f"**{status_text}**"
        )

    def is_file_command(self, command: str) -> bool:
        """Проверка, работает ли команда с файлами.

        Args:
            command: Команда без префикса !

        Returns:
            bool: True, если команда из списка FILE_COMMANDS
        """
        command_parts = command.split()
        if not command_parts:
            return False
        return command_parts[0] in self.file_commands
