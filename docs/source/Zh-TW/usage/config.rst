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

   from automation_file import AutomationConfig, notification_manager, notification_router

   config = AutomationConfig.load("automation_file.toml")
   config.apply_to(notification_manager, notification_router)

``apply_to`` 會註冊各個 sink。同時傳入路由器時，也會套用 ``[[notify.routes]]``
表格，並在檔案宣告了路由時啟動路由器（見 :doc:`notifications`）；沒有傳入時，
路由只會被驗證而不會套用。

未解析的 ``${…}`` 參考會擲出
:class:`~automation_file.SecretNotFoundException`，
而不是悄悄變成空字串。需要自訂 provider 鏈時，可使用
:class:`~automation_file.ChainedSecretProvider` /
:class:`~automation_file.EnvSecretProvider` /
:class:`~automation_file.FileSecretProvider`，
並透過 ``AutomationConfig.load(path, provider=…)`` 傳入。
