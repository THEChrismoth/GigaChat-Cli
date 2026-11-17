import asyncio

import pytest
from textual.app import App
from textual.widgets import Input, Markdown

from conftest import python_command
from gigachat_cli.main import Main
from gigachat_cli.screens import chat
from gigachat_cli.screens.chat import ChatScreen
from gigachat_cli.screens.start import MenuApp
from gigachat_cli.utils.config import DEFAULT_MODEL, Config
from gigachat_cli.utils.core import StreamChunk


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
        monkeypatch.setattr(chat, "get_answer_stream", fake)
        return fake
    return install


@pytest.fixture(autouse=True)
def default_model():
    Config().set_model(DEFAULT_MODEL)
    yield
    Config().set_model(DEFAULT_MODEL)


def chat_text(screen) -> str:
    return screen.query_one("#chat_display", Markdown).source


async def send(pilot, text: str) -> None:
    """Ввод сообщения и ожидание окончания его обработки"""
    screen = pilot.app.screen
    screen.query_one("#message_input", Input).value = text
    await pilot.press("enter")
    task = screen.current_stream_task
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
        assert fake.calls == [("Здравствуй", str(screen.command_utils.get_current_directory()))]
        assert screen.query_one("#message_input", Input).value == ""
        assert not screen.is_processing_stream
        assert screen.current_typing_indicator is None


async def test_api_error_is_displayed(answers):
    answers([StreamChunk("", is_final=True, error="GIGACHAT_API_KEY не установен")])

    async with ChatApp().run_test() as pilot:
        await send(pilot, "Вопрос")

        assert "**Ошибка:** GIGACHAT_API_KEY не установен" in chat_text(pilot.app.screen)


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
        assert screen.query_one(".banner").has_class("hidden")
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
        screen.query_one("#message_input", Input).value = "Долгий вопрос"
        await pilot.press("enter")
        await pilot.pause(0.2)
        task = screen.current_stream_task
        assert screen.is_processing_stream

        await pilot.press("escape")
        await pilot.pause()

        assert task.done()
        assert not screen.is_processing_stream
        assert "Запрос отменен пользователем" in chat_text(screen)
        assert "думаю..." in chat_text(screen)


async def test_cancellation_keeps_draft_and_allows_next_request(answers):
    answers([StreamChunk("Частичный ответ")], hang=True)
    async with ChatApp().run_test() as pilot:
        screen = pilot.app.screen
        input_field = screen.query_one("#message_input", Input)
        input_field.value = "Первый запрос"
        await pilot.press("enter")
        await pilot.pause()
        input_field.value = "/he"
        await pilot.pause()
        task = screen.current_stream_task
        await pilot.press("ctrl+c")
        await asyncio.wait_for(asyncio.shield(task), timeout=5)
        assert input_field.value == "/he"
        assert "Частичный ответ" in chat_text(screen)
        assert not screen.is_processing_stream
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
        monkeypatch.setattr(screen.command_utils, "execute_system_command", execute)
        input_field = screen.query_one("#message_input", Input)
        input_field.value = "!test"
        await pilot.press("enter")
        await asyncio.wait_for(started.wait(), timeout=5)
        assert input_field.value == ""
        input_field.value = "Черновик"
        task = screen.current_stream_task
        finish.set()
        await asyncio.wait_for(asyncio.shield(task), timeout=5)
        assert input_field.value == "Черновик"


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
        original = chat.get_answer_stream
        chat.get_answer_stream = stream
        try:
            screen.query_one(Input).value = "Первый"
            await pilot.press("enter")
            await pilot.pause()
            task = screen.current_stream_task
            await pilot.press("escape")
            await asyncio.wait_for(cancelling.wait(), timeout=5)
            await pilot.press("escape")
            assert not task.done()
            screen.query_one(Input).value = "Второй"
            await pilot.press("enter")
            assert calls == ["Первый"]
            assert screen.is_processing_stream
            release.set()
            await asyncio.wait_for(asyncio.shield(task), timeout=5)
            assert not screen.is_processing_stream
        finally:
            release.set()
            chat.get_answer_stream = original


async def test_second_enter_ignored_while_processing(answers):
    fake = answers([StreamChunk("ответ")], hang=True)

    async with ChatApp().run_test() as pilot:
        screen = pilot.app.screen
        input_field = screen.query_one("#message_input", Input)
        input_field.value = "первый"
        await pilot.press("enter")
        await pilot.pause(0.2)
        input_field.value = "второй"
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
        screen.command_utils.current_directory = tmp_path

        await send(pilot, "!cd sub")
        await send(pilot, "вопрос")

        assert fake.calls == [("вопрос", str((tmp_path / "sub").resolve()))]


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
        screen.command_utils.current_directory = long_dir
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


async def test_main_app_starts_with_menu():
    async with Main().run_test() as pilot:
        assert isinstance(pilot.app.screen, MenuApp)

        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ChatScreen)
