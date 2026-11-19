"""Предпросмотр изменения файла."""

import asyncio
import importlib.resources
from pathlib import Path

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widget import Widget
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
        action = "Откатить" if undo else "Применить"
        self._choices = {"reject_change": "1. Отклонить", "apply_change": f"2. {action}"}

    def compose(self) -> ComposeResult:
        """Разместить прокручиваемый diff между путём и кнопками."""
        yield Static(str(self.path), markup=False, id="review_path")
        with VerticalScroll(id="diff_scroll"):
            yield Static(self.diff, markup=False, id="file_diff")
        with Vertical(id="review_actions"):
            for widget_id, label in self._choices.items():
                yield Button(f"  {label}", id=widget_id, compact=True)

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        """Отметить выбранный вариант видимым указателем."""
        self._mark_choice(event.widget, "›")

    def on_descendant_blur(self, event: events.DescendantBlur) -> None:
        """Убрать указатель, когда фокус покидает вариант."""
        self._mark_choice(event.widget, " ")

    def _mark_choice(self, widget: Widget, marker: str) -> None:
        """Обновить подпись кнопки без изменения её ширины."""
        if isinstance(widget, Button) and widget.id in self._choices:
            widget.label = f"{marker} {self._choices[widget.id]}"

    def handle_review_key(self, key: str) -> bool:
        """Обработать быстрый выбор, оставив стрелки для прокрутки diff."""
        if key in {"1", "2", "escape", "ctrl+c"}:
            self.decide(key == "2")
            return True
        if key not in {"up", "down"} or not self.is_mounted:
            return False
        decline = self.query_one("#reject_change", Button)
        accept = self.query_one("#apply_change", Button)
        if not (decline.has_focus or accept.has_focus):
            return False
        (accept if decline.has_focus else decline).focus()
        return True

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
