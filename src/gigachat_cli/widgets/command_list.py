"""Выпадающий список автодополнения команд (/help, /model и т.д.)."""

from textual.widgets import Static
from textual.reactive import reactive


class CommandList(Static):
    """Виджет автодополнения команд с описаниями и прокруткой."""

    can_focus = False

    commands = reactive([])
    selected_index = reactive(0)
    current_input = ""  # Текст поля ввода, по которому отфильтрованы команды
    visible_start = 0   # Индекс первой видимой команды
    visible_count = 5   # Количество команд, показываемых одновременно

    def update_commands(self, commands: list[str], current_input: str) -> None:
        """Обновление списка команд; пустой список скрывает виджет.

        Args:
            commands: Список команд для отображения
            current_input: Текущий текст из поля ввода
        """
        if commands:
            self.commands = commands
            self.current_input = current_input
            self.selected_index = 0
            self.visible_start = 0
            self.remove_class("hidden")
            self._update_display()
        else:
            self.add_class("hidden")
            self.commands = []

    def _update_display(self) -> None:
        """Отрисовка видимой части списка с выделением выбранной команды."""
        if not self.commands:
            return

        commands_with_desc = self.screen.list_utils.get_commands_with_descriptions(self.current_input)
        visible_commands = commands_with_desc[self.visible_start:self.visible_start + self.visible_count]

        formatted_commands = []
        for i, (cmd, description) in enumerate(visible_commands):
            actual_index = self.visible_start + i
            display_cmd = cmd[1:] if cmd.startswith('/') else cmd

            cmd_part = f"{display_cmd:<8}"
            line = f"{cmd_part} - {description}"

            # У выбранной команды показывается позиция, если список не помещается целиком
            if actual_index == self.selected_index:
                if len(commands_with_desc) > self.visible_count:
                    line = f"➤ {line} [{actual_index + 1}/{len(commands_with_desc)}]"
                else:
                    line = f"➤ {line}"
            else:
                line = f"  {line}"

            formatted_commands.append(line)

        self.update("\n".join(formatted_commands))

    def select_next(self) -> None:
        """Выбор следующей команды (после последней - переход к первой)."""
        if self.commands:
            self.selected_index = (self.selected_index + 1) % len(self.commands)
            # Прокрутка, чтобы выбранная команда оставалась видимой
            if self.selected_index >= self.visible_start + self.visible_count:
                self.visible_start += 1
            elif self.selected_index < self.visible_start:
                self.visible_start = self.selected_index
            self._update_display()

    def select_previous(self) -> None:
        """Выбор предыдущей команды (перед первой - переход к последней)."""
        if self.commands:
            self.selected_index = (self.selected_index - 1) % len(self.commands)
            # Прокрутка, чтобы выбранная команда оставалась видимой
            if self.selected_index < self.visible_start:
                self.visible_start -= 1
            elif self.selected_index >= self.visible_start + self.visible_count:
                self.visible_start = self.selected_index - self.visible_count + 1
            self._update_display()

    def get_selected_command(self) -> str:
        """Получение выбранной команды.

        Returns:
            str: Выбранная команда или пустая строка
        """
        if self.commands and 0 <= self.selected_index < len(self.commands):
            return self.commands[self.selected_index]
        return ""

    def apply_selection(self, input_field) -> None:
        """Подстановка выбранной команды в поле ввода.

        Args:
            input_field: Поле ввода для обновления
        """
        selected_cmd = self.get_selected_command()
        if selected_cmd and self.current_input:
            if ' ' in self.current_input:
                last_space_pos = self.current_input.rfind(' ')
                base_text = self.current_input[:last_space_pos + 1]
                new_text = base_text + selected_cmd
            else:
                new_text = selected_cmd

            input_field.value = new_text
            input_field.cursor_position = len(new_text)
            self.add_class("hidden")
            input_field.focus()
