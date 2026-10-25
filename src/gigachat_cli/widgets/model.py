"""Строка состояния с текущей моделью GigaChat."""

from textual.widgets import Static
from gigachat_cli.utils.config import Config


class Model(Static):
    """Виджет отображения текущей модели GigaChat."""

    def __init__(self, *args, **kwargs):
        """Создание виджета с моделью из конфигурации.

        Args:
            *args: Позиционные аргументы Static
            **kwargs: Именованные аргументы Static
        """
        super().__init__(*args, **kwargs)
        config = Config()
        self.current_model = config.get_model()

    def render(self) -> str:
        """Отрисовка названия модели.

        Returns:
            str: Строка с читаемым названием модели
        """
        model_names = {
            "GigaChat-2": "GigaChat 2 Lite",
            "GigaChat-2-Pro": "GigaChat 2 Pro",
            "GigaChat-2-Max": "GigaChat 2 Max",
        }
        display_name = model_names.get(self.current_model, self.current_model)
        return f"Модель: {display_name}"
