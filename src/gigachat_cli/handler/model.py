"""Обработчик команды /model: выбор модели GigaChat."""

from textual.widgets import Input

from gigachat_cli.utils.config import Config


class ModelHandler:
    """Обработчик команды /model: показ списка моделей и сохранение выбора."""

    def __init__(self, cfg: Config, screen=None):
        """Создание обработчика.

        Args:
            cfg: Конфигурация, в которую сохраняется выбранная модель
            screen: Экран чата для отображения результата выбора
        """
        self.cfg = cfg
        self.screen = screen
        # Идентификатор модели в API -> название для пользователя
        self.model_names = {
            "GigaChat-2": "GigaChat 2 Lite",
            "GigaChat-2-Pro": "GigaChat 2 Pro",
            "GigaChat-2-Max": "GigaChat 2 Max",
        }

    async def handle(self, user_text: str, input_field: Input, screen) -> bool:
        """Обработка команды /model: показ списка моделей для выбора.

        Args:
            user_text: Текст сообщения пользователя
            input_field: Поле ввода
            screen: Экран чата

        Returns:
            bool: True, если команда обработана
        """
        if not user_text.lower().startswith('/model'):
            return False

        if user_text.strip() == '/model':
            model_list = [name for name in self.model_names.values()]

            screen.selector_manager.show_selector(
                items=model_list,
                title="Выберите модель:",
                callback=self._on_model_selected
            )

            input_field.value = ""
            input_field.focus()
            return True

        return False

    def _on_model_selected(self, selected_item: str, index: int):
        """Сохранение модели, выбранной в списке.

        Args:
            selected_item: Название модели для пользователя
            index: Индекс выбранного элемента в списке
        """
        model_key = None
        for key, name in self.model_names.items():
            if name == selected_item:
                model_key = key
                break

        if model_key:
            self.cfg.set_model(model_key)
            self.screen.update_chat_display(f"**Система:** ✅ Выбрана модель: **{selected_item}**")
            self.screen._update_model_display()
