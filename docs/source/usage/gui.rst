GUI (PySide6)
=============

A tabbed control surface wraps every feature:

.. code-block:: bash

   python -m automation_file ui
   # or from the repo root during development:
   python main_ui.py

.. code-block:: python

   from automation_file import launch_ui

   launch_ui()

Tabs: Home, Local, Transfer, Progress, JSON actions, Triggers, Scheduler,
Servers. A persistent log panel below the tabs streams every call's result
or error. Background work runs on ``QThreadPool`` via ``ActionWorker`` so
the UI stays responsive.

The GUI shares the same singletons as the rest of the library — registering
a sink, custom command, or trigger from Python takes effect immediately in
the running window.
