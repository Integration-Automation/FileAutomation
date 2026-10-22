# 程式審核：FileAutomation

## 審核者

- 審核者：工作區程式審核
- 日期：2026-10-22
- 對象：`FileAutomation`（套件 `automation_file`）
- 範圍：工作樹熱點。路徑是否可離開預期目錄、shell、雲端憑證來源、壓縮與解壓路徑穿越、套件閘門。排除 `tests/`、`build/`、`dist/`、`__pycache__/`。
- 結論：需修正

## 審核規範

嚴重度：缺陷＝未關閉且與安全或公開契約不符；建議＝應改但預設路徑尚未直接造成損害；備註＝已核對、不單列發現。通過＝無未關閉缺陷；有條件通過＝無立即損害；需修正＝有未關閉缺陷。

1. 設計：分層、登錄、儲存根目錄與動作伺服器的信任邊界須與 `architecture.md`、`CLAUDE.md` 一致。
2. 可讀性：圈複雜度與認知複雜度 ≤ 15、函式 ≤ 75 行、巢狀 ≤ 4、參數 ≤ 7、檔案 ≤ 1000 行、行寬 ≤ 120。通用上限較鬆時從專案較嚴者。
3. 錯誤處理：禁止裸 `except:`；捕捉須指定型別；不得吞掉例外。
4. 死碼：無未使用、註解掉或呼叫後即失效的公開行為。
5. 型別與 docstring：公開函式的說明須與參數、回傳一致。
6. 安全：路徑須經 `safe_join`／`is_within`；禁止 `shell=True`；禁止對不可信資料 `eval`／`exec`／`pickle`／`yaml.load`；TLS 預設驗證；憑證不得寫進程式、紀錄或畫面。
7. 測試：本次不執行測試。只看熱點是否有對應的防護，以及測試是否可能沒覆蓋到錯誤呼叫方式。
8. 效能：熱點路徑避免無界解壓、無逾時的子程序，以及把遠端檔整份拉回只為了讀中繼資料（`progress.md` #17 仍開放，本次不另開缺陷）。
9. §6：PyBreeze 的 `--execute_str` 雙重解碼、TestPioneer 使用的 `download_file` 與 `unzip_all`、ActionCore 套件閘門設定不得被靜默改掉。
10. 文件同步：`architecture.md`、`CLAUDE.md`、`progress.md` 與熱點程式須一致；行為已變而文件未寫，視同缺口。

## 審核紀錄

### 方法

已讀 `architecture.md`（含 §6、§7）、`CLAUDE.md` 前 80 行及安全與品質章節、`progress.md` 開頭開放項。在 `automation_file` 搜尋 `eval(`、`exec(`、`shell=True`、`pickle`、`yaml.load`、`verify=False`、裸 `except:`、`subprocess`、`extractall`。每一則發現都先讀過對應程式，再寫入。未改其他檔、未執行測試、未連線。

### 發現

#### CR-01 解壓目的目錄被當成成員清單

- 嚴重度：缺陷
- 位置：`automation_file/__main__.py` `_cmd_unzip`（約第 69–70 行）；`automation_file/local/zip_ops.py` `unzip_all`（約第 68–76 行）、`unzip_file`（約第 51–59 行）
- 說明：`unzip_all(zip_file_path, extract_member, extract_path, password)` 的第二個位置參數是要抽出的成員名稱，不是目的目錄。CLI `unzip <archive> <target_dir>` 卻寫成 `unzip_all(args.archive, args.target_dir, password=args.password)`。`ZipFile.extractall` 在 `members` 為字串時會逐字元當成成員名，且 `path` 維持空值，也就是目前工作目錄。標準庫會去掉成員名裡的 `..`、絕對路徑與磁碟機代號（已對照 CPython 3.11 `zipfile._extract_member`），所以這不是經典的 `../` zip slip；但檔案不會進入使用者指定的目錄。若壓縮檔含有與該路徑字元同名的成員，內容會寫入工作目錄。`--password` 來自 argparse，型別是 `str`，而 `zipfile` 要求 `bytes`，有密碼時會在真正寫入前發生 `TypeError`。GUI（`ui/tabs/local_tab.py`）與單元測試以關鍵字 `extract_path=` 呼叫，所以這條錯誤呼叫沒有被擋住。`FA_unzip_file` 與 `FA_unzip_all` 本身也沒有再用 `safe_join` 檢查成員。
- 依據：路徑須留在預期目錄（審核規範第 6 條；`CLAUDE.md` Path traversal）。§6 把 `unzip_all` 列為 TestPioneer 的門面名稱；第二個位置參數的意義與此直覺相反。未讀 TestPioneer 原始碼，不把對方的呼叫方式當成已證實。
- 狀態：未關閉
- 建議：CLI 改為 `unzip_all(args.archive, extract_path=args.target_dir, password=...)`，密碼先編成 `bytes`。`unzip_file`／`unzip_all` 在寫入前用 `safe_join` 檢查每一個成員，不要只依賴標準庫。補一條 CLI 測試，確認檔案只出現在 `target_dir`。

