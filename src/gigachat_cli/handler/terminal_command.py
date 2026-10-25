"""Обработчик терминальных команд: сообщения, начинающиеся с !."""

from textual.widgets import Input

from gigachat_cli.utils.command import CommandUtils
from gigachat_cli.widgets.typing import TypingIndicator


class TerminalHandler:
    """Обработчик терминальных команд: выполнение и вывод результата в чат."""

    def __init__(self, command_utils: CommandUtils):
        """Создание обработчика.

        Args:
            command_utils: Утилита выполнения команд (хранит текущую директорию)
        """
        super().__init__()
        self.command_utils = command_utils

    async def handle(self, user_text: str, input_field: Input, screen) -> bool:
        """Выполнение терминальной команды и вывод результата в чат.

        Args:
            user_text: Текст сообщения пользователя
            input_field: Поле ввода
            screen: Экран чата

        Returns:
            bool: True, если сообщение было терминальной командой
        """
        is_terminal, command = CommandUtils.is_terminal_command(user_text)
        if is_terminal:
            screen.update_chat_display(f"**Вы:** `!{command}`")

            screen.current_typing_indicator = TypingIndicator()
            chat_container = screen.query_one("#chat_container")
            chat_container.mount(screen.current_typing_indicator)

            success, output, return_code = await self.command_utils.execute_system_command(command)

            if screen.current_typing_indicator:
                screen.current_typing_indicator.stop_animation()
                screen.current_typing_indicator.remove()
                screen.current_typing_indicator = None

            formatted_output = CommandUtils.format_command_output(output, success, return_code)
            screen.update_chat_display(f"**Вы:** `!{command}`\n\n**Система:**\n\n{formatted_output}")

            # Команда могла сменить директорию (cd)
            screen._update_directory_display()

            input_field.value = ""
            input_field.focus()
            return True

        return False
