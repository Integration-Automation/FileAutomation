Plugins and dynamic registration
================================

Entry-point plugins
-------------------

Third-party packages can register their own ``FA_*`` commands by
declaring an ``automation_file.actions`` entry point in their
``pyproject.toml``::

   [project.entry-points."automation_file.actions"]
   my_plugin = "my_plugin:register"

where ``register`` is a zero-argument callable returning a
``Mapping[str, Callable]``. Once the plugin is installed into the same
virtual environment,
:func:`~automation_file.core.action_registry.build_default_registry`
picks it up automatically — no caller changes required:

.. code-block:: python

   # my_plugin/__init__.py
   def greet(name: str) -> str:
       return f"hello {name}"

   def register() -> dict:
       return {"FA_greet": greet}

.. code-block:: python

   # consumer code, after `pip install my_plugin`
   from automation_file import execute_action
   execute_action([["FA_greet", {"name": "world"}]])

Plugin failures (import errors, factory exceptions, wrong return shape,
registry rejection) are logged and swallowed so one broken plugin cannot
break the library.

Dynamic package registration
----------------------------

.. code-block:: python

   from automation_file import package_manager, execute_action

   package_manager.add_package_to_executor("math")
   execute_action([["math_sqrt", [16.0]]])   # -> 4.0

.. warning::

   ``package_manager.add_package_to_executor`` effectively registers every
   top-level function / class / builtin of a package. Do not expose it to
   untrusted input (e.g. via the TCP, HTTP, or :doc:`mcp` servers).
