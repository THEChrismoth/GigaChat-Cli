"""Экран чата: ввод сообщений, команды, автодополнение и потоковый вывод ответа."""

import importlib.resources
import asyncio
import re
from contextlib import aclosing

from textual.app import ComposeResult
from textual.widgets import Markdown, Static, TextArea
from textual.screen import Screen
from textual.containers import VerticalScroll, Horizontal
from textual import events

from gigachat_cli.core.session import ChatSession
from gigachat_cli.utils.list import ListUtils
from gigachat_cli.utils.selector import SelectorManager

from gigachat_cli.handler.help import HelpHandler
from gigachat_cli.handler.file_edit import FileEditHandler
from gigachat_cli.handler.model import ModelHandler
from gigachat_cli.handler.terminal_command import TerminalHandler

from gigachat_cli.widgets.command_list import CommandList
from gigachat_cli.widgets.file_list import FileList
from gigachat_cli.widgets.message_input import MessageInput
from gigachat_cli.widgets.model import Model
from gigachat_cli.widgets.dir import Dir


class ChatScreen(Screen):
    """Экран чата с GigaChat.

    Сообщение обрабатывается одной задачей сессии: команды /exit и /menu,
    обработчики команд (/help, /model, !команда) или запрос к GigaChat.
    Пока задача выполняется, повторная отправка игнорируется, а Esc/Ctrl+C отменяет ее.
    """

    CSS = importlib.resources.files("gigachat_cli.styles").joinpath("chat.css").read_text()

    def __init__(self):
        """Создание экрана, утилит и обработчиков команд."""
        super().__init__()
        self.session = ChatSession()
        self.list_utils = ListUtils()

        self.selector_manager = SelectorManager(self)

        # Обработчики проверяются по порядку, первый подходящий обрабатывает сообщение
        self.handlers =[
            HelpHandler(),
            FileEditHandler(),
            ModelHandler(self.session, self),
            TerminalHandler()
        ]

        # Состояние обработки текущего сообщения
        self._operation_status: str | None = None
        self.current_response_content: str = ""
        self.completed_exchanges: list[str] = []
        self.current_exchange: str = ""
        self._display_revision = 0
        self._follow_scroll_y: float | None = None

    def compose(self) -> ComposeResult:
        """Создание виджетов экрана.

        Yields:
            Рабочая папка, модель, история, подсказки и поле ввода.
        """
        with Horizontal(classes="status_bar"):
            yield Dir(classes="dir")
            yield Model(classes="model")
        with VerticalScroll(id="chat_container"):
            yield Static(
                "[bold]GigaChat[/bold]\nЗадайте вопрос о проекте или введите /help.",
                id="chat_welcome",
            )
            yield Markdown("", id="chat_display")
        yield CommandList(id="command_list", classes="hidden")
        yield FileList(id="file_list", classes="hidden")
        yield MessageInput(id="message_input")
        yield Static("Enter отправить · F2 перенос · F3/F4 история", id="composer_hint")

    def on_mount(self) -> None:
        """Фокус на поле ввода и заполнение строки состояния."""
        self.query_one("#message_input").focus()
        self._update_directory_display()
        self._update_model_display()
        self.query_one("#command_list", CommandList).add_class("hidden")
        self.query_one("#file_list", FileList).add_class("hidden")

    def on_unmount(self) -> None:
        """Отмена обработки сообщения при закрытии экрана."""
        self.session.cancel()

    def set_operation_status(self, status: str | None) -> None:
        """Показать ход операции у поля ввода или вернуть подсказку клавиш."""
        self._operation_status = status
        self._update_composer_hint()

    def _update_composer_hint(self) -> None:
        """Вывести подсказку для текущей операции или режима ввода."""
        if self._operation_status:
            text = f"{self._operation_status} · Esc / Ctrl+C отменить"
        elif not self.query_one(CommandList).has_class("hidden") or not self.query_one(FileList).has_class("hidden"):
            text = "Tab варианты · Enter выбрать · Esc закрыть"
        else:
            text = "Enter отправить · F2 перенос · F3/F4 история"
        self.query_one("#composer_hint", Static).update(text)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Показ автодополнения команд (/...) или файлов (!команда ...).

        Args:
            event: Событие изменения текста в поле ввода
        """
        input_field = event.text_area
        command_list = self.query_one("#command_list", CommandList)
        file_list = self.query_one("#file_list", FileList)

        if input_field.document.line_count > 1:
            command_list.add_class("hidden")
            file_list.add_class("hidden")
        elif self.list_utils.should_show_commands(input_field.text):
            filtered_commands = self.list_utils.get_filtered_commands(input_field.text)
            command_list.update_commands(filtered_commands, input_field.text)
            file_list.add_class("hidden")

        elif self.session.completion.should_show_files(input_field.text):
            command_list.add_class("hidden")
            files, current_command, current_path = self.session.completion.get_files_for_completion(input_field.text)
            if files:
                file_list.update_files(files, current_command, current_path)
            else:
                file_list.add_class("hidden")

        else:
            command_list.add_class("hidden")
            file_list.add_class("hidden")
        self._update_composer_hint()

    def on_message_input_submitted(self, event: MessageInput.Submitted) -> None:
        """Обработка Enter: выбор в автодополнении или отправка сообщения.

        Args:
            event: Событие отправки поля ввода
        """
        command_list = self.query_one("#command_list", CommandList)
        file_list = self.query_one("#file_list", FileList)

        if self.selector_manager.selector_active:
            return

        input_field = self.query_one(MessageInput)
        if not command_list.has_class("hidden") and command_list.get_selected_command() != input_field.text:
            command_list.apply_selection(input_field)
            self._update_composer_hint()
            return

        if not file_list.has_class("hidden"):
            file_list.apply_selection(input_field)
            self._update_composer_hint()
            return

        if self.session.start(self._run_message_processing):
            command_list.add_class("hidden")
            file_list.add_class("hidden")
            self._update_composer_hint()

    def on_key(self, event: events.Key) -> None:
        """Обработка клавиш: навигация в списках и отмена обработки сообщения.

        Args:
            event: Событие нажатия клавиши
        """
        command_list = self.query_one("#command_list", CommandList)
        file_list = self.query_one("#file_list", FileList)

        if event.key == "ctrl+c" and self.session.busy:
            self.session.cancel()
            event.prevent_default()
            event.stop()
            return

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
        elif isinstance(self.focused, MessageInput) and not command_list.has_class("hidden"):
            if event.key == "tab":
                command_list.select_next()
                event.prevent_default()
                event.stop()
            elif event.key == "shift+tab":
                command_list.select_previous()
                event.prevent_default()
                event.stop()
            elif event.key == "escape":
                command_list.add_class("hidden")
                self._update_composer_hint()
                event.prevent_default()
                self.query_one("#message_input").focus()

        # Автодополнение файлов
        elif isinstance(self.focused, MessageInput) and not file_list.has_class("hidden"):
            if event.key == "tab":
                file_list.select_next()
                event.prevent_default()
                event.stop()
            elif event.key == "shift+tab":
                file_list.select_previous()
                event.prevent_default()
                event.stop()
            elif event.key == "escape":
                file_list.add_class("hidden")
                self._update_composer_hint()
                event.prevent_default()
                self.query_one("#message_input").focus()

        # Отмена запроса к GigaChat или терминальной команды
        elif event.key in ("escape", "ctrl+c") and self.session.busy:
            self.session.cancel()
            event.prevent_default()
            event.stop()

    async def _run_message_processing(self) -> None:
        """Обработка сообщения с гарантированным сбросом состояния после завершения или отмены."""
        try:
            await self.process_message()
        except asyncio.CancelledError:
            if self.is_mounted:
                self.update_chat_display(
                    f"{self.current_exchange}\n\n*Запрос отменен пользователем*"
                )
        except Exception as error:
            if self.is_mounted:
                self.update_chat_display(f"{self.current_exchange}\n\n**Ошибка:** {error}")
        finally:
            self.current_response_content = ""
            if self.is_mounted:
                self.set_operation_status(None)

    async def process_message(self) -> None:
        """Обработка введенного сообщения: команды приложения, обработчики или запрос к GigaChat."""
        input_field = self.query_one(MessageInput)
        text = input_field.text
        trimmed = text.strip()
        if not trimmed:
            return

        user_text = trimmed if trimmed.startswith(("/", "!")) else text
        if user_text.startswith("!") and len(user_text.splitlines()) > 1:
            self._begin_exchange()
            self.update_chat_display("**Ошибка:** терминальная команда должна занимать одну строку.")
            return
        input_field.remember(user_text)

        if user_text.lower() == "/exit":
            self.app.exit("Результат работы")
            return

        if user_text.lower() == "/menu":
            input_field.text = ""
            self.app.push_screen("menu")
            return

        self._begin_exchange()
        for handler in self.handlers:
            if await handler.handle(user_text, input_field, self):
                return

        await self.handle_gigachat_message(user_text, input_field)

    def _begin_exchange(self) -> None:
        """Убрать приветствие и подготовить место для нового обмена."""
        if self.current_exchange:
            self.completed_exchanges.append(self.current_exchange)
        self.query_one("#chat_welcome").add_class("hidden")
        self.clear_chat_display()

    async def handle_gigachat_message(self, user_text: str, input_field: MessageInput) -> None:
        """Отправка сообщения в GigaChat и вывод ответа.

        Args:
            user_text: Текст сообщения
            input_field: Поле ввода
        """
        input_field.text = ""

        self.update_chat_display_stream(user_text, "")

        self.set_operation_status("Ожидание ответа")
        input_field.focus()

        await self.get_bot_response_stream(user_text)

    def _update_model_display(self) -> None:
        """Обновление названия модели в строке состояния."""
        model_widget = self.query_one(Model)
        current_model = self.session.get_model()
        model_widget.current_model = str(current_model)
        model_widget.refresh()

    def _update_directory_display(self) -> None:
        """Обновление текущей директории в строке состояния."""
        dir_widget = self.query_one(Dir)
        current_dir = self.session.directory
        dir_widget.current_dir = str(current_dir)
        dir_widget.refresh()

    def clear_chat_display(self) -> None:
        """Очистить текущий обмен и временные виджеты, сохранив завершённые обмены."""
        chat_display = self.query_one("#chat_display", Markdown)
        self.current_exchange = ""
        chat_display.update("\n\n---\n\n".join(self.completed_exchanges))

        chat_container = self.query_one("#chat_container")
        for child in chat_container.children:
            if child.id not in {"chat_display", "chat_welcome"}:
                child.remove()

    def update_chat_display(self, content: str = "") -> None:
        """Обновить текущий обмен, следуя за ответом только при чтении конца чата.

        Args:
            content: Текст в формате Markdown
        """
        chat_container = self.query_one("#chat_container", VerticalScroll)
        follow_response = (
            chat_container.is_vertical_scroll_end
            or chat_container.scroll_y == self._follow_scroll_y
        )
        self._follow_scroll_y = chat_container.scroll_y if follow_response else None
        chat_display = self.query_one("#chat_display", Markdown)
        self.current_exchange = content
        self._display_revision += 1
        update = chat_display.update("\n\n---\n\n".join([*self.completed_exchanges, content]))
        if follow_response:
            self.call_later(
                self._scroll_after_update, update, self._display_revision, chat_container.scroll_y
            )

    async def _scroll_after_update(self, update, revision: int, scroll_y: float) -> None:
        """Дождаться Markdown и не сбрасывать прокрутку, изменённую во время рендера."""
        await update
        chat_container = self.query_one("#chat_container", VerticalScroll)
        if revision == self._display_revision and chat_container.scroll_y == scroll_y:
            chat_container.scroll_end(animate=False)
        self.call_after_refresh(self._finish_follow_scroll, revision)

    def _finish_follow_scroll(self, revision: int) -> None:
        """Сбросить временную позицию после завершения последнего обновления."""
        if revision == self._display_revision:
            self._follow_scroll_y = None

    def update_chat_display_stream(self, user_text: str, response_content: str) -> None:
        """Вывод сообщения пользователя и полученной части ответа.

        Args:
            user_text: Сообщение пользователя
            response_content: Полученная часть ответа
        """
        if len(user_text.splitlines()) > 1 or "\n" in user_text:
            longest_run = max((len(run) for run in re.findall(r"\x60+", user_text)), default=0)
            fence = "\x60" * max(3, longest_run + 1)
            user_text = f"\n\n{fence}\n{user_text}\n{fence}"
        else:
            user_text = f" {user_text}"
        full_content = f"**Вы:**{user_text}\n\n**GigaChat:**\n\n{response_content}"
        self.update_chat_display(full_content)

    async def get_bot_response_stream(self, user_text: str) -> None:
        """Получение ответа GigaChat по частям с выводом в чат.

        Файлы и анализ проекта берутся из текущей директории чата (меняется через !cd).

        Args:
            user_text: Сообщение пользователя
        """
        self.current_response_content = ""
        has_content = False

        try:
            async with aclosing(self.session.answer(user_text)) as stream:
                async for chunk in stream:
                    if chunk.content and not has_content:
                        has_content = True
                        self.set_operation_status("Генерация ответа")

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

    def _show_stream_error(self, user_text: str, error: str) -> None:
        """Вывод ошибки после уже полученной части ответа.

        Args:
            user_text: Сообщение пользователя
            error: Текст ошибки
        """
        content = self.current_response_content
        if content:
            content += "\n\n"
        self.update_chat_display_stream(user_text, f"{content}**Ошибка:** {error}")
