"""Приложение Textual: интерактивный интерфейс GigaChat CLI."""

from textual.app import App

from gigachat_cli.screens.start import MenuApp


class Main(App):
    """Приложение GigaChat CLI."""

    def on_mount(self) -> None:
        """Открытие стартового экрана меню."""
        self.push_screen(MenuApp())
