import asyncio

import pytest
from textual.app import App
from textual import events
from textual.widgets import Markdown

from gigachat_cli.widgets.message_input import MessageInput

from conftest import python_command
from gigachat_cli.main import Main
from gigachat_cli.core import session
from gigachat_cli.screens.chat import ChatScreen
from gigachat_cli.screens.file_review import FileReviewScreen
from gigachat_cli.core.config import DEFAULT_MODEL, Config
from gigachat_cli.core.model import StreamChunk
from gigachat_cli.core.command import split_command_arguments
from gigachat_cli.widgets.file_list import FileList
from gigachat_cli.core.model import chat_manager


class ChatApp(App):
    """Приложение, сразу открывающее экран чата"""

    def on_mount(self) -> None:
        self.push_screen(ChatScreen())


class FakeAnswers:
    """Заглушка get_answer_stream: отдает заданные чанки и запоминает вызовы"""

    def __init__(self, chunks, hang=False):
        self.chunks = chunks
        self.hang = hang
        self.calls = []

    async def __call__(self, prompt, clear_history=False, project_path=None):
        self.calls.append((prompt, project_path))
        for chunk in self.chunks:
            yield chunk
        if self.hang:
            await asyncio.sleep(60)


@pytest.fixture
def answers(monkeypatch):
    def install(chunks, hang=False):
        fake = FakeAnswers(chunks, hang)
        monkeypatch.setattr(session, "get_answer_stream", fake)
        return fake
    return install


@pytest.fixture(autouse=True)
def default_model():
    Config().set_model(DEFAULT_MODEL)
    yield
    Config().set_model(DEFAULT_MODEL)


def chat_text(screen) -> str:
    return "\n\n".join(block.source for block in screen.query(".chat_exchange").results(Markdown))


async def send(pilot, text: str) -> None:
    """Ввод сообщения и ожидание окончания его обработки"""
    screen = pilot.app.screen
    screen.query_one("#message_input", MessageInput).text = text
    await pilot.press("enter")
    task = screen.session.task
    if task is not None:
        await asyncio.wait_for(asyncio.shield(task), timeout=30)
    await pilot.pause()


async def test_streamed_answer_is_displayed(answers):
    fake = answers([StreamChunk("При"), StreamChunk("вет!"), StreamChunk("", is_final=True)])

    async with ChatApp().run_test() as pilot:
        await send(pilot, "Здравствуй")
        screen = pilot.app.screen

        assert "**Вы:** Здравствуй" in chat_text(screen)
        assert "Привет!" in chat_text(screen)
        assert fake.calls == [("Здравствуй", str(screen.session.directory))]
        assert screen.query_one("#message_input", MessageInput).text == ""
        assert not screen.session.busy
        assert "F3/F4 история" in str(screen.query_one("#composer_hint").render())


async def test_api_error_is_displayed(answers):
    answers([StreamChunk("", is_final=True, error="GIGACHAT_API_KEY не установен")])

    async with ChatApp().run_test() as pilot:
        await send(pilot, "Вопрос")

        assert "**Ошибка:** GIGACHAT_API_KEY не установен" in chat_text(pilot.app.screen)


async def test_status_follows_response_and_resets_after_cancellation(monkeypatch):
    first_chunk = asyncio.Event()

    async def answer(prompt, project_path):
        await first_chunk.wait()
        yield StreamChunk("Часть ответа")
        await asyncio.Event().wait()

    monkeypatch.setattr(session, "get_answer_stream", answer)
    async with ChatApp().run_test() as pilot:
        screen = pilot.app.screen
        hint = screen.query_one("#composer_hint")
        screen.query_one(MessageInput).text = "Долгий запрос"
        await pilot.press("enter")
        assert "Ожидание ответа" in str(hint.render())
        first_chunk.set()
        await pilot.pause()
        assert "Генерация ответа" in str(hint.render())
        await pilot.press("escape")
        await pilot.pause()
        assert "F3/F4 история" in str(hint.render())
        assert "Часть ответа" in chat_text(screen)


