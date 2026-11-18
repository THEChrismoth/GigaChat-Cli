"""Предпросмотр изменения файла."""

import importlib.resources
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class FileReviewScreen(ModalScreen[bool]):
    """Показать diff и запросить явное подтверждение."""

    CSS = importlib.resources.files("gigachat_cli.styles").joinpath("file_review.css").read_text()
    AUTO_FOCUS = "#reject_change"
    BINDINGS = [("escape", "reject", "Отклонить")]

    def __init__(self, path: Path, diff: str, *, undo: bool) -> None:
        """Подготовить путь, diff и подпись кнопки подтверждения."""
        super().__init__()
        self.path = path
        self.diff = diff
        self.apply_label = "Откатить" if undo else "Применить"

    def compose(self) -> ComposeResult:
        """Разместить прокручиваемый diff между путём и кнопками."""
        with Vertical(id="file_review"):
            yield Static(str(self.path), markup=False, id="review_path")
            with VerticalScroll(id="diff_scroll"):
                yield Static(self.diff, markup=False, id="file_diff")
            with Horizontal(id="review_actions"):
                yield Button("Отклонить", id="reject_change")
                yield Button(self.apply_label, variant="primary", id="apply_change")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Передать решение пользователя в чат."""
        self.dismiss(event.button.id == "apply_change")

    def action_reject(self) -> None:
        """Закрыть предпросмотр через Escape."""
        self.dismiss(False)
