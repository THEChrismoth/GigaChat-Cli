"""Команды чата для предложения и отката изменения файла."""

import re
from string import punctuation
from typing import TYPE_CHECKING

from textual.widgets import Input

from gigachat_cli.screens.file_review import FileReviewScreen
from gigachat_cli.utils.command import split_command_arguments
from gigachat_cli.utils.core import chat_manager
from gigachat_cli.utils.file_edit import FileEdit, FileEditError, read_snapshot

if TYPE_CHECKING:
    from gigachat_cli.screens.chat import ChatScreen


def _escape_markdown(text: str) -> str:
    """Показать пути и сообщения об ошибках как текст."""
    return re.sub(f"[{re.escape(punctuation)}]", lambda char: "\\" + char[0], text)


class FileEditHandler:
    """Показать предложения модели и помнить последнюю правку для отката."""

    def __init__(self) -> None:
        """Начать сеанс без сохранённых правок."""
        self._undo: FileEdit | None = None

    async def handle(self, user_text: str, input_field: Input, screen: "ChatScreen") -> bool:
        """Подготовить правку или показать обратное изменение."""
        command = user_text.split(maxsplit=1)[0]
        if command not in {"/edit", "/undo"}:
            return False

        input_field.value = ""
        undo = command == "/undo"
        try:
            if undo:
                if user_text != "/undo":
                    raise FileEditError("Использование: /undo")
                if self._undo is None:
                    raise FileEditError("В этом чате нет правки для отката.")
                edit = self._undo
            else:
                arguments = split_command_arguments(user_text)
                if len(arguments) < 3 or not arguments[1].value:
                    raise FileEditError('Использование: /edit "путь к файлу" задание')
                root = screen.command_utils.get_current_directory()
                snapshot = read_snapshot(root, arguments[1].value)
                name = _escape_markdown(snapshot.relative_path.as_posix())
                screen.update_chat_display(f"Подготовка правки для **{name}**. Esc — отменить.")
                edit = await chat_manager.propose_file_edit(snapshot, user_text[arguments[2].start:])

            diff = edit.diff()
            if not diff:
                screen.update_chat_display("Содержимое файла не изменилось.")
                return True
        except (FileEditError, OSError) as error:
            screen.update_chat_display(f"**Ошибка:** {_escape_markdown(str(error))}")
            return True

        path = edit.before.root / edit.before.relative_path
        screen.app.push_screen(
            FileReviewScreen(path, diff, undo=undo),
            lambda approved: self._finish_review(screen, edit, undo, approved),
        )
        return True

    def _finish_review(self, screen: "ChatScreen", edit: FileEdit, undo: bool, approved: bool | None) -> None:
        """Применить подтверждённый вариант и сообщить результат в чате."""
        name = _escape_markdown(edit.before.relative_path.as_posix())
        if not approved:
            result = f"Изменение файла **{name}** отклонено."
        else:
            try:
                inverse = edit.apply()
            except (FileEditError, OSError) as error:
                result = f"**Ошибка:** {_escape_markdown(str(error))}"
            else:
                self._undo = None if undo else inverse
                verb = "отменено" if undo else "применено. /undo — откатить"
                result = f"Изменение файла **{name}** {verb}."
        screen.update_chat_display(result)
