"""GUI launcher.

Boots a :class:`QApplication` (reusing any existing instance so the window can
be launched from inside an IPython / Spyder REPL) and shows the main window.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from automation_file.logging_config import file_automation_logger


def launch_ui(argv: Sequence[str] | None = None) -> int:
    """Launch the automation_file GUI. Blocks on the Qt event loop."""
    from PySide6.QtWidgets import QApplication

    from automation_file.ui.main_window import MainWindow

    args = list(argv) if argv is not None else sys.argv
    app = QApplication.instance() or QApplication(args)
    window = MainWindow()
    window.show()
    file_automation_logger.info("ui: launched main window")
    return int(app.exec())
