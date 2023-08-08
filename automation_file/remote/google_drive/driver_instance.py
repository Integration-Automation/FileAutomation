from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from automation_file.utils.logging.loggin_instance import file_automation_logger


class GoogleDrive(object):

    def __init__(self):
        self.google_drive_instance = None
        self.creds = None
        self.service = None
        self.scopes = ["https://www.googleapis.com/auth/drive"]

    def later_init(self, token_path: str, credentials_path: str):
        token_path = Path(token_path)
        credentials_path = Path(credentials_path)
        creds = None
        # The file token.json stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        if token_path.exists():
            file_automation_logger.info(
                f"Token exists try to load."
            )
            creds = Credentials.from_authorized_user_file(str(token_path), self.scopes)
        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(credentials_path), self.scopes)
                creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open(str(token_path), 'w') as token:
                token.write(creds.to_json())
        try:
            self.service = build('drive', 'v3', credentials=creds)
            file_automation_logger.info(
                f"Loading service successfully."
            )
        except HttpError as error:
            file_automation_logger.error(
                f"Delete file failed,"
                f"error: {error}"
            )


driver_instance = GoogleDrive()

