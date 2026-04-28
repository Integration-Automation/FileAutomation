Triggers
========

Watch local paths with ``watchdog`` and dispatch an action list whenever a
matching filesystem event fires. The module-level
:data:`~automation_file.trigger.trigger_manager` keeps a named registry of
active watchers so the JSON facade and the GUI share one lifecycle.

.. automodule:: automation_file.trigger
   :members:

.. automodule:: automation_file.trigger.manager
   :members:
