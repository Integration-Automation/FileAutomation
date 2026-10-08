Universal storage layer
=======================

The application API (``File``, ``Storage``), the backend contract
(``StorageBackend``), the URI syntax and the resolver. Usage and the full
contract are described in the manual chapter *Universal Storage Layer*.

File and Storage
----------------

.. automodule:: automation_file.storage.file
   :members:

.. automodule:: automation_file.storage.storage
   :members:

Actions
-------

.. automodule:: automation_file.storage.actions
   :members:

Streams and directory trees
---------------------------

.. automodule:: automation_file.storage.tree
   :members:

.. automodule:: automation_file.storage.streams
   :members:

Storage URIs
------------

.. automodule:: automation_file.storage.uri
   :members:

Backend contract
----------------

.. automodule:: automation_file.storage.backend
   :members:
   :private-members: _stat, _list_dir, _upload, _download, _delete_file, _mkdir, _rmdir, _walk, _copy_from, _move_from, _checksum, _read_bytes

.. automodule:: automation_file.storage.types
   :members:

Resolver
--------

.. automodule:: automation_file.storage.resolver
   :members:

Built-in backends
-----------------

.. automodule:: automation_file.storage.local_storage
   :members:

.. automodule:: automation_file.storage.memory_storage
   :members:

Object stores
-------------

.. automodule:: automation_file.storage.object_storage
   :members:
   :private-members: _head, _scan, _put, _get, _remove

.. automodule:: automation_file.storage.s3_storage
   :members:

.. automodule:: automation_file.storage.azure_storage
   :members:
