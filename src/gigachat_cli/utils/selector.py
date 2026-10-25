"""Управление списком выбора в чате (например, выбор модели)."""

from textual.widgets import Static

from gigachat_cli.widgets.selector import SelectorWidget


class SelectorManager:
    """Показ списка выбора в чате, навигация по нему и вызов обработчика выбора.

    Пока список открыт, поле ввода заблокировано, а клавиши ↑/↓/Enter/Esc
    обрабатываются экраном чата и передаются сюда.
    """

    def __init__(self, screen):
        """Создание менеджера.

        Args:
            screen: Экран чата, в котором показывается список
        """
        self.screen = screen
        self.selector_active = False
        self.selector_index = 0
        self.selector_items = []
        self.selector_title = ""
        self.selector_callback = None
        self.selector_widget = None
        self.selector_instruction = None

    def show_selector(self, items: list, title: str = "Выберите опцию:", callback=None) -> None:
        """Показ списка выбора вместо содержимого чата.

        Args:
            items: Элементы для выбора
            title: Заголовок списка
            callback: Обработчик выбора: callback(выбранный элемент, индекс)
        """
        self.selector_active = True
        self.selector_index = 0
        self.selector_items = items
        self.selector_title = title
        self.selector_callback = callback

        self.screen.clear_chat_display()

        # Пока открыт список, ввод сообщений заблокирован
        message_input = self.screen.query_one("#message_input")
        message_input.disabled = True
        message_input.placeholder = ""
        message_input.blur()

        self.selector_widget = SelectorWidget()
        self.selector_widget.items = items
        self.selector_widget.selected_index = 0

        selector_content = f"**{title}**\n\n"
        self.screen.update_chat_display(selector_content)

        chat_container = self.screen.query_one("#chat_container")
        chat_container.mount(self.selector_widget)

        instruction = Static("\n  Используйте ↑↓ для выбора, Enter для подтверждения, Esc для отмены")
        chat_container.mount(instruction)
        self.selector_instruction = instruction

    def _update_selector_display(self) -> None:
        """Перерисовка списка с текущим выбранным элементом."""
        if self.selector_widget:
            self.selector_widget.selected_index = self.selector_index
            self.selector_widget.refresh()

    def select_next_item(self) -> None:
        """Выбор следующего элемента (после последнего - переход к первому)."""
        if self.selector_active:
            self.selector_index = (self.selector_index + 1) % len(self.selector_items)
            self._update_selector_display()

    def select_previous_item(self) -> None:
        """Выбор предыдущего элемента (перед первым - переход к последнему)."""
        if self.selector_active:
            self.selector_index = (self.selector_index - 1) % len(self.selector_items)
            self._update_selector_display()

    def confirm_selection(self) -> None:
        """Подтверждение выбора: закрытие списка и вызов обработчика."""
        if self.selector_active:
            selected_item = self.selector_items[self.selector_index]

            # Список удаляется до вызова обработчика, чтобы тот мог обновить чат
            if self.selector_widget:
                self.selector_widget.remove()
            if self.selector_instruction:
                self.selector_instruction.remove()

            message_input = self.screen.query_one("#message_input")
            message_input.disabled = False
            message_input.placeholder = "Введите сообщение... (Нажмите Enter для отправки)"
            message_input.focus()

            if self.selector_callback:
                self.selector_callback(selected_item, self.selector_index)

            self.selector_active = False
            self.screen.query_one("#message_input").focus()

    def cancel_selection(self) -> None:
        """Отмена выбора и закрытие списка."""
        if self.selector_active:
            if self.selector_widget:
                self.selector_widget.remove()
            if self.selector_instruction:
                self.selector_instruction.remove()

            message_input = self.screen.query_one("#message_input")
            message_input.disabled = False
            message_input.placeholder = "Введите сообщение... (Нажмите Enter для отправки)"
            message_input.focus()

            self.selector_active = False
            self.screen.update_chat_display("❌ Выбор отменен")
            self.screen.query_one("#message_input").focus()
