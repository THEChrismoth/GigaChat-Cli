"""Команды чата для предложения и отката изменения файла."""

import re
from string import punctuation
from typing import TYPE_CHECKING

from gigachat_cli.widgets.message_input import MessageInput

from gigachat_cli.widgets.file_review import FileReview
from gigachat_cli.core.command import split_command_arguments
from gigachat_cli.core.file_edit import FileEdit, FileEditError

if TYPE_CHECKING:
    from gigachat_cli.screens.chat import ChatScreen


def _escape_markdown(text: str) -> str:
    """Показать пути и сообщения об ошибках как текст."""
    return re.sub(f"[{re.escape(punctuation)}]", lambda char: "\\" + char[0], text)


class FileEditHandler:
    """Показать предложения модели и запросить подтверждение записи."""

    async def handle(self, user_text: str, input_field: MessageInput, screen: "ChatScreen") -> bool:
        """Подготовить правку или показать обратное изменение."""
        command = user_text.split(maxsplit=1)[0]
        if command not in {"/edit", "/undo"}:
            return False

        input_field.text = ""
        undo = command == "/undo"
        try:
            if undo:
                if user_text != "/undo":
                    raise FileEditError("Использование: /undo")
                edit = screen.session.undo_edit()
            else:
                arguments = split_command_arguments(user_text)
                if len(arguments) < 3 or not arguments[1].value:
                    raise FileEditError('Использование: /edit "путь к файлу" задание')
                snapshot = screen.session.snapshot(arguments[1].value)
                name = _escape_markdown(snapshot.relative_path.as_posix())
                screen.update_chat_display(f"**Правка файла:** {name}")
                screen.set_operation_status("Подготовка правки")
                edit = await screen.session.propose_edit(snapshot, user_text[arguments[2].start:])

            diff = edit.diff()
            if not diff:
                screen.update_chat_display("Содержимое файла не изменилось.")
                return True
        except (FileEditError, OSError) as error:
            screen.update_chat_display(f"**Ошибка:** {_escape_markdown(str(error))}")
            return True

        path = edit.before.root / edit.before.relative_path
        approved = await screen.review_file(FileReview(path, diff, undo=undo))
        self._finish_review(screen, edit, undo, approved)
        return True

    def _finish_review(self, screen: "ChatScreen", edit: FileEdit, undo: bool, approved: bool) -> None:
        """Применить подтверждённый вариант и сообщить результат в чате."""
        name = _escape_markdown(edit.before.relative_path.as_posix())
        if not approved:
            result = f"Изменение файла **{name}** отклонено."
        else:
            try:
                screen.session.apply_edit(edit)
            except (FileEditError, OSError) as error:
                result = f"**Ошибка:** {_escape_markdown(str(error))}"
            else:
                verb = "отменено" if undo else "применено. /undo — откатить"
                result = f"Изменение файла **{name}** {verb}."
        screen.update_chat_display(result)
