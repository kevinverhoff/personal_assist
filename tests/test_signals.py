from signals import extract_signals


def test_detects_list_unsubscribe():
    result = extract_signals({"List-Unsubscribe": "<mailto:unsub@x.com>"}, "news@x.com")
    assert result["has_list_unsubscribe"] is True


def test_no_list_unsubscribe():
    result = extract_signals({}, "friend@example.com")
    assert result["has_list_unsubscribe"] is False


def test_detects_bulk_precedence():
    result = extract_signals({"Precedence": "bulk"}, "news@x.com")
    assert result["is_bulk_precedence"] is True


def test_extracts_sender_domain():
    result = extract_signals({}, "person@cityofgreencastle.com")
    assert result["sender_domain"] == "cityofgreencastle.com"


def test_looks_automated_for_noreply():
    result = extract_signals({}, "no-reply@service.com")
    assert result["looks_automated"] is True


def test_does_not_look_automated_for_real_name_style_address():
    result = extract_signals({}, "jane.smith@example.com")
    assert result["looks_automated"] is False
