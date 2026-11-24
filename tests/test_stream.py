import asyncio
from contextlib import aclosing
from types import SimpleNamespace

import pytest


async def test_cancelling_answer_interrupts_active_read(manager, monkeypatch):
    read_started = asyncio.Event()
    closed = asyncio.Event()

    async def astream(messages):
        try:
            yield SimpleNamespace(content="Частичный ответ")
            read_started.set()
            await asyncio.Future()
        finally:
            closed.set()

    monkeypatch.setattr(manager, "_get_giga_chat_instance", lambda: SimpleNamespace(astream=astream))

    async with aclosing(manager.get_answer_stream("Вопрос")) as stream:
        assert (await anext(stream)).content == "Частичный ответ"
        task = asyncio.create_task(anext(stream))
        try:
            await asyncio.wait_for(read_started.wait(), timeout=5)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert closed.is_set()

    assert manager.conversation_history == []


@pytest.mark.parametrize("prompt", [
    "Вопрос",
    "Объясни main.py",
    "Объясни код ```x = 1```",
    "Рефакторинг ```x = 1```",
    "Покажи структуру проекта",
])
async def test_closing_answer_closes_provider_between_chunks(manager, monkeypatch, project, prompt):
    closed = asyncio.Event()

    async def astream(messages):
        try:
            yield SimpleNamespace(content="Начало ответа")
        finally:
            closed.set()

    monkeypatch.setattr(manager, "_get_giga_chat_instance", lambda: SimpleNamespace(astream=astream))

    async with aclosing(manager.get_answer_stream(prompt, project_path=str(project))) as stream:
        assert (await anext(stream)).content == "Начало ответа"

    assert closed.is_set()
    assert manager.conversation_history == []
