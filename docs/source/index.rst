automation_file
===============

Automation-first Python library for local file / directory / zip operations,
HTTP downloads, and Google Drive integration. Actions are defined as JSON and
dispatched through a central :class:`~automation_file.core.action_registry.ActionRegistry`.

Getting started
---------------

Install from PyPI and run a JSON action list:

.. code-block:: bash

   pip install automation_file
   python -m automation_file --execute_file my_actions.json

Or drive the library directly from Python:

.. code-block:: python

   from automation_file import execute_action

   execute_action([
       ["FA_create_dir", {"dir_path": "build"}],
       ["FA_create_file", {"file_path": "build/hello.txt", "content": "hi"}],
   ])

.. toctree::
   :maxdepth: 2
   :caption: Contents

   architecture
   usage
   api/index

Indices
-------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
