"""Обработчик команды /help: краткая справка в чате."""

from textual.widgets import Input


class HelpHandler:
    """Обработчик команды /help."""

    async def handle(self, user_text: str, input_field: Input, screen) -> bool:
        """Вывод справки по командам в чат.

        Args:
            user_text: Текст сообщения пользователя
            input_field: Поле ввода
            screen: Экран чата

        Returns:
            bool: True, если команда обработана
        """
        if user_text.strip() != '/help':
            return False

        # Текст справки
        help_text = """
**Доступные команды:**

- `/model` - Выбор модели GigaChat
- `/help`  - Показать эту справку
- `/menu`  - Возврат в меню
- `/exit`  - Выйти из приложения
- `!команда` - Выполнить терминальную команду

Упомяните файл в запросе (например, `main.py`), чтобы передать его содержимое в контекст.

**Управление:**

- `Tab`/`Shift+Tab` - навигация по автодополнению
- `↑`/`↓` - навигация в селекторах
- `Enter` - подтвердить выбор
- `Esc` - отмена выбора / прерывание запроса или команды
"""
        # Очистка экрана и отображение справки
        screen.clear_chat_display()
        screen.update_chat_display(help_text)
        
        # Очистка поля ввода
        input_field.value = ""
        
        return True
