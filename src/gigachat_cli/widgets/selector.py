"""Список для интерактивного выбора (например, модели)."""

from textual.widgets import Static
from textual.reactive import reactive


class SelectorWidget(Static):
    """Виджет списка с выделением выбранного элемента."""

    items = reactive([])
    selected_index = reactive(0)

    def render(self) -> str:
        """Отрисовка списка с выделением выбранного элемента.

        Returns:
            str: Список элементов в разметке Textual
        """
        if not self.items:
            return ""

        lines = []
        for i, item in enumerate(self.items):
            if i == self.selected_index:
                lines.append(f"➤ [green]{item}[/]")
            else:
                lines.append(f"  {item}")

        return "\n".join(lines)
