設定檔與機敏資訊 provider
=========================

把通知 sink 與預設值集中宣告在一份 TOML 檔。
機敏資訊參考在載入時從環境變數或檔案根目錄（Docker / K8s 風格）解析：

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

未解析的 ``${…}`` 參考會擲出
:class:`~automation_file.SecretNotFoundException`，
而不是悄悄變成空字串。需要自訂 provider 鏈時，可使用
:class:`~automation_file.ChainedSecretProvider` /
:class:`~automation_file.EnvSecretProvider` /
:class:`~automation_file.FileSecretProvider`，
並透過 ``AutomationConfig.load(path, provider=…)`` 傳入。
