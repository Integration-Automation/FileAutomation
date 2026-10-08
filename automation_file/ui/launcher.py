"""GUI launcher.

Boots a :class:`QApplication` (reusing any existing instance so the window can
be launched from inside an IPython / Spyder REPL) and shows the main window.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from automation_file.core.optional import require_module
from automation_file.logging_config import file_automation_logger

_GUI_EXTRA = "gui"


def launch_ui(argv: Sequence[str] | None = None) -> int:
    """Launch the automation_file GUI. Blocks on the Qt event loop.

    Raises :class:`~automation_file.exceptions.OptionalDependencyException`,
    naming the ``gui`` extra, when PySide6 is not installed.
    """
    widgets = require_module("PySide6.QtWidgets", extra=_GUI_EXTRA)

    from automation_file.ui.main_window import MainWindow

    args = list(argv) if argv is not None else sys.argv
    app = widgets.QApplication.instance() or widgets.QApplication(args)
    window = MainWindow()
    window.show()
    file_automation_logger.info("ui: launched main window")
    return int(app.exec())
