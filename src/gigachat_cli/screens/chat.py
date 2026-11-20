"""Экран чата: ввод сообщений, команды, автодополнение и потоковый вывод ответа."""

import importlib.resources
import asyncio
import re
from contextlib import aclosing

from textual.app import ComposeResult
from textual.await_complete import AwaitComplete
from textual.widgets import Markdown, Static, TextArea
from textual.screen import Screen
from textual.timer import Timer
from textual.containers import Vertical, VerticalScroll, Horizontal
from textual import events

from gigachat_cli.core.session import ChatSession
from gigachat_cli.core.sessions import MAX_SAVED_EXCHANGES, SavedSession, SessionData, SessionStore, SessionStoreError
from gigachat_cli.utils.list import ListUtils
from gigachat_cli.utils.selector import SelectorManager

from gigachat_cli.handler.help import HelpHandler
from gigachat_cli.handler.file_edit import FileEditHandler
from gigachat_cli.handler.model import ModelHandler
from gigachat_cli.handler.terminal_command import TerminalHandler
from gigachat_cli.widgets.banner import Banner
from gigachat_cli.widgets.file_review import FileReview

from gigachat_cli.widgets.command_list import CommandList
from gigachat_cli.widgets.file_list import FileList
from gigachat_cli.widgets.message_input import MessageInput
from gigachat_cli.widgets.model import Model
from gigachat_cli.widgets.dir import Dir


_RESPONSE_FRAME_INTERVAL = 1 / 30
_SESSION_COMMANDS = {"/new", "/sessions", "/resume"}
_UNSAVED_COMMANDS = _SESSION_COMMANDS | {"/exit", "/help", "/model"}


def _is_saved_prompt(text: str) -> bool:
    """Исключить системные команды и внутреннюю навигацию из истории на диске."""
    text = text.lstrip()
    return bool(text) and not text.startswith("!") and text.split(maxsplit=1)[0].lower() not in _UNSAVED_COMMANDS


