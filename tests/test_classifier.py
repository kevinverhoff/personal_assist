import json
from unittest.mock import MagicMock

from classifier import classify_message


def _fake_client_returning(payload: dict):
    client = MagicMock()
    response = MagicMock()
    response.text = json.dumps(payload)
    client.models.generate_content.return_value = response
    return client


def test_classify_message_returns_parsed_schema():
    payload = {
        "message_type": "human", "importance": "high", "action_required": True,
        "keep_in_inbox": True, "digest_worthy": False, "person_org_signal": None,
        "confidence": 0.91, "reasoning": "Plan Commission asking for feedback",
    }
    client = _fake_client_returning(payload)
    result = classify_message(client, "Re: Draft", "please review", "please review by Friday", {}, None)
    assert result == payload


def test_classify_message_falls_back_safely_on_exception():
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("API down")
    result = classify_message(client, "subject", "snippet", "body", {}, None)
    assert result["keep_in_inbox"] is True
    assert result["message_type"] == "uncertain"
    assert result["confidence"] == 0.0
    assert "API down" in result["reasoning"]


def test_classify_message_includes_person_match_in_prompt():
    payload = {
        "message_type": "human", "importance": "high", "action_required": False,
        "keep_in_inbox": True, "digest_worthy": False, "person_org_signal": None,
        "confidence": 0.8, "reasoning": "known contact",
    }
    client = _fake_client_returning(payload)
    classify_message(client, "s", "sn", "b", {}, {"person_id": "p1", "person_name": "Blaine Rout"})
    prompt = client.models.generate_content.call_args.kwargs["contents"]
    assert "Blaine Rout" in prompt
