"""Автодополнение путей к файлам в терминальных командах (!ls, !cat и т.д.)."""

from pathlib import Path
import os
from typing import List, Tuple

from gigachat_cli.utils.command import (
    FILE_COMMANDS,
    POSIX_PARSING,
    quote_command_argument,
    split_command_arguments,
)


def path_separators(posix: bool = POSIX_PARSING) -> Tuple[str, ...]:
    """Получение разделителей пути.

    Обратный слеш разделяет путь только на Windows: в POSIX это допустимый символ имени файла.

    Args:
        posix: Правила POSIX или Windows

    Returns:
        Tuple[str, ...]: Разделители пути
    """
    return ('/',) if posix else ('/', '\\')


# Разделители пути для текущей ОС
PATH_SEPARATORS = path_separators()


def split_path_argument(argument: str, separators: Tuple[str, ...] = PATH_SEPARATORS) -> Tuple[str, str]:
    r"""Разделение аргумента-пути на директорию (с завершающим разделителем) и имя.

    Args:
        argument: Аргумент команды, например "src/gig" или "C:\Users\da"
        separators: Разделители пути (по умолчанию - для текущей ОС)

    Returns:
        Tuple[str, str]: (директория, начало имени файла)
    """
    separator_index = max(argument.rfind(separator) for separator in separators)
    return argument[:separator_index + 1], argument[separator_index + 1:]


def complete_path_argument(text: str, name: str, posix: bool = POSIX_PARSING) -> str:
    """Подстановка выбранного имени файла в последний аргумент команды.

    Последний аргумент заменяется целиком: путь до имени сохраняется, а результат
    экранируется (пробелы и спецсимволы) в стиле, которым пользователь начал аргумент.

    Args:
        text: Текст команды из поля ввода
        name: Выбранное имя файла или директории
        posix: Правила POSIX-shell или cmd.exe

    Returns:
        str: Новый текст команды
    """
    arguments = split_command_arguments(text, posix)
    if len(arguments) < 2:
        separator = '' if not text or text[-1].isspace() else ' '
        return text + separator + quote_command_argument(name, posix=posix)

    last = arguments[-1]
    dir_part, _ = split_path_argument(last.value, path_separators(posix))
    return text[:last.start] + quote_command_argument(dir_part + name, last.quote, posix)


class FileUtils:
    """Подбор файлов для автодополнения аргументов терминальных команд."""

    def __init__(self, command_utils):
        """Создание утилиты.

        Args:
            command_utils: Утилита команд, хранящая текущую директорию
        """
        self.command_utils = command_utils
        self.file_commands = FILE_COMMANDS

    def should_show_files(self, text: str) -> bool:
        """Проверка необходимости показа автодополнения файлов.

        Args:
            text: Текст из поля ввода

        Returns:
            bool: True, если введена файловая команда (!ls, !cat и т.д.) и начат ее аргумент
        """
        if not text.strip().startswith('!'):
            return False

        arguments = split_command_arguments(text)
        command = arguments[0].value[1:]  # Без префикса !

        if command not in self.file_commands:
            return False

        # После пробела начинается новый (пустой) аргумент - его тоже дополняем
        return len(arguments) >= 2

    def get_files_for_completion(self, text: str) -> Tuple[List[str], str, str]:
        """Получение файлов и директорий, подходящих к последнему аргументу команды.

        Args:
            text: Текст команды из поля ввода

        Returns:
            Tuple[List[str], str, str]: (имена - сначала директории, текст команды, директория поиска)
        """
        current_dir = self.command_utils.get_current_directory()

        # Дополняется последний аргумент (пустой, если строка заканчивается пробелом)
        arguments = split_command_arguments(text)
        if len(arguments) < 2:
            return [], text, str(current_dir)

        # Аргумент уже без кавычек и экранирования
        dir_part, search_pattern = split_path_argument(arguments[-1].value)

        # Директория поиска: абсолютный путь, путь от ~ или относительно текущей директории
        dir_path = Path(os.path.expanduser(dir_part)) if dir_part else Path()
        base_path = dir_path if dir_path.is_absolute() else current_dir / dir_path

        if not base_path.exists() or not base_path.is_dir():
            return [], text, str(base_path)

        try:
            # Скрытые файлы тоже показываются
            all_items = []
            for item in base_path.iterdir():
                if not search_pattern:
                    all_items.append(item.name)
                else:
                    if item.name.startswith(search_pattern):
                        all_items.append(item.name)

            def sort_key(item):
                item_path = base_path / item
                return (0 if item_path.is_dir() else 1, item.lower())

            all_items.sort(key=sort_key)

            return all_items, text, str(base_path)

        except (PermissionError, OSError):
            return [], text, str(base_path)
