import asyncio
from contextlib import aclosing
from types import SimpleNamespace

from gigachat_cli.core import session


async def test_pytest_does_not_inherit_gigachat_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIGACHAT_API_KEY", "synthetic-key")
    (tmp_path / "test_env.py").write_text(
        "import os\n\ndef test_env():\n    assert 'GIGACHAT_API_KEY' not in os.environ\n",
        encoding="utf-8",
    )

    success, output, code = await session.ChatSession().run_check()

    assert success and code == 0, output


async def test_session_uses_changed_directory_for_answers_and_edits(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sub").mkdir()
    target = tmp_path / "sub" / "notes.txt"
    target.write_bytes(b"original")
    calls = []

    async def answer(prompt, project_path):
        calls.append((prompt, project_path))
        yield session.StreamChunk("ответ", is_final=True)

    monkeypatch.setattr(session, "get_answer_stream", answer)
    work = session.ChatSession()
    success, _, _ = await work.execute_command("cd sub")
    assert success
    assert [chunk.content async for chunk in work.answer("вопрос")] == ["ответ"]
    assert calls == [("вопрос", str(target.parent.resolve()))]

    work.apply_edit(work.snapshot("notes.txt").propose("updated"))
    assert target.read_bytes() == b"updated"
    await work.execute_command("cd ..")
    work.apply_edit(work.undo_edit())
    assert target.read_bytes() == b"original"


async def test_session_stays_busy_until_cancelled_operation_finishes():
    started = asyncio.Event()
    cleaning = asyncio.Event()
    release = asyncio.Event()

    async def operation():
        try:
            started.set()
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleaning.set()
            await release.wait()

    work = session.ChatSession()
    assert work.start(operation)
    await asyncio.wait_for(started.wait(), timeout=5)
    work.cancel()
    await asyncio.wait_for(cleaning.wait(), timeout=5)
    work.cancel()
    assert work.busy
    assert not work.start(operation)
    release.set()
    await asyncio.wait_for(work.task, timeout=5)
    assert not work.busy


async def test_history_is_committed_when_frontend_receives_final_chunk(manager, monkeypatch):
    async def astream(messages):
        yield SimpleNamespace(content="Ответ")

    fake = SimpleNamespace(astream=astream)
    monkeypatch.setattr(manager, "_get_giga_chat_instance", lambda: fake)
    monkeypatch.setattr("gigachat_cli.core.model.chat_manager", manager)

    async with aclosing(session.ChatSession().answer("Вопрос")) as stream:
        assert (await anext(stream)).content == "Ответ"
        assert (await anext(stream)).is_final
        assert [message.content for message in manager.conversation_history] == ["Вопрос", "Ответ"]
