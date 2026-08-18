import base64
from unittest.mock import MagicMock

from googleapiclient.errors import HttpError

from email_agent.gmail.client import fetch_new_messages, _parse_message, archive_message, get_or_create_label, apply_label


class _FakeResp:
    def __init__(self, status):
        self.status = status
        self.reason = "Not Found"


def _not_found_error():
    return HttpError(_FakeResp(404), b'{"error": {"code": 404, "message": "Requested entity was not found."}}')


def _make_message_payload(gmail_id, subject, sender, internal_date_ms=None):
    body_text = "Hello, this is the body."
    encoded_body = base64.urlsafe_b64encode(body_text.encode()).decode()
    payload = {
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
    if internal_date_ms is not None:
        payload["internalDate"] = str(internal_date_ms)
    return payload


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


def test_parse_message_uses_internal_date_when_present():
    raw = _make_message_payload("msg-1", "Hi", "Someone <someone@example.com>", internal_date_ms=1786000000000)
    result = _parse_message(raw)
    assert result["received_at"] == "2026-08-06T07:06:40+00:00"


def test_parse_message_falls_back_to_date_header_without_internal_date():
    raw = _make_message_payload("msg-1", "Hi", "Someone <someone@example.com>")
    result = _parse_message(raw)
    assert result["received_at"] == "2026-08-15T11:00:00+00:00"


def test_fetch_new_messages_paginates_through_history():
    # Reproduces the real bug: Gmail's history.list caps at 100 records per
    # page. With enough mailbox activity (reads, label changes, not just new
    # mail) between runs, genuinely new messages can land on page 2+, which
    # must not be silently dropped.
    service = MagicMock()
    service.users().history().list().execute.side_effect = [
        {"history": [{"messagesAdded": []}], "historyId": "999", "nextPageToken": "page2"},
        {"history": [{"messagesAdded": [{"message": {"id": "msg-1"}}]}], "historyId": "999"},
    ]
    service.users().messages().get().execute.return_value = _make_message_payload(
        "msg-1", "Hello there", "Jane Somebody <jane@example.com>"
    )
    messages, new_history_id = fetch_new_messages(service, last_history_id="100")
    assert new_history_id == "999"
    assert len(messages) == 1
    assert messages[0]["gmail_message_id"] == "msg-1"
    paged_calls = [
        call.kwargs for call in service.users().history().list.call_args_list
        if call.kwargs.get("pageToken") == "page2"
    ]
    assert len(paged_calls) == 1


def test_fetch_new_messages_skips_message_deleted_before_fetch():
    # Reproduces the real bug: history.list can reference a message that no
    # longer exists by the time we call messages.get (auto-deleted spam,
    # moved out of Gmail entirely, etc). A single 404 must not crash the
    # whole run and strand new_history_id -- the other messages in the same
    # batch still need to come through, and the batch's real historyId must
    # still be returned so sync_state advances past the bad message.
    service = MagicMock()
    service.users().history().list().execute.return_value = {
        "history": [{"messagesAdded": [
            {"message": {"id": "msg-deleted"}},
            {"message": {"id": "msg-1"}},
        ]}],
        "historyId": "1001",
    }
    service.users().messages().get().execute.side_effect = [
        _not_found_error(),
        _make_message_payload("msg-1", "Hello there", "Jane Somebody <jane@example.com>"),
    ]
    messages, new_history_id = fetch_new_messages(service, last_history_id="1000")
    assert new_history_id == "1001"
    assert len(messages) == 1
    assert messages[0]["gmail_message_id"] == "msg-1"


def test_archive_message_removes_inbox_label_only():
    service = MagicMock()
    archive_message(service, "msg-1")
    service.users().messages().modify.assert_called_once_with(
        userId="me", id="msg-1", body={"removeLabelIds": ["INBOX"]}
    )


def test_get_or_create_label_returns_existing_label_id_without_creating():
    service = MagicMock()
    service.users().labels().list().execute.return_value = {
        "labels": [{"id": "Label_1", "name": "VIP"}, {"id": "Label_2", "name": "Known Contact"}]
    }
    label_id = get_or_create_label(service, "VIP", background_color="#fb4c2f", text_color="#ffffff")
    assert label_id == "Label_1"
    service.users().labels().create.assert_not_called()


def test_get_or_create_label_creates_when_missing():
    service = MagicMock()
    service.users().labels().list().execute.return_value = {"labels": []}
    service.users().labels().create().execute.return_value = {"id": "Label_new"}
    label_id = get_or_create_label(service, "VIP", background_color="#fb4c2f", text_color="#ffffff")
    assert label_id == "Label_new"
    create_kwargs = service.users().labels().create.call_args.kwargs
    assert create_kwargs["body"]["name"] == "VIP"
    assert create_kwargs["body"]["color"] == {"backgroundColor": "#fb4c2f", "textColor": "#ffffff"}


def test_apply_label_adds_label_id_to_message():
    service = MagicMock()
    apply_label(service, "msg-1", "Label_1")
    service.users().messages().modify.assert_called_once_with(
        userId="me", id="msg-1", body={"addLabelIds": ["Label_1"]}
    )


def test_fetch_new_messages_no_history_id_does_full_inbox_scan():
    service = MagicMock()
    service.users().messages().list().execute.return_value = {"messages": [{"id": "msg-1"}]}
    service.users().messages().get().execute.return_value = _make_message_payload(
        "msg-1", "First run", "Someone <someone@example.com>"
    )
    service.users().getProfile().execute.return_value = {"historyId": "500"}
    messages, new_history_id = fetch_new_messages(service, last_history_id=None)
    assert len(messages) == 1
    assert new_history_id == "500"
    list_call_kwargs = service.users().messages().list.call_args.kwargs
    assert list_call_kwargs["q"] == "in:inbox"
