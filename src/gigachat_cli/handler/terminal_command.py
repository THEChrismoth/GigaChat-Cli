"""Обработчик терминальных команд: сообщения, начинающиеся с !."""

from gigachat_cli.widgets.message_input import MessageInput

from gigachat_cli.core.command import CommandUtils


class TerminalHandler:
    """Обработчик терминальных команд: выполнение и вывод результата в чат."""

    async def handle(self, user_text: str, input_field: MessageInput, screen) -> bool:
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
            input_field.text = ""
            screen.update_chat_display(f"**Вы:** `!{command}`")

            screen.set_operation_status("Выполнение команды")
            success, output, return_code = await screen.session.execute_command(command)

            formatted_output = CommandUtils.format_command_output(output, success, return_code)
            screen.update_chat_display(f"**Вы:** `!{command}`\n\n**Система:**\n\n{formatted_output}")

            # Команда могла сменить директорию (cd)
            screen._update_directory_display()

            input_field.focus()
            return True

        return False
