"""Стартовый экран: меню приложения."""

import importlib.resources

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import ListView, ListItem, Label
from textual.containers import Container

from gigachat_cli.screens.chat import ChatScreen
from gigachat_cli.screens.help import HelpScreen
from gigachat_cli.widgets.banner import Banner


class MenuApp(Screen):
    """Экран главного меню: переход в чат, справка, выход."""

    CSS = importlib.resources.files("gigachat_cli.styles").joinpath("start.css").read_text()

    def compose(self) -> ComposeResult:
        """Создание виджетов экрана.

        Yields:
            Контейнер с баннером и списком пунктов меню
        """
        yield Container(
            Banner(),
            Container(
                ListView(
                    ListItem(Label("🚀 Начать использование", classes="menu-item"), id="start", classes="menu-button"),
                    ListItem(Label("❓ Помощь и инструкции", classes="menu-item"), id="help", classes="menu-button"),
                    ListItem(Label("🚪 Выход", classes="menu-item"), id="exit", classes="menu-button"),
                    classes="menu-list"
                ),
                classes="buttons-container"
            ),
            classes="main-container"
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Переход по выбранному пункту меню.

        Args:
            event: Событие выбора элемента списка
        """
        choice = event.item.id
        if choice == "start":
            self.app.push_screen(ChatScreen())
        elif choice == "help":
            self.app.push_screen(HelpScreen())
        elif choice == "exit":
            self.app.exit()

    def on_mount(self) -> None:
        """Фокус на списке меню для навигации с клавиатуры."""
        self.query_one(ListView).focus()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Выделение подсвеченного пункта меню классом active.

        Args:
            event: Событие подсветки элемента списка
        """
        list_view = self.query_one(ListView)
        for item in list_view.children:
            item.remove_class("active")

        if event.item:
            event.item.add_class("active")