@pytest.mark.parametrize("size", [(80, 24), (120, 40), (60, 24)])
async def test_stream_respects_scroll_position_and_focus(answers, size):
    answers([
        StreamChunk("\n\n".join(f"Строка {i}" for i in range(start, start + 10)) + "\n\n")
        for start in range(0, 80, 10)
    ] + [StreamChunk("", is_final=True)])
    async with ChatApp().run_test(size=size) as pilot:
        await send(pilot, "Длинный ответ")
        screen = pilot.app.screen
        container = screen.query_one("#chat_container")
        assert screen.query_one("#chat_welcome").has_class("hidden")
        assert container.size.height >= 15
        assert container.is_vertical_scroll_end
        container.scroll_home(animate=False)
        container.focus()
        await pilot.pause()
        assert pilot.app.focused is container
        screen.update_chat_display(screen.current_exchange + "\n\nПродолжение")
        await pilot.pause()
        assert container.scroll_y == 0
        container.scroll_end(animate=False)
        await pilot.pause()
        screen.update_chat_display(screen.current_exchange + "\n\nЕщё продолжение")
        await pilot.pause()
        assert container.is_vertical_scroll_end


async def test_history_survives_messages_help_and_model_selection(answers):
    answers([StreamChunk("Ответ", is_final=True)])
    async with ChatApp().run_test() as pilot:
        for index in range(10):
            await send(pilot, f"Вопрос номер {index}")
        await send(pilot, "/help")
        await send(pilot, "/model")
        await pilot.press("escape")
        await pilot.pause()
        text = chat_text(pilot.app.screen)
        for index in range(10):
            assert text.count(f"**Вы:** Вопрос номер {index}") == 1
        assert text.count("**GigaChat:**") == 10
        assert "Доступные команды" in text
        assert "Выбор отменен" in text


async def test_fast_stream_batches_fragments_without_rebuilding_history(answers, monkeypatch):
    answers([StreamChunk("\n\n".join(f"Строка {i}" for i in range(30)), is_final=True)])
    async with ChatApp().run_test(size=(80, 24)) as pilot:
        screen = pilot.app.screen
        await send(pilot, "Первый вопрос")
        history = screen.query_one("#chat_container")
        first = screen.query_one(".chat_exchange", Markdown)
        finished_blocks = tuple(first.children)
        assert history.is_vertical_scroll_end

        updated = []
        update = Markdown.update

        def track(widget, source):
            updated.append(widget)
            return update(widget, source)

        monkeypatch.setattr(Markdown, "update", track)
        chunks = [StreamChunk(str(i) + " ") for i in range(180)]
        answers(chunks + [StreamChunk("", is_final=True)])
        await send(pilot, "Второй вопрос")

        assert first not in updated
        assert tuple(first.children) == finished_blocks
        assert " ".join(str(i) for i in range(180)) in chat_text(screen)
        assert 0 < len(updated) < len(chunks) // 2
        assert history.is_vertical_scroll_end


async def test_partial_answer_kept_on_error(answers):
    answers([StreamChunk("Начало ответа"), StreamChunk("", is_final=True, error="обрыв")])

    async with ChatApp().run_test() as pilot:
        await send(pilot, "Вопрос")
        text = chat_text(pilot.app.screen)

        assert "Начало ответа" in text
        assert "**Ошибка:** обрыв" in text


async def test_escape_cancels_request(answers):
    answers([StreamChunk("думаю...")], hang=True)

    async with ChatApp().run_test() as pilot:
        screen = pilot.app.screen
        screen.query_one("#message_input", MessageInput).text = "Долгий вопрос"
        await pilot.press("enter")
        await pilot.pause(0.2)
        task = screen.session.task
        assert screen.session.busy

        await pilot.press("escape")
        await pilot.pause()

        assert task.done()
        assert not screen.session.busy
        assert "Запрос отменен пользователем" in chat_text(screen)
        assert "думаю..." in chat_text(screen)


async def test_cancellation_keeps_draft_and_allows_next_request(answers):
    answers([StreamChunk("Частичный ответ")], hang=True)
    async with ChatApp().run_test() as pilot:
        screen = pilot.app.screen
        input_field = screen.query_one("#message_input", MessageInput)
        input_field.text = "Первый запрос"
        await pilot.press("enter")
        await pilot.pause()
        input_field.text = "/he"
        await pilot.pause()
        task = screen.session.task
        await pilot.press("ctrl+c")
        await asyncio.wait_for(asyncio.shield(task), timeout=5)
        assert input_field.text == "/he"
        assert "Частичный ответ" in chat_text(screen)
        assert not screen.session.busy
        answers([StreamChunk("Следующий ответ", is_final=True)])
        await send(pilot, "Следующий запрос")
        assert "Частичный ответ" in chat_text(screen)
        assert "Следующий ответ" in chat_text(screen)


