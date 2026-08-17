from archiving import should_archive, MIN_ARCHIVE_CONFIDENCE


def test_should_archive_true_for_routine_high_confidence_unmatched():
    classification = {"digest_worthy": True, "confidence": 0.95}
    assert should_archive(classification, None) is True


def test_should_archive_false_if_matched_to_known_person():
    classification = {"digest_worthy": True, "confidence": 0.95}
    assert should_archive(classification, {"person_id": "p1", "person_name": "X"}) is False


def test_should_archive_false_if_confidence_below_threshold():
    classification = {"digest_worthy": True, "confidence": MIN_ARCHIVE_CONFIDENCE - 0.01}
    assert should_archive(classification, None) is False


def test_should_archive_true_at_exact_threshold():
    classification = {"digest_worthy": True, "confidence": MIN_ARCHIVE_CONFIDENCE}
    assert should_archive(classification, None) is True


def test_should_archive_false_if_not_digest_worthy():
    classification = {"digest_worthy": False, "confidence": 0.99}
    assert should_archive(classification, None) is False
