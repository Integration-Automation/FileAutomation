HTTP transfers
==============

Resumable HTTP downloads
------------------------

:func:`~automation_file.download_file` accepts ``resume=True``. Bytes are
written to ``<target>.part``; if the tempfile already exists the next call
sends ``Range: bytes=<n>-`` so the transfer picks up where it left off.
Combined with ``expected_sha256=`` the download is verified immediately
after the last chunk is written:

.. code-block:: python

   from automation_file import download_file

   download_file(
       "https://example.com/big.bin",
       "big.bin",
       resume=True,
       expected_sha256="3b0c44298fc1...",
   )

Every URL passes through
:func:`~automation_file.remote.url_validator.validate_http_url`, blocking
``file://`` / ``ftp://`` / ``data:`` schemes and IPs in private, loopback,
link-local, reserved, multicast, or unspecified ranges. Default 20 MB
response cap and 15 s connection timeout. TLS verification is never
disabled.

Transfer progress and cancellation
----------------------------------

Pass ``progress_name="<label>"`` to :func:`download_file`,
:func:`s3_upload_file`, or :func:`s3_download_file` to register the transfer
with the shared progress registry. The GUI's **Progress** tab polls the
registry every half second; ``FA_progress_list``, ``FA_progress_cancel``,
and ``FA_progress_clear`` give JSON action lists the same view.

.. code-block:: python

   from automation_file import download_file, progress_cancel

   # In one thread:
   download_file("https://example.com/big.bin", "big.bin",
                 progress_name="big-download")

   # In another thread / from the GUI:
   progress_cancel("big-download")

Cancellation raises :class:`~automation_file.CancelledException` inside the
transfer loop. The transfer function catches it, marks the reporter
``status="cancelled"``, and returns ``False`` — callers don't need to handle
the exception themselves.
