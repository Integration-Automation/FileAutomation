from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from file_automation.utils.exception.exception_tags import token_is_exist


def create_token(credentials_path: str):
    scopes = ["https://www.googleapis.com/auth/drive"]
    token_path = Path(Path.cwd(), "token.json")
    if token_path.exists():
        print(token_is_exist, file=sys.stderr)
    flow = InstalledAppFlow.from_client_secrets_file(
        str(credentials_path), scopes)
    creds = flow.run_local_server(port=0)
    with open(str(token_path), 'w') as token:
        token.write(creds.to_json())
