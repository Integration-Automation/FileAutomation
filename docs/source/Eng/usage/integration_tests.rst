Integration tests
=================

The unit tests give every storage backend a stand-in for its service. The
integration tests run the same contract suite (``tests/storage_contract.py``, 88
cases) against a real one: MinIO for S3, Azurite for Azure Blob, an OpenSSH server
for SFTP, and an FTP, a WebDAV and a Samba server. They live in
``tests/integration/``.

They are skipped unless you point them at a service, so ``python -m pytest tests/``
behaves the same with and without them.

Running one locally
-------------------

With Docker installed, one script starts a service in a container and prints the
variables its test module reads:

.. code-block:: bash

   eval "$(bash tests/integration/start_service.sh s3)"
   python -m pytest tests/integration/test_s3_minio.py -v
   docker rm -f fa-it-s3

The argument is ``s3``, ``azure``, ``sftp``, ``ftp``, ``webdav`` or ``smb``. The
script generates the password or key for that run and stores nothing. To test
against a service of your own, set the variables yourself instead.

Variables
---------

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Module
     - Variables
   * - ``test_s3_minio.py``
     - ``FA_IT_S3_ENDPOINT``, ``FA_IT_S3_ACCESS_KEY``, ``FA_IT_S3_SECRET_KEY``;
       optional ``FA_IT_S3_REGION`` (``us-east-1``)
   * - ``test_azure_azurite.py``
     - ``FA_IT_AZURE_CONNECTION_STRING``
   * - ``test_sftp_openssh.py``
     - ``FA_IT_SFTP_HOST``, ``FA_IT_SFTP_USER``, ``FA_IT_SFTP_PASSWORD``,
       ``FA_IT_SFTP_KNOWN_HOSTS`` (a file with the server's host key; an unknown
       host is rejected); optional ``FA_IT_SFTP_PORT`` (``22``),
       ``FA_IT_SFTP_ROOT`` (``/upload``)
   * - ``test_ftp_server.py``
     - ``FA_IT_FTP_HOST``, ``FA_IT_FTP_USER``, ``FA_IT_FTP_PASSWORD``; optional
       ``FA_IT_FTP_PORT`` (``21``), ``FA_IT_FTP_ROOT`` (``/``), ``FA_IT_FTP_TLS``
       (``1`` for FTPS)
   * - ``test_webdav_server.py``
     - ``FA_IT_WEBDAV_URL``, ``FA_IT_WEBDAV_USER``, ``FA_IT_WEBDAV_PASSWORD``
   * - ``test_smb_samba.py``
     - ``FA_IT_SMB_SERVER``, ``FA_IT_SMB_SHARE``, ``FA_IT_SMB_USER``,
       ``FA_IT_SMB_PASSWORD``; optional ``FA_IT_SMB_PORT`` (``445``),
       ``FA_IT_SMB_ENCRYPT`` (``1``)

A module whose first variable is not set is skipped. With ``FA_IT_REQUIRED=1`` it
fails instead, which is how CI makes sure a job did not pass by skipping
everything.

Each test works in a bucket, a container or a directory of its own with a random
name, and removes it afterwards. Point the tests at an account you can afford to
write to all the same.

In CI
-----

``.github/workflows/integration.yml`` runs on every pull request, on pushes to
``dev``, nightly and on demand. Its ``services`` job starts one service per matrix
entry with the same script and runs that service's module. Its ``platforms`` job
runs the unit tests on Linux and macOS; the ``pytest`` job of the main workflow
covers Windows. Neither gates a release.

Google Drive, OneDrive and Dropbox have no emulator, so they are covered by their
stand-ins only. To check one of them against the real service, write a module on
the same pattern: a guard on its variables, then a ``StorageContract`` subclass
whose ``backend`` fixture yields the adapter rooted in a scratch folder.

Adding a backend
----------------

A new backend ships with a contract class against a stand-in (:doc:`storage`,
"Writing a backend"), and, where its service can run in a container, with a module
here and an entry in the script and in the workflow matrix.

When something goes wrong
-------------------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - What you see
     - What it means and what to do
   * - ``SKIPPED … set FA_IT_S3_ENDPOINT to run against an S3 service``
     - The module's variables are not set. Start the service with the script, or
       set them.
   * - ``FA_IT_REQUIRED is set, but FA_IT_… is not``
     - CI mode, and the service did not start or did not export its variables.
       Read the "Start the service" step and the service log printed after a
       failure.
   * - ``nothing is listening on 127.0.0.1:<port>``
     - The container did not come up within 90 seconds. The script prints
       ``docker ps -a`` and the container's log.
   * - ``StorageUnavailableException`` in every test
     - The service is reachable but refused the credentials, or, for SFTP, its
       host key is not in the known-hosts file.