async def test_terminal_command_keeps_draft(answers, monkeypatch):
    started = asyncio.Event()
    finish = asyncio.Event()

    async def execute(command):
        started.set()
        await finish.wait()
        return True, "готово", 0

    async with ChatApp().run_test() as pilot:
        screen = pilot.app.screen
        monkeypatch.setattr(screen.session, "execute_command", execute)
        input_field = screen.query_one("#message_input", MessageInput)
        input_field.text = "!test"
        await pilot.press("enter")
        await asyncio.wait_for(started.wait(), timeout=5)
        assert input_field.text == ""
        input_field.text = "Черновик"
        task = screen.session.task
        finish.set()
        await asyncio.wait_for(asyncio.shield(task), timeout=5)
        assert input_field.text == "Черновик"


async def test_cancel_waits_for_cleanup_before_next_request(answers):
    cancelling = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def stream(prompt, **kwargs):
        calls.append(prompt)
        yield StreamChunk("Начало")
        try:
            await asyncio.Event().wait()
        finally:
            cancelling.set()
            await release.wait()

    async with ChatApp().run_test() as pilot:
        screen = pilot.app.screen
        original = session.get_answer_stream
        session.get_answer_stream = stream
        try:
            screen.query_one(MessageInput).text = "Первый"
            await pilot.press("enter")
            await pilot.pause()
            task = screen.session.task
            await pilot.press("escape")
            await asyncio.wait_for(cancelling.wait(), timeout=5)
            await pilot.press("escape")
            assert not task.done()
            screen.query_one(MessageInput).text = "Второй"
            await pilot.press("enter")
            assert calls == ["Первый"]
            assert screen.session.busy
            release.set()
            await asyncio.wait_for(asyncio.shield(task), timeout=5)
            assert not screen.session.busy
        finally:
            release.set()
            session.get_answer_stream = original


async def test_second_enter_ignored_while_processing(answers):
    fake = answers([StreamChunk("ответ")], hang=True)

    async with ChatApp().run_test() as pilot:
        screen = pilot.app.screen
        input_field = screen.query_one("#message_input", MessageInput)
        input_field.text = "первый"
        await pilot.press("enter")
        await pilot.pause(0.2)
        input_field.text = "второй"
        await pilot.press("enter")
        await pilot.pause(0.2)

        assert [call[0] for call in fake.calls] == ["первый"]
        await pilot.press("escape")


async def test_terminal_command(answers):
    fake = answers([])

    async with ChatApp().run_test() as pilot:
        await send(pilot, "!" + python_command("print(424242)"))
        text = chat_text(pilot.app.screen)

        assert "**Система:**" in text
        assert "424242" in text
        assert "**Выполнено**" in text
        assert fake.calls == []


async def test_terminal_cd_updates_project_path(answers, tmp_path):
    fake = answers([StreamChunk("ok", is_final=True)])
    (tmp_path / "sub").mkdir()

    async with ChatApp().run_test() as pilot:
        screen = pilot.app.screen
        screen.session._commands.current_directory = tmp_path

        await send(pilot, "!cd sub/")
        await send(pilot, "вопрос")

        assert fake.calls == [("вопрос", str((tmp_path / "sub").resolve()))]


@pytest.mark.parametrize("command", ["!cat ", "!cd "])
async def test_directory_selection_opens_children_until_file(answers, tmp_path, command):
    fake = answers([])
    nested = tmp_path / "My Docs" / "Вложенная папка"
    nested.mkdir(parents=True)
    (nested / "notes.txt").write_text("notes", encoding="utf-8")
    async with ChatApp().run_test() as pilot:
        screen = pilot.app.screen
        screen.session._commands.current_directory = tmp_path
        field = screen.query_one(MessageInput)
        files = screen.query_one(FileList)
        field.text = command
        await pilot.pause()
        for expected in ["My Docs", "Вложенная папка", "notes.txt"]:
            assert not files.has_class("hidden")
            assert files.files == [expected]
            await pilot.press("enter")
            await pilot.pause()
            assert not screen.session.busy
        assert files.has_class("hidden")
        assert split_command_arguments(field.text)[-1].value == "My Docs/Вложенная папка/notes.txt"
        assert fake.calls == []


async def test_cd_selected_directory_can_be_executed_with_escape(answers, tmp_path):
    (tmp_path / "folder").mkdir()
    (tmp_path / "folder" / "child").mkdir()
    async with ChatApp().run_test() as pilot:
        screen = pilot.app.screen
        screen.session._commands.current_directory = tmp_path
        screen.query_one(MessageInput).text = "!cd "
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert not screen.query_one(FileList).has_class("hidden")
        await pilot.press("escape")
        await pilot.press("enter")
        task = screen.session.task
        if task:
            await asyncio.wait_for(asyncio.shield(task), timeout=5)
        assert screen.session.directory == (tmp_path / "folder").resolve()


