Cloud and SFTP backends
=======================

Every backend (Google Drive, S3, Azure Blob, Dropbox, SFTP) is bundled
with ``automation_file`` and auto-registered by
:func:`~automation_file.core.action_registry.build_default_registry`.
There is no extra install step — call ``later_init`` on the singleton and go:

.. code-block:: python

   from automation_file import execute_action, s3_instance

   s3_instance.later_init(region_name="us-east-1")

   execute_action([
       ["FA_s3_upload_file", {"local_path": "report.csv",
                              "bucket": "reports", "key": "report.csv"}],
   ])

All backends expose the same five operations: ``upload_file``,
``upload_dir``, ``download_file``, ``delete_*``, ``list_*``.
``register_<backend>_ops(registry)`` is still public for callers that build
custom registries.

Google Drive
------------

.. code-block:: python

   from automation_file import driver_instance, drive_upload_to_drive

   driver_instance.later_init("token.json", "credentials.json")
   drive_upload_to_drive("example.txt")

OAuth credentials live on disk at the caller-supplied ``token_path``
(UTF-8). Never log or print the file contents.

SFTP
----

:class:`~automation_file.SFTPClient` uses :class:`paramiko.RejectPolicy`
— unknown hosts are rejected rather than auto-added. Provide
``known_hosts=`` explicitly or rely on ``~/.ssh/known_hosts``. Do not
swap in ``AutoAddPolicy`` for convenience.

Cross-backend copy
------------------

The cross-backend dispatcher accepts URI syntax for every backend:

.. code-block:: python

   from automation_file import execute_action

   execute_action([
       ["FA_cross_copy",
        {"src": "s3://reports/2026-04.csv",
         "dst": "drive:///Backups/april.csv"}],
   ])

URI prefixes: ``local://``, ``s3://``, ``drive://``, ``sftp://``,
``azure://``, ``dropbox://``, ``ftp://``.
