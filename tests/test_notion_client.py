from unittest.mock import MagicMock, patch

from notion_client import NotionClient


def _mock_response(json_data, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status = MagicMock()
    return response


@patch("notion_client.requests.post")
def test_query_data_source_sends_correct_request(mock_post):
    mock_post.return_value = _mock_response({"results": [{"id": "page-1", "properties": {}}], "has_more": False})
    client = NotionClient(token="secret_abc")
    results = client.query_data_source("ds-123", filter={"property": "Email", "email": {"equals": "a@x.com"}})

    assert results == [{"id": "page-1", "properties": {}}]
    called_url = mock_post.call_args.args[0]
    assert "ds-123" in called_url
    called_headers = mock_post.call_args.kwargs["headers"]
    assert called_headers["Authorization"] == "Bearer secret_abc"
    assert "Notion-Version" in called_headers


@patch("notion_client.requests.post")
def test_query_data_source_paginates(mock_post):
    mock_post.side_effect = [
        _mock_response({"results": [{"id": "p1", "properties": {}}], "has_more": True, "next_cursor": "cur1"}),
        _mock_response({"results": [{"id": "p2", "properties": {}}], "has_more": False}),
    ]
    client = NotionClient(token="secret_abc")
    results = client.query_data_source("ds-123")
    assert [r["id"] for r in results] == ["p1", "p2"]
    assert mock_post.call_count == 2


@patch("notion_client.requests.post")
def test_create_page_sends_parent_and_properties(mock_post):
    mock_post.return_value = _mock_response({"id": "new-page", "properties": {"Name": {}}})
    client = NotionClient(token="secret_abc")
    result = client.create_page("ds-123", properties={"Name": {"title": [{"text": {"content": "Jane"}}]}})
    assert result["id"] == "new-page"
    payload = mock_post.call_args.kwargs["json"]
    assert payload["parent"] == {"type": "data_source_id", "data_source_id": "ds-123"}
    assert payload["properties"]["Name"]["title"][0]["text"]["content"] == "Jane"


@patch("notion_client.requests.patch")
def test_update_page_sends_properties(mock_patch):
    mock_patch.return_value = _mock_response({"id": "page-1", "properties": {}})
    client = NotionClient(token="secret_abc")
    result = client.update_page("page-1", properties={"Status": {"select": {"name": "Needs Review"}}})
    assert result["id"] == "page-1"
    payload = mock_patch.call_args.kwargs["json"]
    assert payload["properties"]["Status"]["select"]["name"] == "Needs Review"


@patch("notion_client.requests.post")
def test_create_child_page_uses_page_id_parent(mock_post):
    mock_post.return_value = _mock_response({"id": "child-page-1"})
    client = NotionClient(token="secret_abc")
    result = client.create_child_page("parent-page-id", "Email Agent — Latest Run", content="hello")
    assert result["id"] == "child-page-1"
    payload = mock_post.call_args.kwargs["json"]
    assert payload["parent"] == {"type": "page_id", "page_id": "parent-page-id"}
    assert payload["properties"]["title"]["title"][0]["text"]["content"] == "Email Agent — Latest Run"
