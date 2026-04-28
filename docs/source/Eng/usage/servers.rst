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
