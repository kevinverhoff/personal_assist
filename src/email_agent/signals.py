import re

_AUTOMATED_PATTERNS = [
    r"no-?reply",
    r"do-?not-?reply",
    r"^notifications?@",
    r"^mailer@",
    r"^automated@",
]


def _has_list_unsubscribe(headers: dict) -> bool:
    return any(key.lower() == "list-unsubscribe" for key in headers)


def _is_bulk_precedence(headers: dict) -> bool:
    for key, value in headers.items():
        if key.lower() == "precedence" and value.strip().lower() in ("bulk", "list"):
            return True
    return False


def _sender_domain(sender_email: str) -> str:
    return sender_email.split("@")[-1].lower() if "@" in sender_email else ""


def _looks_automated(sender_email: str) -> bool:
    local_part = sender_email.split("@")[0].lower()
    return any(re.search(pattern, local_part) for pattern in _AUTOMATED_PATTERNS)


def extract_signals(headers: dict[str, str], sender_email: str) -> dict:
    return {
        "has_list_unsubscribe": _has_list_unsubscribe(headers),
        "is_bulk_precedence": _is_bulk_precedence(headers),
        "sender_domain": _sender_domain(sender_email),
        "looks_automated": _looks_automated(sender_email),
    }
