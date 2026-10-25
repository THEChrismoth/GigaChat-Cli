"""Терминальные команды: разбор командной строки, экранирование аргументов и выполнение."""

import asyncio
import shlex
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Optional


IS_WINDOWS = os.name == 'nt'

# Правила разбора командной строки: POSIX (shlex) или cmd.exe на Windows
POSIX_PARSING = not IS_WINDOWS


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

    async def execute_system_command(self, command: str) -> Tuple[bool, str, int]:
        r"""Выполнение команды в текущей директории.

        На Windows команда выполняется через cmd.exe (доступны dir, type и пути с \),
        в остальных ОС - напрямую, без shell. Ввод с клавиатуры недоступен,
        время выполнения ограничено, при отмене задачи процесс завершается.

        Args:
            command: Команда без префикса !

        Returns:
            Tuple[bool, str, int]: (успех, вывод stdout и stderr, код возврата)

        Raises:
            asyncio.CancelledError: Выполнение отменено (процесс при этом завершается)
        """
        if not command.strip():
            return False, "Пустая команда", 1

        stripped = command.strip()
        program = stripped.split()[0]

        try:
            # cd меняет директорию чата, а не дочернего процесса
            if stripped == 'cd' or stripped.startswith(('cd ', 'cd\t')):
                return await self._handle_cd_command(stripped)

            # stdin закрыт, чтобы интерактивные команды не перехватывали терминал TUI
            if IS_WINDOWS:
                process = await asyncio.create_subprocess_shell(
                    stripped,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.current_directory
                )
            else:
                args = shlex.split(stripped)
                if not args:
                    return False, "Не удалось разобрать команду", 1

                process = await asyncio.create_subprocess_exec(
                    args[0],
                    *args[1:],
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.current_directory
                )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.command_timeout)
            except asyncio.TimeoutError:
                await self._kill_process(process)
                return False, f"Превышено время выполнения команды ({self.command_timeout} с)", 1
            except asyncio.CancelledError:
                await self._kill_process(process)
                raise
            return_code = process.returncode

            output_lines = []

            if stdout:
                output_lines.append(_decode_output(stdout))

            if stderr:
                output_lines.append(_decode_output(stderr))

            output_text = "\n".join(output_lines)

            return return_code == 0, output_text, return_code

        except FileNotFoundError:
            return False, f"Команда '{program}' не найдена", 1
        except ValueError as e:
            # shlex.split: незакрытая кавычка
            return False, f"Не удалось разобрать команду: {e}", 1
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return False, f"Ошибка выполнения: {e}", 1

    @staticmethod
    async def _kill_process(process: asyncio.subprocess.Process) -> None:
        """Принудительное завершение процесса вместе с дочерними (на Windows).

        Args:
            process: Запущенный процесс
        """
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
                else:
                    process.kill()
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
