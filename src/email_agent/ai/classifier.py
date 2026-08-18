import json

from google import genai

_MODEL = "gemini-flash-lite-latest"

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "message_type": {"type": "string", "enum": [
            "human", "newsletter", "marketing", "receipt", "notification",
            "account_service", "government_community", "school",
            "political_advocacy", "automated_other", "uncertain",
        ]},
        "importance": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
        "action_required": {"type": "boolean"},
        "keep_in_inbox": {"type": "boolean"},
        "digest_worthy": {"type": "boolean"},
        "person_org_signal": {"type": "string", "nullable": True},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": [
        "message_type", "importance", "action_required", "keep_in_inbox",
        "digest_worthy", "person_org_signal", "confidence", "reasoning",
    ],
}

_SAFE_DEFAULT = {
    "message_type": "uncertain",
    "importance": "medium",
    "action_required": False,
    "keep_in_inbox": True,
    "digest_worthy": False,
    "person_org_signal": None,
    "confidence": 0.0,
}


def make_client(api_key: str):
    return genai.Client(api_key=api_key)


def _build_prompt(subject: str, snippet: str, body: str, signals: dict, person_match: dict | None) -> str:
    person_line = "unknown sender, not in your contacts"
    if person_match:
        person_line = f"known contact: {person_match['person_name']}"
    return (
        "Classify this email for a personal inbox triage system. "
        "Be conservative: if uncertain, prefer keep_in_inbox=true.\n\n"
        f"Subject: {subject}\n"
        f"Snippet: {snippet}\n"
        f"Body excerpt: {body[:2000]}\n"
        f"Signals: {json.dumps(signals)}\n"
        f"Sender: {person_line}\n"
    )


def classify_message(client, subject: str, snippet: str, body: str, signals: dict, person_match: dict | None) -> dict:
    try:
        prompt = _build_prompt(subject, snippet, body, signals, person_match)
        response = client.models.generate_content(
            model=_MODEL,
            contents=prompt,
            config={"response_mime_type": "application/json", "response_schema": _RESPONSE_SCHEMA},
        )
        return json.loads(response.text)
    except Exception as error:
        result = dict(_SAFE_DEFAULT)
        result["reasoning"] = f"Classification failed, defaulting to safe values: {error}"
        return result
