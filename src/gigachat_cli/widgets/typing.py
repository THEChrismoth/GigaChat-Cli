"""Анимированный индикатор ожидания ответа."""

import asyncio
from textual.widgets import Static


class TypingIndicator(Static):
    """Индикатор ожидания ответа: анимированные точки."""

    def __init__(self):
        """Создание индикатора; анимация запускается при монтировании."""
        super().__init__(".")
        self._is_animating = False
        self._animation_task = None

    def on_mount(self) -> None:
        """Запуск анимации при монтировании виджета."""
        self.add_class("typing")
        self._is_animating = True
        self._animation_task = asyncio.create_task(self._animate_typing())

    async def _animate_typing(self) -> None:
        """Циклическая смена количества точек."""
        dots = [".", "..", "...", ""]
        index = 0
        while self._is_animating and self.has_class("typing"):
            self.update(dots[index])
            index = (index + 1) % len(dots)
            await asyncio.sleep(0.4)

    def stop_animation(self) -> None:
        """Остановка анимации и очистка текста."""
        self._is_animating = False
        if self._animation_task and not self._animation_task.done():
            self._animation_task.cancel()
        self.update("")

    def on_unmount(self) -> None:
        """Остановка анимации при удалении виджета."""
        self.stop_animation()
