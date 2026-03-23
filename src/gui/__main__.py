import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from src.gui.main_window import MainWindow
from src.gui.style import STYLESHEET

_ICON_PATH = Path(__file__).parent / "assets" / "icon.png"


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Context Pilot")
    app.setStyleSheet(STYLESHEET)

    if _ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(_ICON_PATH)))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
