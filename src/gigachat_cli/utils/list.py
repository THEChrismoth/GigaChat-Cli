"""Список команд чата (/help, /model и т.д.) и их фильтрация для автодополнения."""


class ListUtils:
    """Команды чата с описаниями и их фильтрация по введенному тексту."""

    def __init__(self):
        """Создание списка доступных команд."""
        self.commands = {
            "exit": "Выйти из приложения",
            "model": "Выбор модели GigaChat",
            "help": "Показать справку по командам",
            "menu":  "Возврат в меню"
        }

    def get_filtered_commands(self, text: str) -> list[str]:
        """Получение команд, начинающихся с введенного текста.

        Args:
            text: Текст из поля ввода (начинается с /)

        Returns:
            list[str]: Отсортированный список команд с префиксом /
        """
        if not text.startswith('/'):
            return []

        search_text = text[1:].lower()

        filtered = [f"/{cmd}" for cmd in self.commands.keys() if cmd.startswith(search_text)]
        filtered.sort()
        return filtered

    def get_commands_with_descriptions(self, text: str) -> list[tuple[str, str]]:
        """Получение команд, начинающихся с введенного текста, вместе с описаниями.

        Args:
            text: Текст из поля ввода (начинается с /)

        Returns:
            list[tuple[str, str]]: Отсортированный список пар (команда, описание)
        """
        if not text.startswith('/'):
            return []

        search_text = text[1:].lower()

        filtered = [
            (f"/{cmd}", desc)
            for cmd, desc in self.commands.items()
            if cmd.startswith(search_text)
        ]
        filtered.sort(key=lambda x: x[0])
        return filtered

    def should_show_commands(self, text: str) -> bool:
        """Проверка необходимости показа автодополнения команд.

        Args:
            text: Текст из поля ввода

        Returns:
            bool: True, если текст начинается с /
        """
        return text.startswith('/')
