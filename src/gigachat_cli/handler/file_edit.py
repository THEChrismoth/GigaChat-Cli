"""Команды чата для предложения и отката изменения файла."""

import os
from importlib.util import find_spec
import re
from pathlib import PureWindowsPath
from string import punctuation
from typing import TYPE_CHECKING

from gigachat_cli.widgets.message_input import MessageInput

from gigachat_cli.widgets.file_review import FileReview
from gigachat_cli.core.command import CommandArgument, split_command_arguments
from gigachat_cli.core.file_edit import FileEdit, FileEditError
from gigachat_cli.core.intent import is_read_only_request

if TYPE_CHECKING:
    from gigachat_cli.screens.chat import ChatScreen


_EDIT_REQUEST = re.compile(
    r"^(?:(?:а|пожалуйста|давай(?:те)?|мож(?:ешь|ете|но)|прошу|"
    r"(?:мне\s+)?(?:нужно|надо)|please|(?:can|could) you)[,:\s]+)*"
    r"(?:созда(?:й(?:те)?|ть|дим)|(?P<make>(?:с\s*)?дела(?:й(?:те)?|ть|ем)|make)|исправ(?:ь(?:те)?|ить)|"
    r"добав(?:ь(?:те)?|ить)|запиш(?:и(?:те)?|ать)|отредактируй(?:те)?|отредактировать|"
    r"измени(?:те|ть)?|обнови(?:те|ть)?|перепиш(?:и(?:те)?|ать)|замени(?:те|ть)?|"
    r"напиш(?:и(?:те)?|ать)|create|edit|update|fix|add|write|replace)\b",
    re.IGNORECASE,
)
_READ_ACTION = re.compile(r"\b(?:обзор|разбор|анализ|аудит|отч[её]т|summary|review)\b", re.IGNORECASE)
_FILE_OBJECT = re.compile(r"(?:(?:мне|новый|новые|a|the|new)\s+)*(?:файл(?:ы|ов)?|files?)\b", re.IGNORECASE)
_FILE_WORD = re.compile(r"\b(?:файл(?:а|е|ом|ы|ов|у)?|files?)\b", re.IGNORECASE)


def _escape_markdown(text: str) -> str:
    """Показать пути и сообщения об ошибках как текст."""
    return re.sub(f"[{re.escape(punctuation)}]", lambda char: "\\" + char[0], text)


def _has_file_suffix(value: str) -> bool:
    """Узнать кандидата с расширением, исключая ссылки."""
    return "://" not in value and bool(PureWindowsPath(value).suffix.strip("."))


def _path_candidates(arguments: list[CommandArgument]) -> set[str]:
    """Собрать упомянутые имена файлов, отбросив пунктуацию фразы."""
    candidates = set()
    for argument in arguments:
        value = argument.value if argument.quote else argument.value.strip("«»()\x60,;!?").rstrip(".")
        if _has_file_suffix(value):
            candidates.add(value)
    return candidates


def _natural_arguments(text: str) -> list[CommandArgument]:
    """Разобрать пути в кавычках, включая Markdown и русские кавычки."""
    quoted = re.sub(r"\x60([^\x60\r\n]+)\x60|«([^»\r\n]+)»", r'"\1\2"', text)
    quoted = re.sub(r'(?<=")[,;.!?]+(?=\s|$)', "", quoted)
    return split_command_arguments(quoted)


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

    candidates = _path_candidates(arguments[2:])
    if len(candidates) != 1:
        raise FileEditError(hint)
    return candidates.pop(), text[first.start:]


