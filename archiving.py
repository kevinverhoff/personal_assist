MIN_ARCHIVE_CONFIDENCE = 0.9


def should_archive(classification: dict, person_match: dict | None) -> bool:
    if person_match is not None:
        return False
    if not classification.get("digest_worthy"):
        return False
    return classification.get("confidence", 0) >= MIN_ARCHIVE_CONFIDENCE
