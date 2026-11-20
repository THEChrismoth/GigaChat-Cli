"""Приложение Textual: интерактивный интерфейс GigaChat CLI."""

from pathlib import Path

from textual.app import App

from gigachat_cli.core.sessions import SessionStore
from gigachat_cli.screens.chat import ChatScreen


class Main(App):
    """Приложение GigaChat CLI."""

    def __init__(self, *, persist_sessions: bool = True) -> None:
        """Инициализировать вывод с палитрой терминала."""
        super().__init__(ansi_color=True)
        self.theme = "textual-ansi"
        self._persist_sessions = persist_sessions

    def on_mount(self) -> None:
        """Открыть чат и сразу дать фокус полю ввода."""
        store = SessionStore(Path.home() / ".gigachat" / "sessions.sqlite3", Path.cwd()) if self._persist_sessions else None
        self.push_screen(ChatScreen(store=store))
