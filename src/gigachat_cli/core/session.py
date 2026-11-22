"""Операции рабочей сессии, общие для терминального интерфейса и CLI."""

import asyncio
import os
import sys
from contextlib import aclosing
from pathlib import Path
from typing import AsyncGenerator, Callable, Coroutine

from langchain_core.messages import AIMessage, HumanMessage

from gigachat_cli.core.command import CommandUtils
from gigachat_cli.core.model import StreamChunk, chat_manager, get_answer_stream
from gigachat_cli.core.file import FileUtils
from gigachat_cli.core.file_edit import FileEdit, FileEditError, FileSnapshot, read_snapshot


class ChatSession:
    """Связать запросы и файловые операции с текущей рабочей директорией."""

    def __init__(self) -> None:
        """Начать сессию без активной операции и сохранённой правки."""
        self._commands = CommandUtils()
        self.project_root = self.directory.resolve()
        self.completion = FileUtils(self._commands)
        self._undo: FileEdit | None = None
        self.task: asyncio.Task[None] | None = None

    @property
    def directory(self) -> Path:
        """Вернуть текущую рабочую директорию."""
        return self._commands.get_current_directory()

    @property
    def busy(self) -> bool:
        """Проверить, завершилась ли активная операция вместе с её очисткой."""
        return self.task is not None and not self.task.done()

    def start(self, operation: Callable[[], Coroutine[None, None, None]]) -> bool:
        """Запустить операцию, если сессия свободна."""
        if self.busy:
            return False
        self.task = asyncio.create_task(operation())
        return True

    def cancel(self) -> None:
        """Запросить отмену операции, не прерывая уже начатую очистку."""
        task = self.task
        if task is not None and not task.done() and not task.cancelling():
            task.cancel()

    def get_model(self) -> str:
        """Вернуть выбранную модель."""
        return chat_manager.get_current_model()

    def set_model(self, model: str) -> None:
        """Сохранить выбранную модель."""
        chat_manager.config.set_model(model)

    def export_model_history(self) -> tuple[tuple[str, str], ...]:
        """Сохранить только текстовые сообщения пользователя и модели."""
        return tuple(
            ("user" if isinstance(message, HumanMessage) else "assistant", message.content)
            for message in chat_manager.conversation_history
            if isinstance(message, (HumanMessage, AIMessage)) and isinstance(message.content, str)
        )[-20:]

    def restore_model_history(self, history: tuple[tuple[str, str], ...]) -> None:
        """Заменить контекст модели и сбросить недоступный в новом диалоге откат."""
        message_types = {"user": HumanMessage, "assistant": AIMessage}
        chat_manager.conversation_history = [message_types[role](content=text) for role, text in history]
        self._undo = None

    async def answer(self, prompt: str) -> AsyncGenerator[StreamChunk, None]:
        """Ответить с учётом истории модели и рабочей директории сессии."""
        async with aclosing(get_answer_stream(prompt, project_path=str(self.directory))) as stream:
            async for chunk in stream:
                yield chunk

    async def execute_command(self, command: str) -> tuple[bool, str, int]:
        """Выполнить введённую пользователем команду в рабочей директории."""
        return await self._commands.execute_system_command(command)

    async def run_check(self) -> tuple[bool, str, int]:
        """Запустить выбранную командой /fix проверку без оболочки."""
        env = {name: value for name, value in os.environ.items() if not name.upper().startswith("GIGACHAT_")}
        return await self._commands.execute_system_command((sys.executable, "-P", "-m", "pytest", "-q"), env=env)

    def snapshot(self, path: str) -> FileSnapshot:
        """Прочитать выбранный пользователем файл относительно рабочей директории."""
        return read_snapshot(self.directory, path)

    async def propose_edit(self, snapshot: FileSnapshot, instruction: str) -> FileEdit:
        """Подготовить предлагаемое содержимое из снимка и задания."""
        return await chat_manager.propose_file_edit(snapshot, instruction)

    def undo_edit(self) -> FileEdit:
        """Вернуть предложение для отката последней применённой правки."""
        if self._undo is None:
            raise FileEditError("В этом чате нет правки для отката.")
        return self._undo

    def apply_edit(self, edit: FileEdit) -> None:
        """Применить подтверждённую правку и обновить доступный откат."""
        inverse = edit.apply()
        self._undo = None if edit is self._undo else inverse
