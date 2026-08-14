import base64
import datetime
import email.utils

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


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
        history_response = service.users().history().list(
            userId="me", startHistoryId=last_history_id, labelId="INBOX"
        ).execute()
        for record in history_response.get("history", []):
            for added in record.get("messagesAdded", []):
                message_ids.append(added["message"]["id"])
        new_history_id = history_response["historyId"]
    else:
        list_response = service.users().messages().list(userId="me", q="in:inbox").execute()
        message_ids = [m["id"] for m in list_response.get("messages", [])]
        new_history_id = service.users().getProfile(userId="me").execute()["historyId"]

    messages = []
    for message_id in message_ids:
        raw = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        messages.append(_parse_message(raw))

    return messages, new_history_id
