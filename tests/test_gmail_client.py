import base64
from unittest.mock import MagicMock

from gmail_client import fetch_new_messages


def _make_message_payload(gmail_id, subject, sender):
    body_text = "Hello, this is the body."
    encoded_body = base64.urlsafe_b64encode(body_text.encode()).decode()
    return {
        "id": gmail_id,
        "threadId": f"thread-{gmail_id}",
        "snippet": "Hello, this is the...",
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "Date", "value": "Sat, 15 Aug 2026 07:00:00 -0400"},
            ],
            "mimeType": "text/plain",
            "body": {"data": encoded_body},
        },
    }


def test_fetch_new_messages_scopes_query_to_inbox():
    service = MagicMock()
    service.users().history().list().execute.return_value = {"history": [], "historyId": "999"}
    fetch_new_messages(service, last_history_id="100")
    call_kwargs = service.users().history().list.call_args.kwargs
    assert call_kwargs["labelId"] == "INBOX"
    assert call_kwargs["startHistoryId"] == "100"


def test_fetch_new_messages_parses_message_fields():
    service = MagicMock()
    service.users().history().list().execute.return_value = {
        "history": [{"messagesAdded": [{"message": {"id": "msg-1"}}]}],
        "historyId": "1001",
    }
    service.users().messages().get().execute.return_value = _make_message_payload(
        "msg-1", "Hello there", "Jane Somebody <jane@example.com>"
    )
    messages, new_history_id = fetch_new_messages(service, last_history_id="1000")
    assert new_history_id == "1001"
    assert len(messages) == 1
    assert messages[0]["gmail_message_id"] == "msg-1"
    assert messages[0]["subject"] == "Hello there"
    assert messages[0]["sender_email"] == "jane@example.com"
    assert messages[0]["sender_name"] == "Jane Somebody"
    assert "Hello, this is the body." in messages[0]["body"]


def test_fetch_new_messages_no_history_id_does_full_inbox_scan():
    service = MagicMock()
    service.users().messages().list().execute.return_value = {"messages": [{"id": "msg-1"}]}
    service.users().messages().get().execute.return_value = _make_message_payload(
        "msg-1", "First run", "Someone <someone@example.com>"
    )
    service.users().history().list().execute.return_value = {"historyId": "500"}
    messages, new_history_id = fetch_new_messages(service, last_history_id=None)
    assert len(messages) == 1
    assert new_history_id == "500"
    list_call_kwargs = service.users().messages().list.call_args.kwargs
    assert list_call_kwargs["q"] == "in:inbox"
