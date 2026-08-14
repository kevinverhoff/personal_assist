def _person_page_properties(name: str) -> dict:
    return {
        "Name": {"title": [{"text": {"content": name}}]},
        "Status": {"select": {"name": "Needs Review"}},
        "Active": {"checkbox": True},
    }


def _email_page_properties(address: str, person_id: str) -> dict:
    return {
        "Address": {"title": [{"text": {"content": address}}]},
        "Email": {"email": address},
        "Person": {"relation": [{"id": person_id}]},
        "Confidence": {"select": {"name": "Inferred - needs review"}},
    }


def reconcile_sender(client, config, cache, sender_email: str, sender_name: str, is_human: bool, dry_run: bool) -> dict:
    existing = cache.match_by_email(sender_email)
    if existing:
        return {"action": "known", "person_id": existing["person_id"]}

    name_match = cache.match_by_name(sender_name)
    if name_match:
        if dry_run:
            return {"action": "attached_email", "person_id": name_match["person_id"], "logged_only": True}
        client.create_page(
            config.notion_email_addresses_data_source_id,
            _email_page_properties(sender_email, name_match["person_id"]),
        )
        return {"action": "attached_email", "person_id": name_match["person_id"], "logged_only": False}

    if not is_human:
        return {"action": "no_action"}

    if dry_run:
        return {"action": "created_person", "person_id": None, "logged_only": True}

    person_page = client.create_page(config.notion_people_data_source_id, _person_page_properties(sender_name))
    client.create_page(
        config.notion_email_addresses_data_source_id,
        _email_page_properties(sender_email, person_page["id"]),
    )
    return {"action": "created_person", "person_id": person_page["id"], "logged_only": False}
