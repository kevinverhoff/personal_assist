import difflib
import re
from dataclasses import dataclass, field

NAME_MATCH_THRESHOLD = 0.92


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _extract_title(properties: dict, prop_name: str) -> str:
    prop = properties.get(prop_name, {})
    title_parts = prop.get("title", [])
    return "".join(part.get("plain_text", "") for part in title_parts)


@dataclass
class PeopleCache:
    people_by_id: dict = field(default_factory=dict)   # person_id -> name
    email_to_person_id: dict = field(default_factory=dict)  # normalized email -> person_id

    @classmethod
    def load(cls, client, config) -> "PeopleCache":
        people_by_id = {}
        for page in client.query_data_source(config.notion_people_data_source_id):
            name = _extract_title(page["properties"], "Name")
            people_by_id[page["id"]] = name

        email_to_person_id = {}
        for page in client.query_data_source(config.notion_email_addresses_data_source_id):
            props = page["properties"]
            email = (props.get("Email", {}) or {}).get("email")
            relation = (props.get("Person", {}) or {}).get("relation", [])
            if email and relation:
                email_to_person_id[email.strip().lower()] = relation[0]["id"]

        return cls(people_by_id=people_by_id, email_to_person_id=email_to_person_id)

    def match_by_email(self, email: str) -> dict | None:
        person_id = self.email_to_person_id.get(email.strip().lower())
        if not person_id:
            return None
        return {"person_id": person_id, "person_name": self.people_by_id[person_id]}

    def match_by_name(self, display_name: str) -> dict | None:
        if not display_name:
            return None
        target = normalize_name(display_name)
        best_id, best_score = None, 0.0
        for person_id, name in self.people_by_id.items():
            score = difflib.SequenceMatcher(a=target, b=normalize_name(name)).ratio()
            if score > best_score:
                best_id, best_score = person_id, score
        if best_id and best_score >= NAME_MATCH_THRESHOLD:
            return {"person_id": best_id, "person_name": self.people_by_id[best_id], "score": best_score}
        return None
