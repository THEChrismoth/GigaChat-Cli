"""Приложение Textual: интерактивный интерфейс GigaChat CLI."""

from textual.app import App

from gigachat_cli.screens.chat import ChatScreen


class Main(App):
    """Приложение GigaChat CLI."""

    def __init__(self) -> None:
        """Инициализировать вывод с палитрой терминала."""
        super().__init__(ansi_color=True)
        self.theme = "textual-ansi"

    def on_mount(self) -> None:
        """Открыть чат и сразу дать фокус полю ввода."""
        self.push_screen(ChatScreen())
