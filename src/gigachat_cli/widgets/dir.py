"""Строка состояния с текущей директорией."""

import os
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
            str: Строка с иконкой и путем директории
        """
        return f"📁 Директория: {self.current_dir}"
