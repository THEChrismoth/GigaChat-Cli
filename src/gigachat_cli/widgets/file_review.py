"""Предпросмотр изменения файла."""

import asyncio
import importlib.resources
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Static


class FileReview(Vertical):
    """Показать diff и запросить явное подтверждение."""

    DEFAULT_CSS = importlib.resources.files("gigachat_cli.styles").joinpath("file_review.css").read_text()

    def __init__(self, path: Path, diff: str, *, undo: bool) -> None:
        """Подготовить путь, diff и подпись кнопки подтверждения."""
        super().__init__()
        self._decision: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self.path = path
        self.diff = diff
        self.apply_label = "Откатить" if undo else "Применить"

    def compose(self) -> ComposeResult:
        """Разместить прокручиваемый diff между путём и кнопками."""
        yield Static(str(self.path), markup=False, id="review_path")
        with VerticalScroll(id="diff_scroll"):
            yield Static(self.diff, markup=False, id="file_diff")
        with Horizontal(id="review_actions"):
            yield Button("Отклонить", id="reject_change", compact=True)
            yield Button(self.apply_label, id="apply_change", compact=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Передать решение пользователя в чат."""
        event.stop()
        self.decide(event.button.id == "apply_change")

    def decide(self, approved: bool) -> None:
        """Зафиксировать только первое решение."""
        if not self._decision.done():
            self._decision.set_result(approved)

    async def wait_for_decision(self) -> bool:
        """Дождаться нажатия кнопки или отклонения через Escape."""
        return await self._decision