async def test_empty_directory_selection_closes_completion(answers, tmp_path):
    (tmp_path / "empty").mkdir()
    async with ChatApp().run_test() as pilot:
        screen = pilot.app.screen
        screen.session._commands.current_directory = tmp_path
        field = screen.query_one(MessageInput)
        field.text = "!cd "
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert field.text == "!cd empty/"
        assert screen.query_one(FileList).has_class("hidden")
        assert screen.session.directory == tmp_path
        await pilot.press("enter")
        task = screen.session.task
        if task:
            await asyncio.wait_for(asyncio.shield(task), timeout=5)
        assert screen.session.directory == (tmp_path / "empty").resolve()


@pytest.mark.parametrize("size", [(80, 24), (120, 40), (60, 24)])
async def test_file_edit_review_confirm_and_undo(tmp_path, monkeypatch, size):
    target = tmp_path / "Мои заметки [demo].txt"
    target.write_bytes(b"original\n")

    async def propose(snapshot, instruction):
        assert snapshot.relative_path.name == target.name
        assert instruction == "Обнови текст"
        return snapshot.propose("[bold] replacement\n")

    monkeypatch.setattr(chat_manager, "propose_file_edit", propose)
    async with ChatApp().run_test(size=size) as pilot:
        screen = pilot.app.screen
        screen.session._commands.current_directory = tmp_path
        command = f'/edit "{target.name}" Обнови текст'
        await send(pilot, command)
        review = pilot.app.screen
        assert isinstance(review, FileReviewScreen)
        assert review.path == target
        assert "+[bold] replacement" in review.diff
        assert pilot.app.focused.id == "reject_change"
        assert target.read_bytes() == b"original\n"
        assert "replacement" in pilot.app.export_screenshot()
        await pilot.press("enter")
        assert pilot.app.screen is screen
        assert target.read_bytes() == b"original\n"

        await send(pilot, command)
        await pilot.press("tab", "enter")
        assert pilot.app.screen is screen
        assert target.read_bytes() == b"[bold] replacement\n"
        assert "применено" in chat_text(screen)

        await send(pilot, "/undo")
        assert isinstance(pilot.app.screen, FileReviewScreen)
        await pilot.press("escape")
        assert pilot.app.screen is screen
        assert target.read_bytes() == b"[bold] replacement\n"
        await send(pilot, "/undo")
        await pilot.press("tab", "enter")
        assert target.read_bytes() == b"original\n"
        assert "отменено" in chat_text(screen)


async def test_file_creation_is_rechecked_at_confirmation(tmp_path, monkeypatch):
    target = tmp_path / "new.txt"

    async def propose(snapshot, instruction):
        assert snapshot.data is None
        return snapshot.propose("proposal\n")

    monkeypatch.setattr(chat_manager, "propose_file_edit", propose)
    async with ChatApp().run_test() as pilot:
        screen = pilot.app.screen
        screen.session._commands.current_directory = tmp_path
        await send(pilot, "/edit new.txt Добавь текст")
        assert isinstance(pilot.app.screen, FileReviewScreen)
        assert not target.exists()
        target.write_bytes(b"external")
        await pilot.click("#apply_change")
        assert pilot.app.screen is screen
        assert target.read_bytes() == b"external"
        assert "Файл изменился" in chat_text(screen)


async def test_file_edit_can_be_cancelled_while_waiting(tmp_path, monkeypatch):
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def propose(snapshot, instruction):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(chat_manager, "propose_file_edit", propose)
    async with ChatApp().run_test() as pilot:
        screen = pilot.app.screen
        screen.session._commands.current_directory = tmp_path
        screen.query_one(MessageInput).text = "/edit new.txt Добавь текст"
        await pilot.press("enter")
        await asyncio.wait_for(started.wait(), timeout=5)
        await pilot.press("escape")
        await asyncio.wait_for(stopped.wait(), timeout=5)
        await pilot.pause()
        assert pilot.app.screen is screen
        assert not screen.session.busy
        assert "Запрос отменен" in chat_text(screen)
        assert not (tmp_path / "new.txt").exists()


async def test_help_command(answers):
    async with ChatApp().run_test() as pilot:
        await send(pilot, "/help")

        assert "Доступные команды" in chat_text(pilot.app.screen)


async def test_model_selection(answers):
    async with ChatApp().run_test() as pilot:
        await send(pilot, "/model")
        screen = pilot.app.screen
        assert screen.selector_manager.selector_active

        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()

        assert not screen.selector_manager.selector_active
        assert Config().get_model() == "GigaChat-2-Pro"
        assert "GigaChat 2 Pro" in chat_text(screen)


