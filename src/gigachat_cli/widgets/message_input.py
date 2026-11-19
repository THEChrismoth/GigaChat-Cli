"""Многострочный редактор запроса и история отправленного текста."""

from textual.binding import Binding
from textual.message import Message
from textual.widgets import TextArea


class MessageInput(TextArea):
    """Редактор с явной отправкой, переносом строки и возвратом к черновику."""

    BINDINGS = [
        Binding("enter", "submit", "Отправить", show=False, priority=True),
        Binding("f2,shift+enter", "newline", "Новая строка", show=False, priority=True),
        Binding("f3,alt+up", "previous_message", "Предыдущий запрос", show=False, priority=True),
        Binding("f4,alt+down", "next_message", "Следующий запрос", show=False, priority=True),
    ]

    class Submitted(Message):
        """Пользователь нажал Enter в редакторе."""

    def __init__(self, *, id: str) -> None:
        """Создать редактор с пустым черновиком."""
        super().__init__(id=id, placeholder="Введите сообщение")
        self._messages: list[str] = []
        self._history_index = 0
        self._draft = ""

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Увеличить высоту редактора при добавлении строк."""
        self.styles.height = min(self.document.line_count, 6) + 2

    def remember(self, text: str) -> None:
        """Сохранить отправленный текст и закончить просмотр истории."""
        if not self._messages or text != self._messages[-1]:
            self._messages.append(text)
            self._messages = self._messages[-100:]
        self._history_index = len(self._messages)
        self._draft = ""

    def action_submit(self) -> None:
        """Попросить экран обработать Enter."""
        self.post_message(self.Submitted())

    def action_newline(self) -> None:
        """Вставить перевод строки вместо текущего выделения."""
        result = self.replace("\n", *self.selection, maintain_selection_offset=False)
        self.move_cursor(result.end_location)

    def action_previous_message(self) -> None:
        """Вернуться к предыдущему запросу, запомнив текущий черновик."""
        if self._history_index == 0:
            return
        if self._history_index == len(self._messages):
            self._draft = self.text
        self._history_index -= 1
        self.text = self._messages[self._history_index]
        self.move_cursor(self.document.end)

    def action_next_message(self) -> None:
        """Перейти к следующему запросу или восстановить черновик."""
        if self._history_index == len(self._messages):
            return
        self._history_index += 1
        if self._history_index == len(self._messages):
            self.text = self._draft
        else:
            self.text = self._messages[self._history_index]
        self.move_cursor(self.document.end)
