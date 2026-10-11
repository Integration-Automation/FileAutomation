Triggers and scheduler
======================

File-watcher triggers
---------------------

Run an action list whenever a filesystem event fires on a watched path. The
module-level :data:`~automation_file.trigger.trigger_manager` keeps a named
registry of active watchers so the JSON facade and the GUI share one
lifecycle.

.. code-block:: python

   from automation_file import watch_start, watch_stop

   watch_start(
       name="inbox-sweeper",
       path="/data/inbox",
       action_list=[["FA_copy_all_file_to_dir",
                     {"source_dir": "/data/inbox",
                      "target_dir": "/data/processed"}]],
       events=["created", "modified"],
       recursive=False,
   )
   # later:
   watch_stop("inbox-sweeper")

Or drive it from a JSON action list with ``FA_watch_start`` /
``FA_watch_stop`` / ``FA_watch_stop_all`` / ``FA_watch_list``.

Scheduler
---------

Running an action list or a pipeline on a cron expression with a time zone, on
a file event, on an event from the bus, after another pipeline or by hand is
described in :doc:`scheduler`, together with the run records, overlap
protection, timeouts and the ``FA_schedule_*`` actions. A job that should run on
a file event and leave a record of every run uses the scheduler's
``FileTrigger`` instead of ``FA_watch_start``.

A watcher calls
:func:`~automation_file.notify.manager.notify_on_failure` when its action
list raises :class:`~automation_file.exceptions.FileAutomationException`.
The helper is a no-op when no sinks are registered, so auto-notification
is an opt-in side effect of registering any
:class:`~automation_file.NotificationSink` — see :doc:`notifications`. The
scheduler does the same for an action list it cannot dispatch, and publishes
every other failed run as a ``scheduler.error`` event.