async def test_model_selection_cancel(answers):
    async with ChatApp().run_test() as pilot:
        await send(pilot, "/model")
        await pilot.press("down")
        await pilot.press("escape")
        await pilot.pause()

        assert Config().get_model() == DEFAULT_MODEL
        assert "Выбор отменен" in chat_text(pilot.app.screen)


async def test_status_bar_shows_directory_on_narrow_screen(answers, tmp_path):
    # Регрессия: длинный путь переносился на вторую строку, и строка состояния (высота 1)
    # показывала только "Директория:" без пути
    long_dir = tmp_path / "project_directory"
    long_dir.mkdir()

    async with ChatApp().run_test(size=(60, 40)) as pilot:
        screen = pilot.app.screen
        screen.session._commands.current_directory = long_dir
        screen._update_directory_display()
        await pilot.pause()

        # Видимое содержимое экрана: начало пути должно попасть в строку состояния
        screenshot = pilot.app.export_screenshot()

        assert "Директория:" in screenshot.replace("&#160;", " ")
        assert tmp_path.parts[1][:3] in screenshot or "~" in screenshot


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("{home}", "~"),
        ("{home}{sep}projects{sep}app", "~{sep}projects{sep}app"),
        ("{other}", "{other}"),
    ],
)
def test_shorten_home(monkeypatch, tmp_path, path, expected):
    import os
    from gigachat_cli.widgets.dir import shorten_home

    home = tmp_path / "home"
    other = str(tmp_path / "elsewhere")
    monkeypatch.setattr("gigachat_cli.widgets.dir.Path.home", lambda: home)
    values = {"home": str(home), "sep": os.sep, "other": other}

    assert shorten_home(path.format(**values)) == expected.format(**values)


async def test_multiline_input_and_history_restore_a_draft(answers):
    fake = answers([StreamChunk("Ответ", is_final=True)])
    async with ChatApp().run_test(size=(80, 24)) as pilot:
        screen = pilot.app.screen
        field = screen.query_one(MessageInput)
        field.text = "  первый отступ"
        field.move_cursor(field.document.end)
        await pilot.press("f2")
        assert field.text == "  первый отступ\n"
        assert field.cursor_location == (1, 0)
        pilot.app.post_message(events.Paste("    строка кода\n  строка лога"))
        await pilot.pause()
        request = "  первый отступ\n    строка кода\n  строка лога"
        assert field.text == request
        assert field.size.height == 3
        assert fake.calls == []
        await pilot.press("enter")
        await pilot.pause()
        assert fake.calls[0][0] == request
        assert request in chat_text(screen)
        assert field.text == ""

        field.text = "Черновик\n  с отступом"
        await pilot.press("f3")
        assert field.text == request
        await pilot.press("f4")
        assert field.text == "Черновик\n  с отступом"


async def test_multiline_terminal_command_is_not_executed(answers, monkeypatch):
    fake = answers([])

    async def execute(command):
        pytest.fail(f"Выполнена многострочная команда: {command!r}")

    async with ChatApp().run_test() as pilot:
        screen = pilot.app.screen
        monkeypatch.setattr(screen.session, "execute_command", execute)
        field = screen.query_one(MessageInput)
        command = "!cd sub\nother"
        field.text = command
        await pilot.press("enter")
        await pilot.pause()
        assert field.text == command
        assert fake.calls == []
        assert "терминальная команда должна занимать одну строку" in chat_text(screen)


@pytest.mark.parametrize("no_color", [False, True])
async def test_main_uses_terminal_palette_and_help_stays_in_chat(monkeypatch, no_color):
    if no_color:
        monkeypatch.setenv("NO_COLOR", "1")
    else:
        monkeypatch.delenv("NO_COLOR", raising=False)
    async with Main().run_test() as pilot:
        chat_screen = pilot.app.screen
        assert isinstance(chat_screen, ChatScreen)
        assert pilot.app.focused.id == "message_input"
        assert pilot.app.ansi_color
        history = chat_screen.query_one("#chat_container").region
        style = chat_screen.get_style_at(history.x + 3, history.bottom - 2)
        assert style.bgcolor is None or style.bgcolor.is_default
        editor = pilot.app.focused.content_region
        style = chat_screen.get_style_at(editor.x + 2, editor.y)
        assert style.bgcolor is None or style.bgcolor.is_default
        await send(pilot, "/help")
        assert pilot.app.screen is chat_screen
        assert "Доступные команды" in chat_text(chat_screen)
        assert not chat_screen.list_utils.get_filtered_commands("/menu")
