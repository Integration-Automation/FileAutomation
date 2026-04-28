Config file and secret providers
================================

Declare notification sinks and defaults once in a TOML file. Secret
references resolve at load time from environment variables or a file
root (Docker / K8s style):

.. code-block:: toml

   # automation_file.toml

   [secrets]
   file_root = "/run/secrets"

   [defaults]
   dedup_seconds = 120

   [[notify.sinks]]
   type = "slack"
   name = "team-alerts"
   webhook_url = "${env:SLACK_WEBHOOK}"

   [[notify.sinks]]
   type = "email"
   name = "ops-email"
   host = "smtp.example.com"
   port = 587
   sender = "alerts@example.com"
   recipients = ["ops@example.com"]
   username = "${env:SMTP_USER}"
   password = "${file:smtp_password}"

.. code-block:: python

   from automation_file import AutomationConfig, notification_manager

   config = AutomationConfig.load("automation_file.toml")
   config.apply_to(notification_manager)

Unresolved ``${…}`` references raise
:class:`~automation_file.SecretNotFoundException` rather than silently
becoming empty strings. Custom provider chains can be built via
:class:`~automation_file.ChainedSecretProvider` /
:class:`~automation_file.EnvSecretProvider` /
:class:`~automation_file.FileSecretProvider` and passed to
``AutomationConfig.load(path, provider=…)``.
