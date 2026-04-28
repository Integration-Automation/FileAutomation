Local file operations
=====================

Path safety
-----------

.. code-block:: python

   from automation_file import safe_join

   target = safe_join("/data/jobs", user_supplied_path)
   # -> raises PathTraversalException if the resolved path escapes /data/jobs.

Always resolve user-supplied paths through
:func:`~automation_file.local.safe_paths.safe_join` (or the ``is_within``
check). Naive concatenation + ``Path.resolve()`` is bypassed by symlinks and
``..`` segments.

Fast file search
----------------

:func:`~automation_file.fast_find` picks the cheapest backend available on
the host — OS index first, streaming scandir walk as a fallback — so large
trees are searched with minimal energy:

* macOS: ``mdfind`` (Spotlight)
* Linux: ``plocate`` / ``locate`` database
* Windows: Everything's ``es.exe`` CLI, if installed
* Fallback: ``os.scandir`` generator with ``fnmatch`` matching and early
  termination via ``limit=``

.. code-block:: python

   from automation_file import fast_find, scandir_find, has_os_index

   # Query an indexer when available, fall back to scandir otherwise.
   results = fast_find("/var/log", "*.log", limit=100)

   # Force the portable path (skip the OS indexer).
   results = fast_find("/data", "report_*.csv", use_index=False)

   # Streaming generator — stop early without scanning the whole tree.
   for path in scandir_find("/data", "*.csv"):
       if "2026" in path:
           break

   # Which indexer will fast_find try?  Returns "mdfind" / "locate" /
   # "plocate" / "es" / None.
   has_os_index()

JSON form: ``[["FA_fast_find", {"root": "/var/log", "pattern": "*.log",
"limit": 50}]]``.

Checksums and verification
--------------------------

Hash any file with a streaming reader (any :mod:`hashlib` algorithm) and
verify against an expected digest with constant-time comparison:

.. code-block:: python

   from automation_file import file_checksum, verify_checksum

   digest = file_checksum("bundle.tar.gz")                 # sha256 by default
   verify_checksum("bundle.tar.gz", digest)                # -> True
   verify_checksum("bundle.tar.gz", "deadbeef...", algorithm="blake2b")

JSON forms: ``FA_file_checksum`` / ``FA_verify_checksum``.

File deduplication
------------------

:func:`~automation_file.find_duplicates` walks a tree once with
``os.scandir`` and runs a three-stage size → partial-hash → full-hash
pipeline. Files with unique sizes are eliminated without being hashed at
all, so a tree of millions of files is cheap to scan:

.. code-block:: python

   from automation_file import find_duplicates

   groups = find_duplicates("/data", min_size=1024)
   # groups: list[list[str]], each inner list is a set of identical files
   # sorted by size descending.

JSON form: ``FA_find_duplicates``.

Incremental directory sync
--------------------------

:func:`~automation_file.sync_dir` mirrors ``src`` into ``dst`` by copying
only files that are new or changed. Change detection is ``(size, mtime)``
by default; pass ``compare="checksum"`` when mtime is unreliable. Extras
under ``dst`` are left alone unless ``delete=True`` is passed; preview
with ``dry_run=True``:

.. code-block:: python

   from automation_file import sync_dir

   summary = sync_dir("/data/src", "/data/dst", delete=True)
   # summary: {"copied": [...], "skipped": [...], "deleted": [...],
   #           "errors": [...], "dry_run": False}

Symlinks are re-created as symlinks rather than followed. JSON form:
``FA_sync_dir``.

Directory manifests
-------------------

Write a JSON manifest of every file under a tree and verify the tree
hasn't changed later. Useful for release-artifact verification, backup
integrity checks, and pre-flight checks before moves:

.. code-block:: python

   from automation_file import write_manifest, verify_manifest

   write_manifest("/release/payload", "/release/MANIFEST.json")

   # Later…
   result = verify_manifest("/release/payload", "/release/MANIFEST.json")
   if not result["ok"]:
       raise SystemExit(f"manifest mismatch: {result}")

``result`` reports ``matched``, ``missing``, ``modified``, and ``extra``
lists separately. Extras do not fail verification (mirrors ``sync_dir``'s
non-deleting default); ``missing`` or ``modified`` do. JSON forms:
``FA_write_manifest`` / ``FA_verify_manifest``.
