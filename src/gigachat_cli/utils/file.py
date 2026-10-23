from pathlib import Path
import os
from typing import List, Tuple

from gigachat_cli.utils.command import FILE_COMMANDS


def split_path_argument(argument: str) -> Tuple[str, str]:
    """
    Разделение аргумента-пути на директорию (с завершающим разделителем) и имя

    Args:
        argument: Аргумент команды, например "src/gig" или "C:\\Users\\da"

    Returns:
        Tuple[str, str]: (директория, начало имени файла)
    """
    separator_index = max(argument.rfind('/'), argument.rfind('\\'))
    return argument[:separator_index + 1], argument[separator_index + 1:]


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
        
        # Разбираем команду на части
        parts = text.strip().split()
        if len(parts) < 1:
            return False
        
        command = parts[0][1:]  # Убираем префикс !
        
        # Проверяем, является ли команда файловой
        if command not in self.file_commands:
            return False
        
        # Показываем файлы если есть пробел после команды или есть аргументы
        return len(parts) >= 2 or text.endswith(' ')
    
    def get_files_for_completion(self, text: str) -> Tuple[List[str], str, str]:
        """
        Получение списка файлов для автодополнения
        
        Args:
            text: Текст команды для автодополнения
            
        Returns:
            Tuple[List[str], str, str]: (список файлов, полная команда, текущий путь)
        """
        parts = text.strip().split()
        if len(parts) < 1:
            return [], text, ""

        current_dir = self.command_utils.get_current_directory()

        # После пробела начинается новый аргумент, иначе дополняется последний
        if text.endswith(' '):
            last_part = ""
        elif len(parts) >= 2:
            last_part = parts[-1]
        else:
            return [], text, str(current_dir)

        # Разделение аргумента на директорию и шаблон имени (поддерживаются / и \)
        dir_part, search_pattern = split_path_argument(last_part)

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