class FileEditHandler:
    """Показать предложения модели и запросить подтверждение записи."""

    def __init__(self) -> None:
        """Начать без задания, ожидающего уточнения пути."""
        self._pending_instruction: str | None = None

    def reset(self) -> None:
        """Сбросить незавершённое уточнение при смене диалога."""
        self._pending_instruction = None

    def _natural_request(self, text: str) -> tuple[set[str], str] | None:
        """Распознать прямую просьбу о правке или ответ с одним путём."""
        pending, self._pending_instruction = self._pending_instruction, None
        text = text.strip()
        if text.startswith(("/", "!")) or is_read_only_request(text):
            return None
        if pending:
            arguments = _natural_arguments(text)
            if len(arguments) == 1:
                path = arguments[0].value
                if path and (arguments[0].quote or _has_file_suffix(path) or "/" in path or "\\" in path):
                    return {path}, pending
        action = _EDIT_REQUEST.match(text)
        if not action:
            return None
        tail = text[action.end():].lstrip(' ,:')
        if _READ_ACTION.match(tail):
            return None
        if action.group("make") and not _FILE_OBJECT.match(tail):
            arguments = _natural_arguments(tail)
            if not arguments or not _path_candidates(arguments[:1]):
                return None
        paths = _path_candidates(_natural_arguments(text))
        if paths or _FILE_WORD.search(text):
            return paths, text
        return None

    async def handle(self, user_text: str, input_field: MessageInput, screen: "ChatScreen") -> bool:
        """Подготовить правку или показать обратное изменение."""
        command = user_text.split(maxsplit=1)[0]
        request = self._natural_request(user_text)
        if command not in {"/edit", "/undo", "/fix"} and request is None:
            return False

        input_field.text = ""
        undo = command == "/undo"
        check = command == "/fix"
        heading = ""
        try:
            if undo:
                if user_text != "/undo":
                    raise FileEditError("Использование: /undo")
                edit = screen.session.undo_edit()
            else:
                if check and find_spec("pytest") is None:
                    raise FileEditError("Для /fix установите pytest в окружение приложения.")
                if request is None:
                    path, instruction = _parse_edit_request(user_text)
                else:
                    paths, instruction = request
                    if len(paths) != 1:
                        self._pending_instruction = instruction
                        screen.update_chat_display(
                            "Какой файл нужно изменить? Ответьте одним путём, например `test.txt`. "
                            "Путь с пробелами или без расширения заключите в кавычки."
                        )
                        return True
                    path = next(iter(paths))
                snapshot = screen.session.snapshot(path)
                name = _escape_markdown(snapshot.relative_path.as_posix())
                heading = f"**Вы:** {_escape_markdown(instruction)}\n\n"
                await self._edit_file(screen, path, name, instruction, heading, check=check, explicit=request is None)
                return True

            diff = edit.diff()
            if not diff:
                screen.update_chat_display("Содержимое файла не изменилось.")
                return True
        except (FileEditError, OSError) as error:
            message = f"**Ошибка:** {_escape_markdown(str(error))}"
            previous = screen.current_exchange
            screen.update_chat_display(f"{previous}\n\n{message}" if previous else message)
            return True

        path = edit.before.root / edit.before.relative_path
        if undo:
            screen.update_chat_display("**Предлагаемый откат**")
        approved = await screen.review_file(FileReview(path, diff, undo=undo))
        self._finish_review(screen, edit, undo, approved, heading)
        return True

    async def _edit_file(
        self, screen: "ChatScreen", path: str, name: str, instruction: str, heading: str, *, check: bool, explicit: bool
    ) -> None:
        """Предложить правку и при необходимости повторить её после сбоя pytest."""
        attempt_instruction = instruction
        for attempt in range(2 if check else 1):
            snapshot = screen.session.snapshot(path)
            target = snapshot.root / snapshot.relative_path
            screen.update_chat_display(f"{heading}**Правка файла:** {name}")
            screen.set_operation_status("Подготовка правки")
            edit = await screen.session.propose_edit(snapshot, attempt_instruction)
            diff = edit.diff()
            if not diff and not check:
                screen.update_chat_display(f"{heading}Содержимое файла не изменилось.")
                return

            automatic = (
                screen.yolo and explicit and edit.after is not None
                and target.is_relative_to(screen.session.project_root)
                and screen.session.directory.resolve().is_relative_to(screen.session.project_root)
            )
            if diff and not automatic:
                if check:
                    screen.update_chat_display(f"{heading}**Правка файла:** {name}\n\nПосле записи: `pytest -q`.")
                if not await screen.review_file(FileReview(target, diff, undo=False)):
                    screen.update_chat_display(f"{heading}Изменение файла **{name}** отклонено.")
                    return
            if diff:
                screen.session.apply_edit(edit)
            result = (f"Изменение файла **{name}** применено. /undo — откатить."
                      if diff else "Содержимое файла не изменилось.")
            screen.update_chat_display(heading + result)
            if not check:
                return

            screen.set_operation_status("Проверка pytest")
            success, output, code = await screen.session.run_check()
            key = os.getenv("GIGACHAT_API_KEY")
            if key:
                output = output.replace(key, "[скрыто]")
            block = _escape_markdown(output)
            heading += f"{result}\n\n**pytest:** код {code}.\n\n{block}\n\n"
            screen.update_chat_display(heading.rstrip())
            if success or code != 1 or attempt == 1:
                return
            attempt_instruction = (
                f"{instruction}\n\nПредыдущая правка не прошла pytest. "
                f"Исправь причину, если она относится к этому файлу. Pytest завершился с кодом 1."
            )

    def _finish_review(
        self, screen: "ChatScreen", edit: FileEdit, undo: bool, approved: bool, heading: str
    ) -> None:
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
        screen.update_chat_display(heading + result)
