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
    """Разделители пути: обратный слеш - только на Windows, в POSIX это допустимый символ имени файла"""
    return ('/',) if posix else ('/', '\\')


# Разделители пути для текущей ОС
PATH_SEPARATORS = path_separators()


def split_path_argument(argument: str, separators: Tuple[str, ...] = PATH_SEPARATORS) -> Tuple[str, str]:
    """
    Разделение аргумента-пути на директорию (с завершающим разделителем) и имя

    Args:
        argument: Аргумент команды, например "src/gig" или "C:\\Users\\da"
        separators: Разделители пути (по умолчанию - для текущей ОС)

    Returns:
        Tuple[str, str]: (директория, начало имени файла)
    """
    separator_index = max(argument.rfind(separator) for separator in separators)
    return argument[:separator_index + 1], argument[separator_index + 1:]


def complete_path_argument(text: str, name: str, posix: bool = POSIX_PARSING) -> str:
    """
    Подстановка выбранного имени файла в последний аргумент команды

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
    """Утилита для работы с файловой системой и автодополнением файлов"""

    def __init__(self, command_utils):
        """
        Инициализация утилиты файлов

        Args:
            command_utils: Утилита команд для получения текущей директории
        """
        self.command_utils = command_utils
        self.file_commands = FILE_COMMANDS
    
    def should_show_files(self, text: str) -> bool:
        """
        Проверка необходимости показа автодополнения файлов
        
        Args:
            text: Текст из поля ввода
            
        Returns:
            bool: True если нужно показывать автодополнение файлов
        """
        if not text.strip().startswith('!'):
            return False

        # Разбираем команду на аргументы с учетом кавычек
        arguments = split_command_arguments(text)
        command = arguments[0].value[1:]  # Убираем префикс !

        # Проверяем, является ли команда файловой
        if command not in self.file_commands:
            return False

        # Показываем файлы если после команды начат аргумент (в том числе пустой - после пробела)
        return len(arguments) >= 2
    
    def get_files_for_completion(self, text: str) -> Tuple[List[str], str, str]:
        """
        Получение списка файлов для автодополнения
        
        Args:
            text: Текст команды для автодополнения
            
        Returns:
            Tuple[List[str], str, str]: (список файлов, полная команда, текущий путь)
        """
        current_dir = self.command_utils.get_current_directory()

        # Дополняется последний аргумент (пустой, если строка заканчивается пробелом)
        arguments = split_command_arguments(text)
        if len(arguments) < 2:
            return [], text, str(current_dir)

        # Разделение аргумента (без кавычек и экранирования) на директорию и шаблон имени
        dir_part, search_pattern = split_path_argument(arguments[-1].value)

        # Определение базового пути для поиска (абсолютный, ~ или относительный)
        dir_path = Path(os.path.expanduser(dir_part)) if dir_part else Path()
        base_path = dir_path if dir_path.is_absolute() else current_dir / dir_path
        
        # Проверка существования базового пути
        if not base_path.exists() or not base_path.is_dir():
            return [], text, str(base_path)
        
        try:
            # Получение всех файлов и директорий (включая скрытые)
            all_items = []
            for item in base_path.iterdir():
                # Если search_pattern пустой, показываем все файлы
                if not search_pattern:
                    all_items.append(item.name)
                else:
                    # Фильтрация по паттерну (показываем все совпадения)
                    if item.name.startswith(search_pattern):
                        all_items.append(item.name)
            
            # Сортировка: сначала директории, потом файлы
            def sort_key(item):
                item_path = base_path / item
                return (0 if item_path.is_dir() else 1, item.lower())
            
            all_items.sort(key=sort_key)
            
            return all_items, text, str(base_path)
            
        except (PermissionError, OSError):
            return [], text, str(base_path)