#### CR-02 檔案祕密可讀出宣告的根目錄

- 嚴重度：缺陷
- 位置：`automation_file/core/secrets.py` `FileSecretProvider.get`（約第 67–75 行）
- 說明：`${file:<name>}` 的名稱幾乎沒有限制（`core/secrets.py` 的樣式允許 `}` 以外的字元）。`get` 使用 `self._root / name`，沒有呼叫 `safe_join`。名稱若是 `../` 或絕對路徑，`pathlib` 會離開 `file_root`，讀到的內容會被代進已解析的設定，並當成憑證使用。讀取失敗只記路徑、不記內容，這點是對的；但路徑本身可以逃出預期目錄。
- 依據：對可信根目錄解析外來路徑必須走 `safe_join`（`CLAUDE.md` Path traversal；審核規範第 6 條）。憑證應來自環境變數或呼叫端指定且受約束的路徑。
- 狀態：未關閉
- 建議：`candidate = safe_join(self._root, name)`，讓 `PathTraversalException` 變成找不到祕密或設定錯誤，不要讀取根目錄以外的檔案。拒絕絕對路徑與 `..`。

#### CR-03 SFTP／FTP 的根目錄只是路徑前綴

- 嚴重度：缺陷
- 位置：`automation_file/storage/session_storage.py` `_remote`（約第 168–170 行）；`automation_file/storage/sftp_storage.py` `_stat`（約第 174–179 行）、`_download`（約第 229–231 行）；`automation_file/storage/ftp_storage.py` `_download`（約第 337–339 行）
- 說明：`root=` 經 `absolute_root` 與 `posixpath.join` 接上儲存路徑。`normalize_path` 拒絕 `..` 與 NUL，所以路徑字串本身爬不出去。SFTP 的 `stat` 與 `get` 會跟隨伺服器上的符號連結；FTP 的 `RETR` 也由伺服器解析該名稱。連結若指向根目錄之外，讀寫內容就離開預期目錄。本地 `LocalStorage` 的讀寫會經 `safe_join` 拒絕這種連結，兩邊的根目錄語意不一致。`progress.md` #37(d) 仍把這點列為未完成。
- 依據：審核規範第 6 條（路徑不得離開預期目錄）；`session_storage` 說明此後端服務的是根目錄以下的樹。`sftp_storage` 明文寫著讀寫會跟隨連結，與該約束衝突。
- 狀態：未關閉
- 建議：在 `root` 不是 `/` 時，讀寫前用 `lstat` 拒絕連結，或解析連結目標並確認仍在根目錄之下。FTP 無法可靠辨認連結時，應在文件與能力旗標寫明此根目錄不是沙箱，並避免把它當成 MCP 遠端根的同等約束。控制連線指令雖把路徑拼進 `RETR`／`STOR`，CPython 3.11 的 `ftplib.putline` 會拒絕換行，這次不把指令注入列為缺陷。

#### CR-04 裝置碼登入把存取權杖放進結果與畫面

- 嚴重度：缺陷
- 位置：`automation_file/remote/onedrive/client.py` `device_code_login`（約第 88–97 行）；登錄於 `automation_file/remote/onedrive/__init__.py` 的 `FA_onedrive_device_code_login`；`automation_file/ui/tabs/base.py` `run_action`（約第 52–53 行）；`automation_file/ui/tabs/onedrive_tab.py` `_on_device_code`
- 說明：登入成功後用戶端已自行保存權杖，卻 `return result`，把 MSAL 回傳的整個字典交給呼叫端。程式至少讀取了其中的 `access_token`。`execute_action` 會把這個回傳值放進結果對照表，TCP／HTTP 動作回應也會帶出。進階分頁的 `run_action` 用 `repr` 把同一結果寫進日誌面板。另外，裝置碼流程的 `message`（含使用者代碼）以 INFO 寫入日誌。應用層的 `mask_secrets` 沒有套在這條回傳路徑上。執行器成功時不把回傳值寫入 `file_automation_logger`；失敗時若例外訊息含整個字典，才會被錯誤日誌記到。
- 依據：不得紀錄或顯示權杖（`CLAUDE.md` General rules、Secrets and credentials；審核規範第 6 條）。
- 狀態：未關閉
- 建議：動作與 GUI 只回傳帳號、到期時間等非祕密欄位；權杖只留在用戶端物件。日誌不要寫裝置碼訊息全文，改寫「已開始裝置碼流程」並讓操作者在既有的顯示管道看到代碼。失敗訊息不要內嵌整個回傳字典。

