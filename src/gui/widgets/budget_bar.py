from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QProgressBar
from PySide6.QtCore import Qt


class BudgetBar(QWidget):
    """Token budget progress bar showing used / total tokens with colour coding."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._usage_label = QLabel("0 / 8 000 tokens")
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setMinimumWidth(120)
        self._pct_label = QLabel("0 %")
        self._pct_label.setFixedWidth(38)
        self._pct_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        layout.addWidget(self._usage_label)
        layout.addWidget(self._bar, stretch=1)
        layout.addWidget(self._pct_label)

    def update_budget(self, used: int, total: int) -> None:
        total = max(1, total)
        pct = int(used / total * 100)
        self._usage_label.setText(f"{used:,} / {total:,} tokens")
        self._bar.setValue(min(pct, 100))
        self._pct_label.setText(f"{pct} %")

        if pct >= 90:
            colour = "#e53935"
        elif pct >= 70:
            colour = "#fb8c00"
        else:
            colour = "#43a047"
        self._bar.setStyleSheet(
            f"QProgressBar::chunk {{ background: {colour}; border-radius: 3px; }}"
        )
