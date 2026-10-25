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
    """Аргумент командной строки"""
    start: int                    # Позиция начала аргумента в исходной строке
    value: str                    # Значение без кавычек и экранирования
    quote: Optional[str] = None   # Кавычка, которой открыт аргумент (если есть)


def split_command_arguments(text: str, posix: bool = POSIX_PARSING) -> List[CommandArgument]:
    """
    Разбор командной строки на аргументы с учетом кавычек и экранирования

    В отличие от shlex.split не завершается ошибкой на незакрытой кавычке или
    завершающем обратном слеше: строка разбирается в процессе ввода.
    Если строка заканчивается пробелом вне кавычек, добавляется пустой аргумент,
    который пользователь начинает вводить.

    Args:
        text: Командная строка
        posix: Правила POSIX-shell (кавычки ' и ", экранирование \\)
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
    """
    Экранирование аргумента для командной строки

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

# Список команд, работающих с файловой системой
FILE_COMMANDS = ['cd', 'ls', 'cp', 'mv', 'rm', 'mkdir', 'cat', 'touch', 'find', 'grep']
if IS_WINDOWS:
    FILE_COMMANDS += ['dir', 'type', 'copy', 'move', 'del', 'rmdir', 'md']


def _decode_output(data: bytes) -> str:
    """Декодирование вывода команды (cmd.exe на Windows пишет в OEM-кодировке)"""
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        if IS_WINDOWS:
            import ctypes
            return data.decode(f"cp{ctypes.windll.kernel32.GetOEMCP()}", errors='replace')
        return data.decode('utf-8', errors='replace')


class CommandUtils:
    """Утилита для выполнения системных команд и работы с файловой системой"""

    def __init__(self, command_timeout: float = 60):
        """Инициализация утилиты команд"""
        self.current_directory = Path.cwd()
        self.command_timeout = command_timeout
        self.file_commands = FILE_COMMANDS
    
    async def execute_system_command(self, command: str) -> Tuple[bool, str, int]:
        """
        Выполнение системной команды и возврат результата
        
        Args:
            command: Строка команды для выполнения
            
        Returns:
            Tuple[bool, str, int]: (успех, вывод, код возврата)
        """
        if not command.strip():
            return False, "Пустая команда", 1
        
        stripped = command.strip()
        program = stripped.split()[0]

        try:
            # Обрабатываем команду cd отдельно
            if stripped == 'cd' or stripped.startswith(('cd ', 'cd\t')):
                return await self._handle_cd_command(stripped)

            # stdin закрыт, чтобы интерактивные команды не перехватывали терминал TUI
            if IS_WINDOWS:
                # Через cmd.exe доступны встроенные команды (dir, type) и пути с обратными слешами
                process = await asyncio.create_subprocess_shell(
                    stripped,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.current_directory
                )
            else:
                # Разбираем команду с поддержкой флагов
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

            # Читаем вывод команды с ограничением по времени
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.command_timeout)
            except asyncio.TimeoutError:
                await self._kill_process(process)
                return False, f"Превышено время выполнения команды ({self.command_timeout} с)", 1
            except asyncio.CancelledError:
                await self._kill_process(process)
                raise
            return_code = process.returncode

            # Формируем результат выполнения
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
            return False, f"Не удалось разобрать команду: {e}", 1
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return False, f"Ошибка выполнения: {e}", 1

    @staticmethod
    async def _kill_process(process: asyncio.subprocess.Process) -> None:
        """Принудительное завершение процесса"""
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
        """
        Обработка команды смены директории
        
        Args:
            command: Команда cd с аргументами
            
        Returns:
            Tuple[bool, str, int]: (успех, сообщение, код возврата)
        """
        try:
            # Те же правила разбора, что и при автодополнении: "My Docs", My\ Docs, "My Docs"/sub
            args = [argument.value for argument in split_command_arguments(command)]

            # cd без аргументов - переход в домашнюю директорию
            target_dir = args[1] if len(args) > 1 else "~"

            # Раскрываем ~ и делаем относительный путь абсолютным относительно текущей директории
            target_path = Path(os.path.expanduser(target_dir))
            if not target_path.is_absolute():
                target_path = self.current_directory / target_path

            # Разрешаем путь (обрабатываем .. и .)
            resolved_path = target_path.resolve()
            
            # Проверяем существование директории
            if not resolved_path.exists():
                return False, f"cd: {target_dir}: Директория не существует", 1
            
            if not resolved_path.is_dir():
                return False, f"cd: {target_dir}: Не является директорией", 1
            
            # Меняем текущую директорию
            self.current_directory = resolved_path
            
            return True, f"Директория изменена на: {resolved_path}", 0
            
        except Exception as e:
            return False, f"cd: ошибка: {e}", 1
    
    def get_current_directory(self) -> Path:
        """
        Получение текущей рабочей директории
        
        Returns:
            Path: Текущая директория
        """
        return self.current_directory
    
    @staticmethod
    def is_terminal_command(text: str) -> Tuple[bool, Optional[str]]:
        """
        Проверка является ли текст терминальной командой
        
        Args:
            text: Текст для проверки
            
        Returns:
            Tuple[bool, Optional[str]]: (является командой, команда без префикса)
        """
        text = text.strip()
        if text.startswith('!'):
            return True, text[1:].strip()
        return False, None
    
    @staticmethod
    def format_command_output(output: str, success: bool, return_code: int) -> str:
        """
        Форматирование вывода команды в Markdown
        
        Args:
            output: Вывод команды
            success: Успешность выполнения
            return_code: Код возврата
            
        Returns:
            str: Отформатированный вывод в Markdown
        """
        status_text = "Выполнено" if success else f"Завершено с кодом {return_code}"
        
        return (
            f"```\n{output}\n```\n"
            f"**{status_text}**"
        )
    
    def is_file_command(self, command: str) -> bool:
        """
        Проверка является ли команда файловой
        
        Args:
            command: Команда для проверки
            
        Returns:
            bool: True если команда работает с файловой системой
        """
        command_parts = command.split()
        if not command_parts:
            return False
        return command_parts[0] in self.file_commands