#### CR-05 本地清單跟隨連結，只洩漏根外中繼資料

- 嚴重度：建議
- 位置：`automation_file/storage/local_storage.py` `_stat_entry`（約第 89–94 行）、`_list_dir`（約第 184–190 行）、`_walk`（約第 192–205 行）
- 說明：有根目錄時，讀寫走 `local_path` → `safe_join`，連結若指向根外會被拒絕。清單與走訪卻對目錄項呼叫 `stat()`（跟隨連結），再把目標的大小與修改時間放進 `FileInfo`。名稱仍是連結自己的名稱，不會直接給出目標路徑；內容讀取仍被拒絕。`os.walk` 預設不走入連結目錄。`progress.md` #37(a) 仍開放。
- 依據：審核規範第 6 條。與 CR-03 同類，但此處讀寫已被擋住，立即損害限於中繼資料。
- 狀態：未關閉
- 建議：清單改 `lstat`，或在 `stat` 之後用 `safe_join` 確認目標仍在根內；否則只報告連結本身。

#### CR-06 7z 與 RAR 只檢查名稱就整包解出

- 嚴重度：建議
- 位置：`automation_file/local/archive_ops.py` `_extract_seven_zip`（約第 146–157 行）、`_extract_rar`（約第 160–171 行）
- 說明：ZIP 是逐成員 `_ensure_within` 後自行寫入；tar 拒絕符號連結與硬連結，並在有 `data_filter` 時套用。7z 與 RAR 只對 `getnames()`／`namelist()` 做 `_ensure_within`，接著呼叫 `extractall`。名稱裡的 `..` 會被拒絕，但連結目標，以及套件解壓時若與清單名稱不一致的路徑，這段檢查看不到。本次未安裝並重現 py7zr／rarfile 的連結行為，所以不把它寫成已證實的寫出根外。
- 依據：審核規範第 6 條（zip slip）；同檔 ZIP／tar 已採用更嚴的寫法。
- 狀態：未關閉
- 建議：與 ZIP 相同，逐條目寫入並在寫入當下檢查解析後路徑；拒絕連結。不要在檢查名稱之後把解壓交給 `extractall`。

#### CR-07 `set_zip_password` 關閉後沒有作用

- 嚴重度：建議
- 位置：`automation_file/local/zip_ops.py` `set_zip_password`（約第 96–100 行）；登錄名 `FA_set_zip_password`（`core/action_registry.py`）
- 說明：函式開啟壓縮檔、呼叫 `setpassword`，然後隨 `with` 關閉。密碼只存在那個已丟棄的物件上，不會寫回檔案，也不會影響之後的 `unzip_*`。模組說明寫的是設定讀取用密碼。這是公開動作，呼叫成功卻不改變後續行為。
- 依據：審核規範第 4、5 條（死行為、docstring 與行為不一致）。
- 狀態：未關閉
- 建議：刪除這個動作，或改成在同一次開啟中把密碼用於實際讀取，並在說明裡寫清楚標準庫不能寫出加密 ZIP。

#### CR-08 Windows 裝置名只在 MCP 被拒絕

- 嚴重度：建議
- 位置：`automation_file/server/mcp_policy.py` `names_windows_device`（約第 180–190 行）與 `StorageGuard._confine`（約第 429–434 行）；`automation_file/storage/local_storage.py` `local_path` 沒有對應檢查
- 說明：MCP 的本地根會拒絕 `CON`、`NUL`、`COM*`、`LPT*` 以及含 `:` 的資料流名稱。`LocalStorage(root)` 只做 `safe_join`。`progress.md` #37(c) 寫明儲存層在 Windows 上仍會開啟這些名稱，並由 MCP 工具自行拒絕。本次沒有在 Windows 上重現開啟裝置，只確認攔截不在儲存層。
- 依據：審核規範第 6 條；預期目錄不應經裝置名或替代資料流繞開。
- 狀態：未關閉
- 建議：把 `names_windows_device` 挪到 `LocalStorage`（或 `safe_join` 的 Windows 分支），讓沒有經過 MCP 的根目錄也拒絕。

### 總評

熱點裡沒有 `shell=True`、沒有對不可信資料的 `eval`／`exec`／`pickle`／`yaml.load`，也沒有裸 `except:`。ZIP／tar 的經典 `../` 穿越有標準庫或自有檢查。未關閉的缺陷是：CLI 解壓沒有把檔案留在指定目錄、檔案祕密提供者可以讀出根目錄、SFTP／FTP 的根目錄擋不住符號連結、OneDrive 裝置碼登入把存取權杖放進動作結果與 GUI 日誌。後四則建議不阻擋這次結論，但與同一條路徑邊界有關。

