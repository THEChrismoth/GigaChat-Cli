"""Команды чата для предложения и отката изменения файла."""

import re
from pathlib import PureWindowsPath
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


def _has_file_suffix(value: str) -> bool:
    """Узнать кандидата с расширением, исключая ссылки."""
    return "://" not in value and bool(PureWindowsPath(value).suffix.strip("."))


def _parse_edit_request(text: str) -> tuple[str, str]:
    """Выбрать явный путь или единственное имя файла из задания."""
    arguments = split_command_arguments(text)
    hint = 'Укажите путь перед заданием: /edit "test.txt" Напиши «привет мир».'
    if len(arguments) < 3 or not arguments[1].value:
        raise FileEditError(hint)

    first = arguments[1]
    path = first.value
    if first.quote or _has_file_suffix(path) or ("://" not in path and ("/" in path or "\\" in path)):
        return path, text[arguments[2].start:]

    candidates = set()
    for argument in arguments[2:]:
        # В естественной фразе имя может стоять в скобках или перед запятой.
        value = argument.value if argument.quote else argument.value.strip("«»()\x60,;!?").rstrip(".")
        if _has_file_suffix(value):
            candidates.add(value)
    if len(candidates) != 1:
        raise FileEditError(hint)
    return candidates.pop(), text[first.start:]


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
                path, instruction = _parse_edit_request(user_text)
                snapshot = screen.session.snapshot(path)
                name = _escape_markdown(snapshot.relative_path.as_posix())
                screen.update_chat_display(f"**Правка файла:** {name}")
                screen.set_operation_status("Подготовка правки")
                edit = await screen.session.propose_edit(snapshot, instruction)

            diff = edit.diff()
            if not diff:
                screen.update_chat_display("Содержимое файла не изменилось.")
                return True
        except (FileEditError, OSError) as error:
            screen.update_chat_display(f"**Ошибка:** {_escape_markdown(str(error))}")
            return True

        path = edit.before.root / edit.before.relative_path
        screen.update_chat_display("**Предлагаемый откат**" if undo else "**Предлагаемая правка**")
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
