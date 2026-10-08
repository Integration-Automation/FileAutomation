Public API and compatibility
============================

This page says what you may rely on, how a release number tells you what
changed, and how a name is retired. It is the contract behind the 1.0 release.

What is public
--------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Surface
     - What it covers
   * - Python names
     - Everything in ``automation_file.__all__``, and everything in the
       ``__all__`` of the documented packages: ``automation_file.storage``,
       ``automation_file.events``, ``automation_file.pipeline``,
       ``automation_file.integrity``, ``automation_file.audit``,
       ``automation_file.notify``, ``automation_file.scheduler``. That means
       the name, its parameters, what it returns and the exceptions it
       documents.
   * - Actions
     - Every ``FA_*`` action name, its parameters and the shape of its result.
       An action list written today keeps running.
   * - Command line
     - The subcommands and flags of ``python -m automation_file``, the shape of
       their JSON output and their exit codes.
   * - Storage URIs
     - The syntax (:doc:`storage`), the built-in schemes and their aliases.
   * - Data formats
     - Pipeline definitions (``schema_version: 1``), integrity manifests
       (``schema_version: 2``), the audit record and its SQLite schema
       (version 2), the configuration file.
   * - Events
     - The type name of each core event (``pipeline.failed``, ...), its severity
       and its payload keys (:doc:`event_bus`).
   * - Exceptions
     - The hierarchy below ``FileAutomationException``: which class an error
       is, and which classes it inherits from.
   * - Extension points
     - The methods a ``StorageBackend`` subclass overrides, the ``AuditStore``,
       ``RunStore`` and ``NotificationSink`` interfaces, and the
       ``automation_file.actions`` entry point.

What is not public
------------------

* A name that starts with an underscore, in any module.
* The module a public name lives in. Import ``S3Storage`` from
  ``automation_file`` or ``automation_file.storage``; the path
  ``automation_file.storage.s3_storage`` may change.
* The exact text of an error message and of a log line. Rely on the exception
  class and its attributes.
* The GUI's widget classes.
* Anything under ``tests/``, including the stand-ins. The storage contract suite
  (``tests/storage_contract.py``) is published for backend authors, but it is
  test code and is versioned with the repository, not with the package.

Stability levels
----------------

Stable
    Covered by everything below. From 1.0 on this is: ``StorageBackend`` and
    the storage URI syntax, ``File`` and ``Storage``, ``Pipeline`` and its
    definition format, ``IntegrityMonitor`` and its manifest, the event model,
    the audit record and ``AuditStore``, the ``FA_*`` actions, the command line.

Provisional
    New and still allowed to change in a minor release, with the change listed
    in the release notes. A provisional feature is marked as such at the top of
    its manual page. Until 1.0 the storage layer, the event bus, the pipeline
    runtime, the integrity monitor, the audit trail, the notification router and
    the semantic MCP tools are provisional.

Private
    Everything listed under `What is not public`_. It changes without notice.

Version numbers
---------------

Releases follow semantic versioning, ``MAJOR.MINOR.PATCH``.

.. list-table::
   :header-rows: 1
   :widths: 16 84

   * - Part
     - Goes up when
   * - ``PATCH``
     - A bug is fixed. Nothing public is added, removed or changed in meaning.
   * - ``MINOR``
     - Something is added, a provisional feature changes, or something is
       deprecated. Code written for the previous minor release keeps working.
   * - ``MAJOR``
     - Something stable is removed or changes in a way existing code can
       notice. The release notes carry a migration guide.

Two cases deserve a sentence each. A **security fix** may change behaviour in a
patch release when keeping the behaviour would keep the hole; the release notes
say so. And **0.x releases** are before the contract: the next minor release may
change anything, although the ``FA_*`` actions have been kept compatible
throughout.

Supported Python versions are the CPython releases that still receive security
fixes upstream. Dropping one that has reached its end of life is a minor change.

How a name is retired
---------------------

1. A minor release marks the name as deprecated. It keeps working exactly as
   before, and each use raises a ``DeprecationWarning`` that names the release
   it was deprecated in, the release that will remove it, and its replacement.
   The message is also logged once per process, because Python hides the
   warning outside ``__main__`` and an action list run from JSON would never
   show it. A deprecated ``FA_*`` action stays registered.
2. The manual and the release notes list it, with the replacement.
3. It stays for at least two minor releases.
4. Only a major release removes it.

The warning is written in one way throughout the code base:

.. code-block:: python

   from automation_file.core.deprecation import deprecated, warn_deprecated

   @deprecated(since="1.2", removal="2.0", replacement="automation_file.File.copy_to")
   def copy_between(source, target):
       ...

   def start(self, *, legacy_flag=None):
       if legacy_flag is not None:
           warn_deprecated("the 'legacy_flag' argument", since="1.2", removal="2.0")

To find the deprecated names your own code uses, run your tests with warnings
turned into errors::

   python -W error::DeprecationWarning -m pytest

Nothing is deprecated at the time of writing. The older interfaces that have a
newer counterpart (``copy_between`` and ``File.copy_to``, ``AuditLog`` and the
audit trail, ``execute_action_dag`` and ``Pipeline``) are all supported side by
side.

Data formats
------------

A format that is written to disk carries a version, and a reader refuses a
version it does not know instead of guessing: a manifest with
``schema_version: 3`` raises ``IntegrityException`` today, and a pipeline
definition with an unknown ``schema_version`` is reported by
``validate_definition``. When a format gets a new version, the release that
introduces it still reads the previous one, and says how to convert.

When something goes wrong
-------------------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - What you see
     - What it means and what to do
   * - ``DeprecationWarning: … is deprecated since 1.2 and will be removed in 2.0; use … instead``
     - The name still works. Switch to the replacement before the release the
       message names.
   * - An import of a module path fails after an upgrade
     - The path was not public. Import the name from ``automation_file`` or
       from its documented package.
   * - A test that compared an error message fails after an upgrade
     - Message text is not part of the contract. Compare the exception class,
       or match only the part you depend on.
   * - ``… has manifest schema version 3``
     - The file was written by a newer release. Upgrade the package that reads
       it.
