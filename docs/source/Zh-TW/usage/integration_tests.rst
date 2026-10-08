整合測試
========

單元測試為每個儲存後端準備了服務的替身。整合測試則把同一套契約測試
（``tests/storage_contract.py``，88 個案例）拿去對真正的服務執行：S3 用 S3Mock、
Azure Blob 用 Azurite、SFTP 用 OpenSSH 伺服器，另外還有 FTP、WebDAV 與 Samba 伺服器。
這些測試放在 ``tests/integration/``。

除非你把它們指向某個服務，否則它們會被略過，因此不論有沒有這些測試，
``python -m pytest tests/`` 的行為都一樣。

在本機執行其中一個
------------------

安裝 Docker 之後，用一支腳本就能在容器中啟動服務，並印出該測試模組要讀取的變數：

.. code-block:: bash

   eval "$(bash tests/integration/start_service.sh s3)"
   python -m pytest tests/integration/test_s3_minio.py -v
   docker rm -f fa-it-s3

參數可以是 ``s3``、``azure``、``sftp``、``ftp``、``webdav`` 或 ``smb``。腳本會為這一次
執行產生密碼或金鑰，不會儲存任何東西。若要對你自己的服務測試，請改為自行設定這些變數。

變數
----

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - 模組
     - 變數
   * - ``test_s3_minio.py``
     - ``FA_IT_S3_ENDPOINT``、``FA_IT_S3_ACCESS_KEY``、``FA_IT_S3_SECRET_KEY``；
       選用 ``FA_IT_S3_REGION``（``us-east-1``）
   * - ``test_azure_azurite.py``
     - ``FA_IT_AZURE_CONNECTION_STRING``
   * - ``test_sftp_openssh.py``
     - ``FA_IT_SFTP_HOST``、``FA_IT_SFTP_USER``、``FA_IT_SFTP_PASSWORD``、
       ``FA_IT_SFTP_KNOWN_HOSTS``（內含伺服器主機金鑰的檔案；未知的主機會被拒絕）；
       選用 ``FA_IT_SFTP_PORT``（``22``）、``FA_IT_SFTP_ROOT``（``/upload``）
   * - ``test_ftp_server.py``
     - ``FA_IT_FTP_HOST``、``FA_IT_FTP_USER``、``FA_IT_FTP_PASSWORD``；選用
       ``FA_IT_FTP_PORT``（``21``）、``FA_IT_FTP_ROOT``（``/``）、``FA_IT_FTP_TLS``
       （``1`` 代表 FTPS）
   * - ``test_webdav_server.py``
     - ``FA_IT_WEBDAV_URL``、``FA_IT_WEBDAV_USER``、``FA_IT_WEBDAV_PASSWORD``
   * - ``test_smb_samba.py``
     - ``FA_IT_SMB_SERVER``、``FA_IT_SMB_SHARE``、``FA_IT_SMB_USER``、
       ``FA_IT_SMB_PASSWORD``；選用 ``FA_IT_SMB_PORT``（``445``）、
       ``FA_IT_SMB_ENCRYPT``（``1``）

第一個變數沒有設定的模組會被略過。設定 ``FA_IT_REQUIRED=1`` 時則改為失敗，CI 就是用
這個方式確保工作不是靠著略過所有測試而通過。

每個測試都在自己專屬、名稱隨機的 bucket、container 或目錄中運作，結束後會把它移除。
即使如此，仍請把測試指向一個你承擔得起寫入的帳號。

在 CI 中
--------

``.github/workflows/integration.yml`` 會在每個 pull request、每次推送到 ``dev``、每晚
以及手動觸發時執行。其中的 ``services`` 工作會用同一支腳本，為矩陣中的每個項目啟動一個
服務，並執行該服務的模組。``platforms`` 工作則在 Linux 與 macOS 上執行單元測試；
Windows 由主要流程的 ``pytest`` 工作負責。兩者都不會阻擋發行。

Google Drive、OneDrive 與 Dropbox 沒有模擬器，因此只由它們的替身涵蓋。若要對真正的
服務檢查其中之一，請依同樣的模式撰寫模組：先檢查變數，再寫一個 ``StorageContract``
子類別，讓它的 ``backend`` fixture 產生以某個暫存資料夾為根目錄的轉接器。

新增後端
--------

新的後端會附上一個針對替身的契約類別（:doc:`storage` 的「撰寫後端」），而且只要它的
服務能在容器中執行，就會在這裡附上一個模組，並在腳本與流程矩陣中各加上一個項目。

發生問題時
----------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - 你看到的
     - 代表什麼、該怎麼做
   * - ``SKIPPED … set FA_IT_S3_ENDPOINT to run against an S3 service``
     - 這個模組的變數沒有設定。請用腳本啟動服務，或自行設定變數。
   * - ``FA_IT_REQUIRED is set, but FA_IT_… is not``
     - 目前是 CI 模式，而服務沒有啟動，或沒有匯出它的變數。請查看「Start the service」
       步驟，以及失敗後印出的服務日誌。
   * - ``nothing is listening on 127.0.0.1:<port>``
     - 容器在 90 秒內沒有啟動完成。腳本會印出 ``docker ps -a`` 與該容器的日誌。
   * - 每個測試都出現 ``StorageUnavailableException``
     - 服務連得到，但拒絕了憑證；或者以 SFTP 而言，它的主機金鑰不在 known-hosts 檔案中。
