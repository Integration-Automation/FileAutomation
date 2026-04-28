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

Cron scheduler
--------------

Run an action list on a recurring schedule. The 5-field cron parser supports
``*``, exact values, ``a-b`` ranges, comma-separated lists, and ``*/n`` step
syntax with ``jan``..``dec`` / ``sun``..``sat`` aliases.

.. code-block:: python

   from automation_file import schedule_add

   schedule_add(
       name="nightly-snapshot",
       cron_expression="0 2 * * *",           # every day at 02:00 local time
       action_list=[["FA_zip_dir", {"dir_we_want_to_zip": "/data",
                                    "zip_name": "/backup/data_nightly"}]],
   )

A background thread wakes on minute boundaries, so expressions with
sub-minute precision are not supported. JSON forms: ``FA_schedule_add`` /
``FA_schedule_remove`` / ``FA_schedule_remove_all`` / ``FA_schedule_list``.

Both dispatchers call
:func:`~automation_file.notify.manager.notify_on_failure` when an action
list raises :class:`~automation_file.exceptions.FileAutomationException`.
The helper is a no-op when no sinks are registered, so auto-notification
is an opt-in side effect of registering any
:class:`~automation_file.NotificationSink` — see :doc:`notifications`.
