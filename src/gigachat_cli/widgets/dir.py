"""Строка состояния с текущей директорией."""

import os
from pathlib import Path

from textual.widgets import Static


class Dir(Static):
    """Виджет отображения текущей рабочей директории."""

    def __init__(self, *args, **kwargs):
        """Создание виджета с текущей директорией процесса.

        Args:
            *args: Позиционные аргументы Static
            **kwargs: Именованные аргументы Static
        """
        super().__init__(*args, **kwargs)
        self.current_dir = os.path.abspath(os.curdir)

    def render(self) -> str:
        """Отрисовка текущей директории.

        Returns:
            str: Строка с иконкой и путем директории (домашняя директория сокращается до ~)
        """
        return f"📁 Директория: {shorten_home(self.current_dir)}"


def shorten_home(path: str) -> str:
    """Замена домашней директории в начале пути на ~.

    Args:
        path: Путь к директории

    Returns:
        str: Путь вида ~/projects/app или исходный путь, если он вне домашней директории
    """
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home.rstrip("/\\") + os.sep):
        return "~" + path[len(home.rstrip("/\\")):]
    return path
