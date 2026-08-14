import requests

_BASE_URL = "https://api.notion.com/v1"
_NOTION_VERSION = "2025-09-03"


class NotionClient:
    def __init__(self, token: str):
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": _NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def query_data_source(self, data_source_id: str, filter: dict | None = None) -> list[dict]:
        results: list[dict] = []
        cursor = None
        while True:
            payload: dict = {}
            if filter:
                payload["filter"] = filter
            if cursor:
                payload["start_cursor"] = cursor
            response = requests.post(
                f"{_BASE_URL}/data_sources/{data_source_id}/query",
                headers=self._headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            results.extend(data["results"])
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return results

    def create_page(self, data_source_id: str, properties: dict, content: str | None = None) -> dict:
        payload: dict = {
            "parent": {"type": "data_source_id", "data_source_id": data_source_id},
            "properties": properties,
        }
        if content:
            payload["children"] = [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]},
                }
            ]
        response = requests.post(f"{_BASE_URL}/pages", headers=self._headers, json=payload)
        response.raise_for_status()
        return response.json()

    def update_page(self, page_id: str, properties: dict | None = None) -> dict:
        payload: dict = {}
        if properties:
            payload["properties"] = properties
        response = requests.patch(f"{_BASE_URL}/pages/{page_id}", headers=self._headers, json=payload)
        response.raise_for_status()
        return response.json()

    def replace_page_content(self, page_id: str, content: str) -> None:
        cursor = None
        block_ids: list[str] = []
        while True:
            params = {"start_cursor": cursor} if cursor else {}
            response = requests.get(
                f"{_BASE_URL}/blocks/{page_id}/children", headers=self._headers, params=params
            )
            response.raise_for_status()
            data = response.json()
            block_ids.extend(block["id"] for block in data["results"])
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

        for block_id in block_ids:
            response = requests.delete(f"{_BASE_URL}/blocks/{block_id}", headers=self._headers)
            response.raise_for_status()

        response = requests.patch(
            f"{_BASE_URL}/blocks/{page_id}/children",
            headers=self._headers,
            json={"children": [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]},
                }
            ]},
        )
        response.raise_for_status()

    def create_child_page(self, parent_page_id: str, title: str, content: str | None = None) -> dict:
        payload: dict = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "properties": {"title": {"title": [{"text": {"content": title}}]}},
        }
        if content:
            payload["children"] = [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]},
                }
            ]
        response = requests.post(f"{_BASE_URL}/pages", headers=self._headers, json=payload)
        response.raise_for_status()
        return response.json()
