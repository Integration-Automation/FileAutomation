"""Storage adapters against real services.

Each module here runs the same ``StorageContract`` as the unit tests, but against
a live service (MinIO, Azurite, ...) instead of a stand-in. A module skips as a
whole unless its ``FA_IT_*`` environment variables say where the service is, so a
plain ``pytest tests/`` never needs the network. ``.github/workflows/integration.yml``
starts the services in containers and sets the variables.
"""
