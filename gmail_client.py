import base64
import datetime
import email.utils

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# gmail.modify is a superset of read access plus label changes (archive is
# implemented as removing the INBOX label) -- it does NOT allow permanent
# delete/send. Changing this from gmail.readonly requires re-running
# gmail_auth_setup.py to mint a new refresh token with the new scope; the
# old token does not gain the new permission automatically.
_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def build_service(config):
    credentials = Credentials(
        token=None,
        refresh_token=config.google_refresh_token,
        client_id=config.google_client_id,
        client_secret=config.google_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=_SCOPES,
    )
    return build("gmail", "v1", credentials=credentials)


def _decode_body(payload: dict) -> str:
    body_data = payload.get("body", {}).get("data")
    if body_data:
        return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []) or []:
        if part.get("mimeType") == "text/plain":
            return _decode_body(part)
    return ""


def _received_at(raw: dict, headers: dict) -> str:
    internal_date_ms = raw.get("internalDate")
    if internal_date_ms:
        dt = datetime.datetime.fromtimestamp(int(internal_date_ms) / 1000, tz=datetime.UTC)
        return dt.isoformat()
    parsed = email.utils.parsedate_to_datetime(headers.get("Date", ""))
    if parsed:
        return parsed.astimezone(datetime.UTC).isoformat()
    return ""


def _parse_message(raw: dict) -> dict:
    headers = {h["name"]: h["value"] for h in raw["payload"]["headers"]}
    sender_name, sender_email = email.utils.parseaddr(headers.get("From", ""))
    return {
        "gmail_message_id": raw["id"],
        "thread_id": raw["threadId"],
        "sender_email": sender_email,
        "sender_name": sender_name or sender_email,
        "subject": headers.get("Subject", ""),
        "received_at": _received_at(raw, headers),
        "snippet": raw.get("snippet", ""),
        "body": _decode_body(raw["payload"]),
        "headers": headers,
    }


def fetch_new_messages(service, last_history_id: str | None) -> tuple[list[dict], str]:
    message_ids: list[str] = []

    if last_history_id:
        page_token = None
        new_history_id = last_history_id
        while True:
            kwargs = {"userId": "me", "startHistoryId": last_history_id, "labelId": "INBOX"}
            if page_token:
                kwargs["pageToken"] = page_token
            history_response = service.users().history().list(**kwargs).execute()
            for record in history_response.get("history", []):
                for added in record.get("messagesAdded", []):
                    message_ids.append(added["message"]["id"])
            new_history_id = history_response["historyId"]
            page_token = history_response.get("nextPageToken")
            if not page_token:
                break
    else:
        list_response = service.users().messages().list(userId="me", q="in:inbox").execute()
        message_ids = [m["id"] for m in list_response.get("messages", [])]
        new_history_id = service.users().getProfile(userId="me").execute()["historyId"]

    messages = []
    for message_id in message_ids:
        try:
            raw = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        except HttpError as error:
            if error.resp.status == 404:
                # history.list can reference a message that's gone by the
                # time we fetch it (auto-deleted spam, moved out of Gmail
                # entirely) -- skip it rather than losing the whole batch
                # and getting stuck retrying the same dead message forever.
                continue
            raise
        messages.append(_parse_message(raw))

    return messages, new_history_id


def archive_message(service, gmail_message_id: str) -> None:
    service.users().messages().modify(
        userId="me", id=gmail_message_id, body={"removeLabelIds": ["INBOX"]}
    ).execute()


def get_or_create_label(service, name: str, background_color: str, text_color: str) -> str:
    existing = service.users().labels().list(userId="me").execute().get("labels", [])
    for label in existing:
        if label["name"] == name:
            return label["id"]

    created = service.users().labels().create(
        userId="me",
        body={
            "name": name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
            "color": {"backgroundColor": background_color, "textColor": text_color},
        },
    ).execute()
    return created["id"]


def apply_label(service, gmail_message_id: str, label_id: str) -> None:
    service.users().messages().modify(
        userId="me", id=gmail_message_id, body={"addLabelIds": [label_id]}
    ).execute()
