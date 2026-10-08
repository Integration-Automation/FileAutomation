配置文件与机密 provider
=======================

把通知 sink 与默认值集中声明在一份 TOML 文件里。
机密引用在加载时从环境变量或文件根目录（Docker / K8s 风格）解析：

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

   from automation_file import AutomationConfig, notification_manager, notification_router

   config = AutomationConfig.load("automation_file.toml")
   config.apply_to(notification_manager, notification_router)

``apply_to`` 会注册各个 sink。同时传入路由器时，也会应用 ``[[notify.routes]]``
表格，并在文件声明了路由时启动路由器（见 :doc:`notifications`）；没有传入时，
路由只会被验证而不会应用。

未解析的 ``${…}`` 引用会抛出
:class:`~automation_file.SecretNotFoundException`，
而不是悄悄变成空字符串。需要自定义 provider 链时，可以使用
:class:`~automation_file.ChainedSecretProvider` /
:class:`~automation_file.EnvSecretProvider` /
:class:`~automation_file.FileSecretProvider`，
并通过 ``AutomationConfig.load(path, provider=…)`` 传入。