### 已核對

- 套件閘門：`core/package_loader.py` 的 `PackageGate` 為 `OFF`。註解寫明沒有 `FA_*` 會載入套件，並以測試在出現這種動作時失敗（工作區 X-12）。全套件搜尋只看到 `PackageLoader` 與門面持有 `package_manager`，預設登錄沒有載入套件的動作。這與 `CLAUDE.md`、`architecture.md` §6 一致，不列缺陷。一旦有遠端或動作可以呼叫 `add_package_to_executor`，閘門必須改開。
- Shell：`local/shell_ops.py` 要求非空的字串列表、`shell=False`、必須有逾時。`FA_run_shell` 在預設登錄中，可執行呼叫端給的程式，但不經 shell。TCP／HTTP 預設只綁迴圈位址，ACL 是選擇性的；這與文件所說「對網路開放等同於開放動作執行」一致，不另列缺陷。
- `utils/fast_find.py` 以固定程式名稱與參數列表呼叫 `mdfind`／`locate`／`es`，有逾時，結果再經 `_is_within`。macOS 查詢字串有插值，但不符合根目錄的結果會被丟掉。不列缺陷。
- 雲端憑證來源：沒有寫死的金鑰或權杖。S3 由 `later_init` 參數或 boto3 預設鏈；Azure 由連接字串或帳戶網址加憑證；Google Drive 由呼叫端的 `token_path` 與 `credentials_path`；Dropbox、Box、OneDrive 由呼叫端權杖；SFTP／FTP 由呼叫端密碼或金鑰，SFTP 使用 `RejectPolicy`。設定裡的祕密是 `${env:...}` 與 `${file:...}`（見 CR-02）。儲存 URI 拒絕授權單位中的使用者資訊。
- YAML 使用 `yaml.safe_load`／`SafeLoader`（`local/data_ops.py`、`pipeline/definition.py`）。`ui/launcher.py` 的 `app.exec()` 是 Qt 事件迴圈，不是 Python `exec`。
- HTTP 下載走 `validate_http_url`、`allow_redirects=False`，未設 `verify=False`。WebDAV 的 `verify_tls` 預設為 `True`，呼叫端可以關掉；預設安全，不列缺陷。
- `local/tar_ops.py` 與 `archive_ops.py` 的 ZIP／tar 會拒絕逃出目的目錄的成員；tar 另拒絕連結。`extract_tar` 的說明寫 `safe_join`，實作是 `is_within`，行為仍是同一組檢查。
- 本地一般檔案動作（`file_ops` 等）沒有根目錄，這是自動化工具的預期，不是沙箱。有根目錄的路徑是 `LocalStorage`、MCP `StorageGuard`、解壓目的目錄與祕密檔根目錄。

### 未涵蓋

- 未執行 pytest、ruff、mypy，也未逐函式量測圈複雜度。抽讀的熱點函式沒有明顯超過 75 行、7 個參數或 4 層巢狀；未量測的部分不寫成缺陷。
- 未涵蓋 `tests/`、`build/`、`dist/`、`__pycache__/`、文件站 `_build/`。
- 未連線雲端，未核對 #32 所列尚未對上真實服務的轉接器。
- 未重現 Windows 裝置名開啟（CR-08）與 7z／RAR 連結解壓（CR-06）。
- `progress.md` #17、#19、#31、#32、#36、#38、#39 與發行項不在這次熱點結論裡，除非與路徑或憑證直接相關（#37 已納入 CR-03、CR-05、CR-08）。

### 本專案加嚴

- 可讀性採 `CLAUDE.md`：函式 75 行而非 80 行，另有認知複雜度 ≤ 15 與檔案 ≤ 1000 行。
- 路徑只承認 `safe_join`／`is_within`，不承認自行 `resolve` 後用字串比較。
- 套件載入視同 `eval`。目前閘門關閉是因為沒有動作入口，不是因為載入本身安全。
- 儲存 URI 不得帶憑證；`delete` 不得刪除儲存根，也不得跟隨符號連結刪除目標。
- SFTP 必須維持 `RejectPolicy`。TLS 不得以 `verify=False` 為預設。
- §6：Windows 上 `--execute_str` 的第二次 `json.loads`、`auto_control` 鍵、TCP 結尾 `Return_Data_Over_JE`、以及門面上的 `unzip_all` 都還在。CR-01 影響的是 `unzip_all` 的位置參數語意，尚未改名。

### 結論

需修正。未關閉缺陷 4 則（CR-01 至 CR-04），建議 4 則（CR-05 至 CR-08）。修完 CR-01 至 CR-04 前不符合通過。
