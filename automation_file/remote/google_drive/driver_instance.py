from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from automation_file.utils.logging.loggin_instance import file_automation_logger


class GoogleDrive(object):

    def __init__(self):
        # Google Drive 實例相關屬性
        # Attributes for Google Drive instance
        self.google_drive_instance = None
        self.creds = None
        self.service = None
        # 權限範圍：完整存取 Google Drive
        # Scope: full access to Google Drive
        self.scopes = ["https://www.googleapis.com/auth/drive"]

    def later_init(self, token_path: str, credentials_path: str):
        """
        初始化 Google Drive API 驅動
        Initialize Google Drive API driver
        :param token_path: Google Drive token 檔案路徑 (str)
                           Path to token.json file
        :param credentials_path: Google Drive credentials 憑證檔案路徑 (str)
                                 Path to credentials.json file
        :return: None
        """
        token_path = Path(token_path)
        credentials_path = Path(credentials_path)
        creds = None

        # token.json 儲存使用者的 access 與 refresh token
        # token.json stores user's access and refresh tokens
        if token_path.exists():
            file_automation_logger.info("Token exists, try to load.")
            creds = Credentials.from_authorized_user_file(str(token_path), self.scopes)

        # 如果沒有有效的憑證，則重新登入
        # If no valid credentials, perform login
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                # 如果憑證過期但有 refresh token，則刷新
                # Refresh credentials if expired but refresh token exists
                creds.refresh(Request())
            else:
                # 使用 OAuth2 流程重新登入
                # Use OAuth2 flow for login
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(credentials_path), self.scopes
                )
                creds = flow.run_local_server(port=0)

            # 儲存憑證到 token.json，供下次使用
            # Save credentials to token.json for future use
            with open(str(token_path), 'w') as token:
                token.write(creds.to_json())

        try:
            # 建立 Google Drive API service
            # Build Google Drive API service
            self.service = build('drive', 'v3', credentials=creds)
            file_automation_logger.info("Loading service successfully.")
        except HttpError as error:
            file_automation_logger.error(
                f"Init service failed, error: {error}"
            )


# 建立單例，供其他模組使用
# Create a singleton instance for other modules to use
driver_instance = GoogleDrive()