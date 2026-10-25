"""Экран чата: ввод сообщений, команды, автодополнение и потоковый вывод ответа."""

import importlib.resources
import asyncio
from typing import Optional

from textual.app import ComposeResult
from textual.widgets import Input, Markdown
from textual.screen import Screen
from textual.containers import VerticalScroll, Horizontal
from textual import events

from gigachat_cli.utils.config import Config
from gigachat_cli.utils.core import get_answer_stream
from gigachat_cli.utils.command import CommandUtils
from gigachat_cli.utils.list import ListUtils
from gigachat_cli.utils.selector import SelectorManager
from gigachat_cli.utils.file import FileUtils

from gigachat_cli.handler.help import HelpHandler
from gigachat_cli.handler.model import ModelHandler
from gigachat_cli.handler.terminal_command import TerminalHandler

from gigachat_cli.widgets.command_list import CommandList
from gigachat_cli.widgets.file_list import FileList
from gigachat_cli.widgets.model import Model
from gigachat_cli.widgets.banner import Banner
from gigachat_cli.widgets.recommend import Recommend
from gigachat_cli.widgets.dir import Dir
from gigachat_cli.widgets.typing import TypingIndicator


class ChatScreen(Screen):
    """Экран чата с GigaChat.

    Сообщение обрабатывается одной задачей (current_stream_task): команды /exit и /menu,
    обработчики команд (/help, /model, !команда) или запрос к GigaChat.
    Пока задача выполняется, повторная отправка игнорируется, а Esc/Ctrl+C отменяет ее.
    """

    CSS = importlib.resources.files("gigachat_cli.styles").joinpath("chat.css").read_text()

    def __init__(self):
        """Создание экрана, утилит и обработчиков команд."""
        super().__init__()
        self.command_utils = CommandUtils()
        self.list_utils = ListUtils()
        self.file_utils = FileUtils(self.command_utils)
        self.cfg = Config()

        self.selector_manager = SelectorManager(self)

        # Обработчики проверяются по порядку, первый подходящий обрабатывает сообщение
        self.handlers =[
            HelpHandler(),
            ModelHandler(self.cfg, self),
            TerminalHandler(self.command_utils)
        ]

        # Состояние обработки текущего сообщения
        self.current_typing_indicator: Optional[TypingIndicator] = None
        self.current_stream_task: Optional[asyncio.Task] = None
        self.current_response_content: str = ""
        self.is_processing_stream: bool = False
        self.last_user_message: str = ""

    def compose(self) -> ComposeResult:
        """Создание виджетов экрана.

        Yields:
            Баннер, советы, область чата, списки автодополнения, поле ввода и строку состояния
        """
        yield Banner(classes="banner")
        yield Recommend(classes="recommend")
        with VerticalScroll(id="chat_container"):
            yield Markdown("", id="chat_display")
        yield CommandList(id="command_list", classes="hidden")
        yield FileList(id="file_list", classes="hidden")
        yield Input(
            placeholder="Введите сообщение... (Нажмите Enter для отправки)",
            id="message_input"
        )
        with Horizontal(classes="status_bar"):
            yield Dir(classes="dir")
            yield Model(classes="model")

    def on_mount(self) -> None:
        """Фокус на поле ввода и заполнение строки состояния."""
        self.current_typing_indicator = None
        self.query_one("#message_input").focus()
        self._update_directory_display()
        self._update_model_display()
        self.query_one("#command_list", CommandList).add_class("hidden")
        self.query_one("#file_list", FileList).add_class("hidden")

    def on_unmount(self) -> None:
        """Отмена обработки сообщения при закрытии экрана."""
        self._cleanup_stream_processing()

    def _cleanup_stream_processing(self):
        """Отмена текущей обработки сообщения и сброс ее состояния."""
        if self.current_stream_task and not self.current_stream_task.done():
            self.current_stream_task.cancel()
        self.is_processing_stream = False
        self.current_response_content = ""
        self._hide_typing_indicator()

    def _hide_typing_indicator(self):
        """Удаление индикатора ожидания ответа, если он показан."""
        if self.current_typing_indicator:
            self.current_typing_indicator.stop_animation()
            self.current_typing_indicator.remove()
            self.current_typing_indicator = None

    def on_click(self, event: events.Click) -> None:
        """Возврат фокуса в поле ввода при клике по экрану.

        Args:
            event: Событие клика
        """
        if not self.selector_manager.selector_active:
            input_field = self.query_one("#message_input")
            if hasattr(event.widget, 'id') and event.widget.id != "message_input":
                input_field.focus()

    def on_focus(self, event: events.Focus) -> None:
        """Возврат фокуса в поле ввода, если его получил другой виджет.

        Args:
            event: Событие получения фокуса
        """
        if not self.selector_manager.selector_active:
            if event.widget.id != "message_input":
                self.query_one("#message_input").focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Показ автодополнения команд (/...) или файлов (!команда ...).

        Args:
            event: Событие изменения текста в поле ввода
        """
        input_field = event.input
        command_list = self.query_one("#command_list", CommandList)
        file_list = self.query_one("#file_list", FileList)

        if self.list_utils.should_show_commands(input_field.value):
            filtered_commands = self.list_utils.get_filtered_commands(input_field.value)
            command_list.update_commands(filtered_commands, input_field.value)
            file_list.add_class("hidden")

        elif self.file_utils.should_show_files(input_field.value):
            files, current_command, current_path = self.file_utils.get_files_for_completion(input_field.value)
            if files:
                file_list.update_files(files, current_command, current_path)
                command_list.add_class("hidden")
            else:
                file_list.add_class("hidden")

        else:
            command_list.add_class("hidden")
            file_list.add_class("hidden")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Обработка Enter: выбор в автодополнении или отправка сообщения.

        Args:
            event: Событие отправки поля ввода
        """
        command_list = self.query_one("#command_list", CommandList)
        file_list = self.query_one("#file_list", FileList)

        # Enter в открытом списке выбора обрабатывается в on_key
        if self.selector_manager.selector_active:
            event.prevent_default()
            return

        elif not command_list.has_class("hidden"):
            command_list.apply_selection(event.input)
            event.prevent_default()
            return

        elif not file_list.has_class("hidden"):
            file_list.apply_selection(event.input)
            event.prevent_default()
            return

        if self.is_processing_stream:
            event.prevent_default()
            return

        # Флаг ставится сразу, чтобы повторный Enter не запустил вторую обработку
        self.is_processing_stream = True
        self.current_stream_task = asyncio.create_task(self._run_message_processing())
        command_list.add_class("hidden")
        file_list.add_class("hidden")
        event.prevent_default()

        self.query_one("#message_input").focus()

    def on_key(self, event: events.Key) -> None:
        """Обработка клавиш: навигация в списках и отмена обработки сообщения.

        Args:
            event: Событие нажатия клавиши
        """
        command_list = self.query_one("#command_list", CommandList)
        file_list = self.query_one("#file_list", FileList)

        # Список выбора (например, модели)
        if self.selector_manager.selector_active:
            if event.key == "down":
                self.selector_manager.select_next_item()
                event.prevent_default()
            elif event.key == "up":
                self.selector_manager.select_previous_item()
                event.prevent_default()
            elif event.key == "enter":
                self.selector_manager.confirm_selection()
                event.prevent_default()
            elif event.key == "escape":
                self.selector_manager.cancel_selection()
                event.prevent_default()

        # Автодополнение команд
        elif not command_list.has_class("hidden"):
            if event.key == "tab":
                command_list.select_next()
                event.prevent_default()
                event.stop()
            elif event.key == "shift+tab":
                command_list.select_previous()
                event.prevent_default()
                event.stop()
            elif event.key == "enter":
                command_list.apply_selection(self.query_one("#message_input"))
                event.prevent_default()
                self.query_one("#message_input").focus()
            elif event.key == "escape":
                command_list.add_class("hidden")
                event.prevent_default()
                self.query_one("#message_input").focus()

        # Автодополнение файлов
        elif not file_list.has_class("hidden"):
            if event.key == "tab":
                file_list.select_next()
                event.prevent_default()
                event.stop()
            elif event.key == "shift+tab":
                file_list.select_previous()
                event.prevent_default()
                event.stop()
            elif event.key == "enter":
                file_list.apply_selection(self.query_one("#message_input"))
                event.prevent_default()
                self.query_one("#message_input").focus()
            elif event.key == "escape":
                file_list.add_class("hidden")
                event.prevent_default()
                self.query_one("#message_input").focus()

        # Без открытых списков Tab не переключает фокус с поля ввода
        elif event.key == "tab" and command_list.has_class("hidden") and file_list.has_class("hidden"):
            event.prevent_default()
            event.stop()

        # Отмена запроса к GigaChat или терминальной команды
        elif event.key in ("escape", "ctrl+c") and self.is_processing_stream:
            self._cleanup_stream_processing()
            self.query_one("#message_input", Input).value = ""
            self.update_chat_display(f"**Вы:** {self.last_user_message}\n\n*Запрос отменен пользователем*")
            event.prevent_default()
            event.stop()

    async def _run_message_processing(self) -> None:
        """Обработка сообщения с гарантированным сбросом состояния после завершения или отмены."""
        try:
            await self.process_message()
        except asyncio.CancelledError:
            pass
        finally:
            self._hide_typing_indicator()
            self.is_processing_stream = False
            self.current_response_content = ""
            self.current_stream_task = None

    async def process_message(self) -> None:
        """Обработка введенного сообщения: команды приложения, обработчики или запрос к GigaChat."""
        input_field = self.query_one("#message_input", Input)
        user_text = input_field.value.strip()

        if not user_text:
            return

        self.last_user_message = user_text

        if user_text.lower().startswith('/exit'):
            self.app.exit("Результат работы")
            return

        if user_text.lower().startswith('/menu'):
            self.app.pop_screen()
            return

        # В чате показывается только последний обмен сообщениями
        self.clear_chat_display()

        for handler in self.handlers:
            if await handler.handle(user_text, input_field, self):
                return

        await self.handle_gigachat_message(user_text, input_field)

    async def handle_gigachat_message(self, user_text: str, input_field: Input) -> None:
        """Отправка сообщения в GigaChat и вывод ответа.

        Args:
            user_text: Текст сообщения
            input_field: Поле ввода
        """
        input_field.value = ""

        self.update_chat_display(f"**Вы:** {user_text}\n\n**GigaChat:**\n\n")

        self.current_typing_indicator = TypingIndicator()
        chat_container = self.query_one("#chat_container")
        chat_container.mount(self.current_typing_indicator)
        input_field.focus()

        await self.get_bot_response_stream(user_text)

    def _update_model_display(self) -> None:
        """Обновление названия модели в строке состояния."""
        model_widget = self.query_one(Model)
        current_model = self.cfg.get_model()
        model_widget.current_model = str(current_model)
        model_widget.refresh()

    def _update_directory_display(self) -> None:
        """Обновление текущей директории в строке состояния."""
        dir_widget = self.query_one(Dir)
        current_dir = self.command_utils.get_current_directory()
        dir_widget.current_dir = str(current_dir)
        dir_widget.refresh()

    def clear_chat_display(self) -> None:
        """Очистка области чата, в том числе временных виджетов (индикатора, списка выбора)."""
        chat_display = self.query_one("#chat_display", Markdown)
        chat_display.update("")

        chat_container = self.query_one("#chat_container")
        for child in chat_container.children:
            if child.id != "chat_display":
                child.remove()

    def update_chat_display(self, content: str = "") -> None:
        """Замена содержимого чата и прокрутка в конец.

        Args:
            content: Текст в формате Markdown
        """
        chat_display = self.query_one("#chat_display", Markdown)
        chat_display.update(content)
        self.query_one("#chat_container").scroll_end()

    def update_chat_display_stream(self, user_text: str, response_content: str) -> None:
        """Вывод сообщения пользователя и полученной части ответа.

        Args:
            user_text: Сообщение пользователя
            response_content: Полученная часть ответа
        """
        full_content = f"**Вы:** {user_text}\n\n**GigaChat:**\n\n{response_content}"
        self.update_chat_display(full_content)

    async def get_bot_response_stream(self, user_text: str) -> None:
        """Получение ответа GigaChat по частям с выводом в чат.

        Файлы и анализ проекта берутся из текущей директории чата (меняется через !cd).

        Args:
            user_text: Сообщение пользователя
        """
        self.current_response_content = ""
        has_content = False

        project_path = str(self.command_utils.get_current_directory())

        try:
            async for chunk in get_answer_stream(user_text, project_path=project_path):
                # С первой частью ответа индикатор ожидания больше не нужен
                if chunk.content and not has_content:
                    has_content = True
                    self._hide_typing_indicator()

                if chunk.content:
                    self.current_response_content += chunk.content
                    self.update_chat_display_stream(user_text, self.current_response_content)

                if chunk.error:
                    self._show_stream_error(user_text, chunk.error)
                    break

                if chunk.is_final:
                    break

                # Небольшая пауза для плавного отображения
                await asyncio.sleep(0.01)

        except Exception as e:
            self._show_stream_error(user_text, str(e))
        finally:
            self._hide_typing_indicator()
            self.current_response_content = ""

    def _show_stream_error(self, user_text: str, error: str) -> None:
        """Вывод ошибки после уже полученной части ответа.

        Args:
            user_text: Сообщение пользователя
            error: Текст ошибки
        """
        self._hide_typing_indicator()
        content = self.current_response_content
        if content:
            content += "\n\n"
        self.update_chat_display_stream(user_text, f"{content}**Ошибка:** {error}")
