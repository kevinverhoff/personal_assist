"""
Run this once to mint a refresh token: `python gmail_auth_setup.py`
Opens a browser for you to consent, then prints the refresh token to paste
into .env as GOOGLE_REFRESH_TOKEN.

Before running: in Google Cloud Console, register a Desktop app OAuth
client, add yourself as a test user, and note the client ID/secret in .env.
After running: go to the OAuth consent screen and click "Publish App"
(Testing -> In production, skip verification) to avoid the 7-day refresh
token expiry that applies while the app stays in Testing status.

Note: the scope below is gmail.modify (read + label changes, used for
archiving), not gmail.readonly. If you already have a refresh token from
before archiving existed, it does NOT carry the new permission -- you must
re-run this script to get a new one; the old token still works for reading
but a modify call with it will fail.
"""
import os

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv()

_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def main():
    client_config = {
        "installed": {
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, _SCOPES)
    credentials = flow.run_local_server(port=0)
    print("\nSuccess. Paste this into .env as GOOGLE_REFRESH_TOKEN:\n")
    print(credentials.refresh_token)


if __name__ == "__main__":
    main()
