Architecture
============

``automation_file`` follows a layered architecture built around four design
patterns:

**Facade**
   :mod:`automation_file` (the top-level ``__init__``) is the only name users
   should need to import. Every public function and singleton is re-exported
   from there.

**Registry + Command**
   :class:`~automation_file.core.action_registry.ActionRegistry` maps an action
   name (a string that appears in a JSON action list) to a Python callable.
   An action is a Command object of shape ``[name]``, ``[name, {kwargs}]``, or
   ``[name, [args]]``.

**Template Method**
   :class:`~automation_file.core.action_executor.ActionExecutor` defines the
   single-action lifecycle: resolve the name, dispatch the call, capture the
   return value or exception. The outer iteration template guarantees that one
   bad action never aborts the batch.

**Strategy**
   ``local/*_ops.py`` and ``remote/google_drive/*_ops.py`` modules are
   collections of independent strategy functions. Each module plugs into the
   shared registry via :func:`automation_file.core.action_registry.build_default_registry`.

Module layout
-------------

.. code-block:: text

   automation_file/
   ├── __init__.py           # Facade
   ├── __main__.py           # CLI
   ├── exceptions.py         # FileAutomationException hierarchy
   ├── logging_config.py     # file_automation_logger
   ├── core/
   │   ├── action_registry.py
   │   ├── action_executor.py
   │   ├── callback_executor.py
   │   ├── package_loader.py
   │   └── json_store.py
   ├── local/
   │   ├── file_ops.py
   │   ├── dir_ops.py
   │   └── zip_ops.py
   ├── remote/
   │   ├── url_validator.py  # SSRF guard
   │   ├── http_download.py
   │   └── google_drive/
   │       ├── client.py     # GoogleDriveClient (Singleton Facade)
   │       ├── delete_ops.py
   │       ├── download_ops.py
   │       ├── folder_ops.py
   │       ├── search_ops.py
   │       ├── share_ops.py
   │       └── upload_ops.py
   ├── server/
   │   └── tcp_server.py     # Loopback-only action server
   ├── project/
   │   ├── project_builder.py
   │   └── templates.py
   └── utils/
       └── file_discovery.py

Shared singletons
-----------------

``automation_file`` creates three process-wide singletons in
``automation_file/__init__.py``:

* ``executor`` — the default :class:`ActionExecutor` used by
  :func:`execute_action`.
* ``callback_executor`` — a :class:`CallbackExecutor` bound to
  ``executor.registry``.
* ``package_manager`` — a :class:`PackageLoader` bound to the same registry.

All three share a single :class:`ActionRegistry` instance, so calling
:func:`add_command_to_executor` makes the new command visible to every
dispatcher at once.

Security boundaries
-------------------

* All outbound HTTP URLs pass through
  :func:`automation_file.remote.url_validator.validate_http_url`.
* :class:`automation_file.server.tcp_server.TCPActionServer` binds to loopback
  by default and refuses non-loopback binds unless the caller passes
  ``allow_non_loopback=True`` explicitly.
* :class:`automation_file.core.package_loader.PackageLoader` registers
  arbitrary module members; it must never be exposed to untrusted clients.
