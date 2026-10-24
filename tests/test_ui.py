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


async def test_main_app_starts_with_menu():
    async with Main().run_test() as pilot:
        assert isinstance(pilot.app.screen, MenuApp)

        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ChatScreen)
