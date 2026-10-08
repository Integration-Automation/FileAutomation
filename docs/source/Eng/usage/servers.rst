Action servers
==============

TCP action server
-----------------

.. code-block:: python

   from automation_file import start_autocontrol_socket_server

   server = start_autocontrol_socket_server(
       host="localhost", port=9943, shared_secret="optional-secret",
   )
   # later:
   server.shutdown()
   server.server_close()

When ``shared_secret`` is supplied the client must prefix each payload with
``AUTH <secret>\n`` before the JSON action list. The server still binds to
loopback by default and refuses non-loopback binds unless
``allow_non_loopback=True`` is passed.

The server accepts a single JSON payload per connection (``recv(8192)``).
Do not raise that limit without also adding a length-framed protocol.

HTTP action server
------------------

.. code-block:: python

   from automation_file import start_http_action_server

   server = start_http_action_server(
       host="127.0.0.1", port=9944, shared_secret="optional-secret",
   )

   # Client side:
   # curl -H 'Authorization: Bearer optional-secret' \
   #      -d '[["FA_create_dir",{"dir_path":"x"}]]' \
   #      http://127.0.0.1:9944/actions

HTTP responses are JSON. Auth failures return ``401``; malformed JSON
returns ``400``; unknown paths return ``404``. Request body capped at
1 MB. Loopback-only by default; ``allow_non_loopback=True`` is required to
bind elsewhere.

The shared secret comparison uses :func:`hmac.compare_digest` (constant
time). Never log the secret or the raw payload.

Web UI
------

A read-only dashboard in the browser, served with the standard library and
HTMX (one script from a pinned CDN URL, with an SRI hash).

.. code-block:: python

   from automation_file import start_web_ui

   server = start_web_ui(host="127.0.0.1", port=9955, shared_secret="optional-secret")
   # Browse http://127.0.0.1:9955/
   # later:
   server.shutdown()
   server.server_close()

The page polls one HTML fragment per section. Every fragment but the transfer
progress is rendered from the application layer (:doc:`app_layer`), the same
services the desktop window (:doc:`gui`) calls, so the two show the same state.

.. list-table::
   :header-rows: 1
   :widths: 22 14 64

   * - Fragment
     - Polled
     - Shows
   * - ``GET /ui/health``
     - 5 s
     - ``ok`` or ``attention`` with the reasons; registered actions, running
       runs, scheduled jobs, monitors, sinks and routes, the audit trail.
   * - ``GET /ui/runs``
     - 3 s
     - Running and recent pipeline runs, and how the newest runs ended.
   * - ``GET /ui/integrity``
     - 10 s
     - Each named integrity monitor and the drift it last found.
   * - ``GET /ui/events``
     - 5 s
     - The latest events of the bus, newest first.
   * - ``GET /ui/storage``
     - 30 s
     - Each storage backend and whether it can be used.
   * - ``GET /ui/audit``
     - 10 s
     - The latest audit records, once ``configure_audit`` gave the trail a
       store.
   * - ``GET /ui/progress``
     - 2 s
     - Live transfers of the progress registry.
   * - ``GET /ui/registry``
     - 30 s
     - The name of every registered action.

``GET /`` and ``GET /index.html`` serve the page; any other path returns
``404``. There is no route that changes anything: run actions through the
action servers above, with their own authentication.

* **Loopback only by default.** ``allow_non_loopback=True`` is required to bind
  elsewhere, and doing so without a ``shared_secret`` logs a warning.
* **Shared secret.** With ``shared_secret``, every request needs
  ``Authorization: Bearer <secret>`` and gets ``401`` without it. The page
  carries the header in ``hx-headers`` so its own polling is authorised; anyone
  who can read the page can therefore read the secret, so serve it over
  loopback or behind TLS.
* **Escaped and masked.** Everything a fragment shows is HTML-escaped, and the
  application layer has already masked tokens, passwords and webhook URLs in
  it.
* **A fragment never breaks the page.** When a service cannot answer, its
  fragment says ``unavailable: <ExceptionType>`` and the others keep working.

``start_web_ui(services=...)`` takes a set built with
``automation_file.app.build_services`` to show another run store, event bus or
resolver than the process-wide ones.
