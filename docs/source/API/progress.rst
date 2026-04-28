Progress + cancellation
=======================

Opt-in transfer instrumentation. Pass ``progress_name="<label>"`` to
:func:`~automation_file.download_file`, :func:`s3_upload_file`, or
:func:`s3_download_file` and the transfer registers with the shared
:data:`~automation_file.core.progress.progress_registry`. From there the GUI
or a JSON action can poll the reporter snapshot or cancel the transfer
mid-flight.

.. automodule:: automation_file.core.progress
   :members:
