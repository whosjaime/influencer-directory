from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Optional

import requests


class MondayAPIError(RuntimeError):
    pass


class MondayClient:
    """Minimal Monday.com GraphQL client for pushing creator leads into a board."""

    API_URL = "https://api.monday.com/v2"

    def __init__(self, api_token: Optional[str] = None) -> None:
        self.api_token = api_token or os.getenv("MONDAY_API_TOKEN")
        if not self.api_token:
            raise MondayAPIError("Missing MONDAY_API_TOKEN.")

    def _post(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        response = requests.post(
            self.API_URL,
            headers={"Authorization": self.api_token, "Content-Type": "application/json"},
            json={"query": query, "variables": variables or {}},
            timeout=30,
        )
        if response.status_code >= 400:
            raise MondayAPIError(f"Monday API error {response.status_code}: {response.text[:500]}")
        data = response.json()
        if data.get("errors"):
            raise MondayAPIError(json.dumps(data["errors"], indent=2))
        return data.get("data", {})

    def create_item(self, board_id: int, item_name: str, column_values: Dict[str, Any], group_id: Optional[str] = None) -> Dict[str, Any]:
        mutation = """
        mutation CreateItem($board_id: ID!, $group_id: String, $item_name: String!, $column_values: JSON!) {
          create_item(board_id: $board_id, group_id: $group_id, item_name: $item_name, column_values: $column_values) {
            id
            name
            url
          }
        }
        """
        variables = {
            "board_id": str(board_id),
            "group_id": group_id,
            "item_name": item_name,
            "column_values": json.dumps(column_values),
        }
        return self._post(mutation, variables)["create_item"]


def build_column_values(row: Dict[str, Any], mapping: Dict[str, str]) -> Dict[str, Any]:
    """Convert scraper output row into Monday column_values.

    Mapping format:
      scraper_field -> monday_column_id

    Example:
      {"youtube_url": "link__1", "fit_score": "numbers__1"}
    """
    values: Dict[str, Any] = {}
    for scraper_field, monday_column_id in mapping.items():
        if scraper_field not in row or not monday_column_id:
            continue
        raw_value = row.get(scraper_field)
        if raw_value in (None, ""):
            continue

        if scraper_field in {"youtube_url", "best_recent_video"}:
            values[monday_column_id] = {"url": str(raw_value), "text": str(raw_value)}
        else:
            values[monday_column_id] = str(raw_value)
    return values


def push_rows_to_monday(
    rows: Iterable[Dict[str, Any]],
    board_id: int,
    mapping: Dict[str, str],
    group_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    client = MondayClient()
    created: List[Dict[str, Any]] = []
    for index, row in enumerate(rows):
        if limit is not None and index >= limit:
            break
        item_name = row.get("name") or row.get("youtube_url") or "YouTube Creator Lead"
        column_values = build_column_values(row, mapping)
        created.append(client.create_item(board_id=board_id, group_id=group_id, item_name=str(item_name), column_values=column_values))
    return created