class ChatScreen(Screen):
    """Экран чата с GigaChat.

    Сообщение обрабатывается одной задачей сессии: команда /exit,
    обработчики команд (/help, /model, !команда) или запрос к GigaChat.
    Пока задача выполняется, повторная отправка игнорируется, а Esc/Ctrl+C отменяет ее.
    """

    CSS = importlib.resources.files("gigachat_cli.styles").joinpath("chat.css").read_text()

    def __init__(self, *, store: SessionStore | None = None):
        """Создание экрана, утилит и обработчиков команд."""
        super().__init__()
        self.session = ChatSession()
        self.list_utils = ListUtils()
        self._store = store
        self._saved_session: SavedSession | None = None
        self._saved_exchanges: list[str] = []
        self._save_current = False
        self._chat_closing = False
        self._file_edits = FileEditHandler()

        self.selector_manager = SelectorManager(self)

        # Обработчики проверяются по порядку, первый подходящий обрабатывает сообщение
        self.handlers =[
            HelpHandler(),
            self._file_edits,
            ModelHandler(self.session, self),
            TerminalHandler()
        ]

        # Состояние обработки текущего сообщения
        self._operation_status: str | None = None
        self._file_review: FileReview | None = None
        self._active_exchange = Markdown(classes="chat_exchange")
        self.current_exchange: str = ""
        self._display_revision = 0
        self._follow_scroll_y: float | None = None

    def compose(self) -> ComposeResult:
        """Создание виджетов экрана.

        Yields:
            Рабочая папка, модель, история, подсказки и поле ввода.
        """
        with Horizontal(classes="status_bar"):
            yield Static("GigaChat", id="chat_title")
            yield Dir(classes="dir")
            yield Model(classes="model")
        with VerticalScroll(id="chat_container"):
            with Vertical(id="chat_welcome"):
                yield Banner()
                yield Static("Спросите о проекте, предложите правку через /edit или откройте /help.")
            yield self._active_exchange
        yield CommandList(id="command_list", classes="hidden")
        yield FileList(id="file_list", classes="hidden")
        yield MessageInput(id="message_input")
        yield Static("Enter отправить · F2 перенос · F3/F4 история · / команды", id="composer_hint")

    async def on_mount(self) -> None:
        """Фокус на поле ввода и заполнение строки состояния."""
        self.query_one("#message_input").focus()
        self._update_directory_display()
        self._update_model_display()
        self.query_one("#command_list", CommandList).add_class("hidden")
        self.query_one("#file_list", FileList).add_class("hidden")
        if self._store is not None:
            try:
                saved = await asyncio.to_thread(self._store.load)
            except SessionStoreError as error:
                self.notify(str(error), severity="warning")
                return
            if saved is not None:
                await self._show_saved_session(saved)
            else:
                self.session.restore_model_history(())

    def on_unmount(self) -> None:
        """Отмена обработки сообщения при закрытии экрана."""
        self._chat_closing = True
        self.session.cancel()

    def set_operation_status(self, status: str | None) -> None:
        """Показать ход операции у поля ввода или вернуть подсказку клавиш."""
        self._operation_status = status
        self._update_composer_hint()

    def _update_composer_hint(self) -> None:
        """Вывести подсказку для текущей операции или режима ввода."""
        if self._file_review is not None:
            text = "1/2 выбрать · ↑/↓ выделить · Enter подтвердить · Esc отменить"
        elif self._operation_status:
            text = f"{self._operation_status} · Esc / Ctrl+C отменить"
        elif not self.query_one(CommandList).has_class("hidden") or not self.query_one(FileList).has_class("hidden"):
            text = "Tab варианты · Enter выбрать · Esc закрыть"
        else:
            text = "Enter отправить · F2 перенос · F3/F4 история · / команды"
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

        if self._file_review is not None and self._file_review.handle_review_key(event.key):
            event.prevent_default()
            event.stop()
            return

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
        self._save_current = False
        try:
            await self.process_message()
        except asyncio.CancelledError:
            if self.is_mounted and not self._chat_closing:
                self.update_chat_display(
                    f"{self.current_exchange}\n\n*Запрос отменен пользователем*"
                )
        except Exception as error:
            if self.is_mounted and not self._chat_closing:
                self.update_chat_display(f"{self.current_exchange}\n\n**Ошибка:** {error}")
        finally:
            if self.is_mounted and not self._chat_closing:
                self.set_operation_status(None)
                if self._save_current and self.current_exchange:
                    await self._save_exchange()

    async def process_message(self) -> None:
        """Обработка введенного сообщения: команды приложения, обработчики или запрос к GigaChat."""
        input_field = self.query_one(MessageInput)
        text = input_field.text
        trimmed = text.strip()
        if not trimmed:
            return

        user_text = trimmed if trimmed.startswith(("/", "!")) else text
        if user_text.startswith("!") and len(user_text.splitlines()) > 1:
            await self._begin_exchange()
            self.update_chat_display("**Ошибка:** терминальная команда должна занимать одну строку.")
            return
        input_field.remember(user_text)

        if user_text.lower() == "/exit":
            self.app.exit("Результат работы")
            return

        command = user_text.split(maxsplit=1)[0].lower()
        if command in _SESSION_COMMANDS:
            input_field.text = ""
            await self._handle_session_command(command, user_text[len(command):].strip())
            return

        await self._begin_exchange()
        self._save_current = _is_saved_prompt(user_text)
        for handler in self.handlers:
            if await handler.handle(user_text, input_field, self):
                return

        await self.handle_gigachat_message(user_text, input_field)

    async def _save_exchange(self) -> None:
        """Записать законченный обмен без предложений, ожидающих подтверждения."""
        if self._store is None:
            return
        self._saved_exchanges.append(self.current_exchange)
        self._saved_exchanges = self._saved_exchanges[-MAX_SAVED_EXCHANGES:]
        prompts = self.query_one(MessageInput).submitted_messages
        data = SessionData(
            tuple(self._saved_exchanges),
            tuple(prompt for prompt in prompts if _is_saved_prompt(prompt)),
            self.session.export_model_history(),
        )
        write = asyncio.create_task(asyncio.to_thread(self._store.save, data, self._saved_session))
        try:
            try:
                self._saved_session = await asyncio.shield(write)
            except asyncio.CancelledError:
                self._saved_session = await write
        except SessionStoreError as error:
            if self.is_mounted and not self._chat_closing:
                self.notify(str(error), severity="warning")

    async def _show_saved_session(self, saved: SavedSession | None) -> None:
        """Перестроить диалог из сохранённых обменов или начать пустой."""
        data = saved.data if saved is not None else SessionData((), (), ())
        self._saved_session = saved
        self._saved_exchanges = list(data.exchanges)
        self.session.restore_model_history(data.model_history)
        self._file_edits.reset()
        editor = self.query_one(MessageInput)
        editor.restore_history(data.prompts)
        container = self.query_one("#chat_container", VerticalScroll)
        self._display_revision += 1
        self._follow_scroll_y = None
        self.current_exchange = ""
        self.query_one("#chat_welcome").set_class(bool(data.exchanges), "hidden")
        await container.remove_children(Markdown)
        self._active_exchange = Markdown(classes="chat_exchange")
        await container.mount(
            *(Markdown(exchange, classes="chat_exchange") for exchange in data.exchanges),
            self._active_exchange,
        )
        self.call_after_refresh(container.scroll_end, animate=False)
        editor.focus()

    async def _handle_session_command(self, command: str, argument: str) -> None:
        """Открыть, перечислить или сменить диалоги текущего проекта."""
        if command == "/new" and not argument:
            await self._show_saved_session(None)
            return
        try:
            if self._store is None:
                raise SessionStoreError("Хранилище диалогов недоступно.")
            if command == "/resume" and argument:
                saved = await asyncio.to_thread(self._store.load, argument)
                if saved is not None:
                    await self._show_saved_session(saved)
                    return
                result = "Диалог с таким идентификатором не найден в этом проекте. Список: `/sessions`."
            elif command == "/sessions" and not argument:
                rows = await asyncio.to_thread(self._store.recent)
                if rows:
                    lines = "\n".join(f"{session_id}  {title}" for session_id, title in rows)
                    result = f"**Сохранённые диалоги**\n\n```text\n{lines}\n```\n\nОткрыть: `/resume ID`."
                else:
                    result = "В этом проекте пока нет сохранённых диалогов."
            else:
                usage = "/resume ID" if command == "/resume" else command
                result = f"Использование: `{usage}`."
        except SessionStoreError as error:
            result = f"**Ошибка:** {error}"
        await self._begin_exchange()
        self.update_chat_display(result)

    async def review_file(self, review: FileReview) -> bool:
        """Показать подтверждение в диалоге и вернуть фокус после выбора."""
        editor = self.query_one(MessageInput)
        self._file_review = review
        editor.disabled = True
        editor.add_class("hidden")
        self.set_operation_status("Ожидание подтверждения правки")
        try:
            await self.query_one("#chat_container", VerticalScroll).mount(review)
            reject = review.query_one("#reject_change")
            reject.focus()
            reject.scroll_visible(animate=False)
            return await review.wait_for_decision()
        finally:
            self._file_review = None
            if review.is_mounted and not self._chat_closing:
                await review.remove()
            if self.is_mounted and not self._chat_closing:
                editor.remove_class("hidden")
                editor.disabled = False
                editor.focus()

    async def _begin_exchange(self) -> None:
        """Оставить прочитанные блоки на месте и открыть следующий обмен."""
        self.query_one("#chat_welcome").add_class("hidden")
        has_previous_exchange = bool(self.current_exchange)
        self.current_exchange = ""
        if has_previous_exchange:
            chat_container = self.query_one("#chat_container", VerticalScroll)
            scroll_y = chat_container.scroll_y
            follow_response = chat_container.is_vertical_scroll_end or scroll_y == self._follow_scroll_y
            self._active_exchange = Markdown(classes="chat_exchange")
            await chat_container.mount(self._active_exchange)
            if follow_response and chat_container.scroll_y == scroll_y:
                self._follow_scroll_y = scroll_y

    async def handle_gigachat_message(self, user_text: str, input_field: MessageInput) -> None:
        """Отправка сообщения в GigaChat и вывод ответа.

        Args:
            user_text: Текст сообщения
            input_field: Поле ввода
        """
        input_field.text = ""

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

    def update_chat_display(self, content: str) -> AwaitComplete:
        """Обновить текущий обмен, следуя за ответом только при чтении конца чата.

        Args:
            content: Текст в формате Markdown.

        Returns:
            Операция, которую можно дождаться после обновления блока.
        """
        chat_container = self.query_one("#chat_container", VerticalScroll)
        follow_response = (
            chat_container.is_vertical_scroll_end
            or chat_container.scroll_y == self._follow_scroll_y
        )
        self._follow_scroll_y = chat_container.scroll_y if follow_response else None
        self.current_exchange = content
        self._display_revision += 1
        update = self._active_exchange.update(content)
        if follow_response:
            self.call_later(
                self._scroll_after_update, update, self._display_revision, chat_container.scroll_y
            )
        return update

    async def _scroll_after_update(self, update: AwaitComplete, revision: int, scroll_y: float) -> None:
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

    async def get_bot_response_stream(self, user_text: str) -> None:
        """Объединить фрагменты ответа и обновлять только активный блок диалога."""
        if len(user_text.splitlines()) > 1 or "\n" in user_text:
            longest_run = max((len(run) for run in re.findall(r"~+", user_text)), default=0)
            fence = "~" * max(3, longest_run + 1)
            prompt = f"\n\n{fence}\n{user_text}\n{fence}"
        else:
            prompt = f" {user_text}"

        heading = f"**Вы:**{prompt}\n\n**GigaChat:**\n\n"
        last_update = self.update_chat_display(heading)
        pending: list[str] = []
        response = ""
        error: str | None = None
        timer: Timer | None = None
        finished = False

        def paint(*, final: bool = False) -> None:
            """Обновить ответ порцией, когда закончена предыдущая отрисовка."""
            nonlocal timer, last_update, response
            if finished and not final:
                return
            if timer is not None:
                timer.stop()
                timer = None
            if self._chat_closing or not self.is_mounted or not (pending or error):
                return
            if not final and not last_update.is_done:
                timer = self.set_timer(_RESPONSE_FRAME_INTERVAL, paint)
                return
            response += "".join(pending)
            pending.clear()
            text = response
            if error:
                text = f"{text}\n\n**Ошибка:** {error}" if text else f"**Ошибка:** {error}"
            last_update = self.update_chat_display(heading + text)

        has_content = False
        try:
            async with aclosing(self.session.answer(user_text)) as stream:
                async for chunk in stream:
                    if chunk.content:
                        if not has_content:
                            has_content = True
                            self.set_operation_status("Генерация ответа")
                        pending.append(chunk.content)
                        if timer is None:
                            timer = self.set_timer(_RESPONSE_FRAME_INTERVAL, paint)
                    if chunk.error or chunk.is_final:
                        error = chunk.error
                        break
        except Exception as exc:
            error = str(exc) or type(exc).__name__
        finally:
            # При отмене внешний обработчик добавляет пометку к уже показанному тексту.
            finished = True
            paint(final=True)
