公開 API 與相容性
==================

本頁說明哪些東西可以依賴、版本號碼如何告訴你改了什麼，以及一個名稱如何退場。
這是 1.0 版背後的契約。

哪些是公開的
------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - 介面
     - 涵蓋範圍
   * - Python 名稱
     - ``automation_file.__all__`` 中的所有名稱，以及下列已寫入文件的套件其
       ``__all__`` 中的所有名稱：``automation_file.storage``、
       ``automation_file.events``、``automation_file.pipeline``、
       ``automation_file.integrity``、``automation_file.audit``、
       ``automation_file.notify``、``automation_file.scheduler``。這包含名稱本身、
       它的參數、回傳值，以及文件中記載的例外。
   * - 動作
     - 每一個 ``FA_*`` 動作的名稱、參數與結果的形狀。今天寫下的動作清單之後仍然能執行。
   * - 命令列
     - ``python -m automation_file`` 的子指令與旗標、JSON 輸出的形狀，以及結束碼。
   * - 儲存 URI
     - 語法（:doc:`storage`）、內建的 scheme 及其別名。
   * - 資料格式
     - 管線定義（``schema_version: 1``）、完整性 manifest（``schema_version: 2``）、
       稽核紀錄及其 SQLite 結構（第 2 版）、設定檔。
   * - 事件
     - 每一種核心事件的類型名稱（``pipeline.failed`` 等）、嚴重程度與 payload 的鍵
       （:doc:`event_bus`）。
   * - 例外
     - ``FileAutomationException`` 之下的階層：一個錯誤屬於哪個類別，以及它繼承自
       哪些類別。
   * - 擴充點
     - ``StorageBackend`` 子類別要覆寫的方法，``AuditStore``、``RunStore`` 與
       ``NotificationSink`` 介面，以及 ``automation_file.actions`` 進入點。

哪些不是公開的
--------------

* 任何模組中以底線開頭的名稱。
* 公開名稱所在的模組。請從 ``automation_file`` 或 ``automation_file.storage`` 匯入
  ``S3Storage``；``automation_file.storage.s3_storage`` 這個路徑可能會變。
* 錯誤訊息與日誌的確切文字。請依賴例外類別與它的屬性。
* GUI 的 widget 類別。
* ``tests/`` 之下的一切，包含各種替身。儲存契約測試套件
  （``tests/storage_contract.py``）是提供給後端作者使用的，但它是測試程式碼，
  隨著儲存庫而不是隨著套件發行版本演進。

穩定等級
--------

穩定（Stable）
    受以下所有規則保障。自 1.0 起包含：``StorageBackend`` 與儲存 URI 語法、
    ``File`` 與 ``Storage``、``Pipeline`` 及其定義格式、``IntegrityMonitor`` 及其
    manifest、事件模型、稽核紀錄與 ``AuditStore``、``FA_*`` 動作，以及命令列。

暫定（Provisional）
    新功能，仍可能在次版本中變動，變動會列在版本說明中。暫定的功能會在其手冊頁面
    開頭標示。在 1.0 之前，儲存層、事件匯流排、管線執行環境、完整性監控、稽核軌跡、
    通知路由器與語意化 MCP 工具都屬於暫定。

私有（Private）
    `哪些不是公開的`_ 列出的一切。它們會在沒有通知的情況下變動。

版本號碼
--------

版本採用語意化版本，``MAJOR.MINOR.PATCH``。

.. list-table::
   :header-rows: 1
   :widths: 16 84

   * - 部分
     - 何時遞增
   * - ``PATCH``
     - 修正錯誤。沒有任何公開的東西被新增、移除或改變意義。
   * - ``MINOR``
     - 新增功能、暫定功能有所變動，或有東西被標為棄用。為前一個次版本寫的程式仍然
       能運作。
   * - ``MAJOR``
     - 穩定的東西被移除，或以既有程式能察覺的方式改變。版本說明會附上遷移指南。

有兩種情況各值得一句話。**安全性修正** 可以在修訂版中改變行為，只要保留原行為就等於
保留漏洞；版本說明會註明。而 **0.x 版** 還在契約之前：下一個次版本可以改動任何東西，
不過 ``FA_*`` 動作一路以來都維持相容。

支援的 Python 版本是上游仍提供安全性修正的 CPython 版本。停止支援已到生命週期終點的
版本屬於次版本變動。

名稱如何退場
------------

1. 某個次版本把名稱標為棄用。它的運作與以往完全相同，每次使用都會發出
   ``DeprecationWarning``，說明它在哪個版本被棄用、哪個版本會移除，以及替代方案。
   同一則訊息在每個行程中也會寫入日誌一次，因為 Python 在 ``__main__`` 之外會隱藏
   這種警告，而由 JSON 執行的動作清單永遠看不到它。被棄用的 ``FA_*`` 動作仍然保持
   註冊。
2. 手冊與版本說明會列出它以及替代方案。
3. 它至少保留兩個次版本。
4. 只有主版本才會移除它。

整個程式庫都用同一種方式發出這個警告：

.. code-block:: python

   from automation_file.core.deprecation import deprecated, warn_deprecated

   @deprecated(since="1.2", removal="2.0", replacement="automation_file.File.copy_to")
   def copy_between(source, target):
       ...

   def start(self, *, legacy_flag=None):
       if legacy_flag is not None:
           warn_deprecated("the 'legacy_flag' argument", since="1.2", removal="2.0")

要找出你自己的程式用到哪些已棄用的名稱，請把警告當成錯誤來執行測試::

   python -W error::DeprecationWarning -m pytest

撰寫本文時沒有任何東西被棄用。已有較新對應物的舊介面（``copy_between`` 與
``File.copy_to``、``AuditLog`` 與稽核軌跡、``execute_action_dag`` 與 ``Pipeline``）
全部並行支援。

資料格式
--------

寫入磁碟的格式都帶有版本，讀取端遇到不認識的版本會直接拒絕而不是猜測：
``schema_version: 3`` 的 manifest 目前會拋出 ``IntegrityException``，
``schema_version`` 不明的管線定義會由 ``validate_definition`` 回報。當某個格式推出新
版本時，引入它的那個發行版本仍然讀得懂前一個版本，並說明如何轉換。

發生問題時
----------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - 你看到的
     - 代表什麼、該怎麼做
   * - ``DeprecationWarning: … is deprecated since 1.2 and will be removed in 2.0; use … instead``
     - 這個名稱仍然可用。請在訊息所說的版本之前改用替代方案。
   * - 升級後某個模組路徑的匯入失敗
     - 那個路徑不是公開的。請從 ``automation_file`` 或它已寫入文件的套件匯入該名稱。
   * - 升級後，一個比對錯誤訊息的測試失敗
     - 訊息文字不屬於契約。請比對例外類別，或只比對你真正依賴的部分。
   * - ``… has manifest schema version 3``
     - 這個檔案是由較新的版本寫出的。請升級讀取它的套件。
