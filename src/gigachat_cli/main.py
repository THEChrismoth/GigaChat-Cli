"""Приложение Textual: интерактивный интерфейс GigaChat CLI."""

from textual.app import App

from gigachat_cli.screens.chat import ChatScreen
from gigachat_cli.screens.start import MenuApp


class Main(App):
    """Приложение GigaChat CLI."""

    SCREENS = {"menu": MenuApp}

    def on_mount(self) -> None:
        """Открыть чат и сразу дать фокус полю ввода."""
        self.push_screen(ChatScreen())
