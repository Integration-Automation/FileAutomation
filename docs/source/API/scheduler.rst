Scheduler
=========

The scheduler runs action lists and pipelines when something fires them: a cron
expression with an optional time zone, a file event, an event on the bus, the end
of another pipeline's run, or a call. Every firing leaves a run record in one of
seven states, a job does not overlap itself unless it allows it, and a run can be
given a timeout and can be cancelled. Usage is described in the manual chapter
*Scheduler*.

.. automodule:: automation_file.scheduler
   :members:

Scheduler and actions
---------------------

.. automodule:: automation_file.scheduler.manager
   :members:

Jobs
----

.. automodule:: automation_file.scheduler.job
   :members:

Triggers
--------

.. automodule:: automation_file.scheduler.triggers
   :members:

Cron expressions and time zones
-------------------------------

The parser understands the standard 5-field syntax (minute hour day-of-month
month day-of-week) with ``*``, ranges, lists, and ``*/n`` steps plus month /
day-of-week aliases.

.. automodule:: automation_file.scheduler.cron
   :members:

Run records
-----------

.. automodule:: automation_file.scheduler.runs
   :members:

Runtime
-------

.. automodule:: automation_file.scheduler.dispatch
   :members:

.. automodule:: automation_file.scheduler.targets
   :members:

Exceptions
----------

.. automodule:: automation_file.scheduler.errors
   :members:
