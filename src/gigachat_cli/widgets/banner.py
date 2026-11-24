"""Логотип GigaChat для приветствия в пустом чате."""

from textwrap import dedent

from textual.widgets import Static


_WIDE_LOGO = tuple(line.rstrip() for line in dedent("""
       █████████   ███                       █████████  █████                 █████
      ███░░░░░███ ░░░                       ███░░░░░███░░███                 ░░███
     ███     ░░░  ████   ███████  ██████   ███     ░░░  ░███████    ██████   ███████
    ░███         ░░███  ███░░███ ░░░░░███ ░███          ░███░░███  ░░░░░███ ░░███░
    ░███    █████ ░███ ░███ ░███  ███████ ░███          ░███ ░███   ███████   ░███
    ░░███  ░░███  ░███ ░███ ░███ ███░░███ ░░███     ███ ░███ ░███  ███░░███   ░███ ███
     ░░█████████  █████░░███████░░████████ ░░█████████  ████ █████░░████████  ░░█████
      ░░░░░░░░░  ░░░░░  ░░░░░███ ░░░░░░░░   ░░░░░░░░░  ░░░░ ░░░░░  ░░░░░░░░    ░░░░░
                        ███ ░███
                       ░░██████
                        ░░░░░░
""").strip("\n").splitlines())

_COMPACT_LOGO = (
    " ███  █████  ███   ███   ████ █   █  ███  █████",
    "█       █   █     █   █ █     █   █ █   █   █",
    "█ ███   █   █ ███ █████ █     █████ █████   █",
    "█   █   █   █   █ █   █ █     █   █ █   █   █",
    " ███  █████  ███  █   █  ████ █   █ █   █   █",
)


class Banner(Static):
    """Выбрать логотип, который помещается в текущую ширину окна."""

    def __init__(self) -> None:
        """Подготовить виджет без разметки и переноса логотипа."""
        super().__init__("GigaChat", id="chat_banner", markup=False)
        self._logo: tuple[str, ...] = ()

    def on_resize(self) -> None:
        """Сменить логотип при переходе между размерами терминала."""
        width = self.content_size.width
        if width >= max(map(len, _WIDE_LOGO)):
            logo = _WIDE_LOGO
        elif width >= max(map(len, _COMPACT_LOGO)):
            logo = _COMPACT_LOGO
        else:
            logo = ("GigaChat",)
        if logo != self._logo:
            self._logo = logo
            self.update("\n".join(logo))
