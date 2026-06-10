from __future__ import annotations

import json
import os
from datetime import date, datetime
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


def today_iso() -> str:
    return date.today().isoformat()


def coerce_number(value: Any) -> float | int | str:
    try:
        number = float(value)
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return str(value)


def format_value(scraper_field: str, raw_value: Any, monday_column_id: str, column_type: str) -> Any:
    if raw_value in (None, ""):
        return None

    if column_type == "link":
        return {"url": str(raw_value), "text": str(raw_value)}

    if column_type == "status":
        return {"label": str(raw_value)}

    if column_type == "dropdown":
        if isinstance(raw_value, list):
            return {"labels": [str(v) for v in raw_value if v not in (None, "")]}
        return {"labels": [str(raw_value)]}

    if column_type == "date":
        if scraper_field == "date_added" and str(raw_value).lower() == "today":
            raw_value = today_iso()
        return {"date": str(raw_value)[:10]}

    if column_type == "numbers":
        return coerce_number(raw_value)

    if column_type == "email":
        return {"email": str(raw_value), "text": str(raw_value)}

    return str(raw_value)


def build_column_values(row: Dict[str, Any], mapping: Dict[str, Any]) -> Dict[str, Any]:
    """Convert scraper output row into Monday column_values.

    New mapping format:
      scraper_field -> {"id": "monday_column_id", "type": "status|dropdown|link|numbers|date|text|long_text|email", "value": optional_static_value}

    Legacy mapping still works:
      scraper_field -> "monday_column_id"
    """
    values: Dict[str, Any] = {}
    for scraper_field, config in mapping.items():
        if isinstance(config, str):
            monday_column_id = config
            column_type = "link" if scraper_field in {"youtube_url", "best_recent_video"} else "text"
            raw_value = row.get(scraper_field)
        else:
            monday_column_id = config.get("id")
            column_type = config.get("type", "text")
            raw_value = config.get("value", row.get(scraper_field))

        if not monday_column_id:
            continue

        formatted = format_value(scraper_field, raw_value, monday_column_id, column_type)
        if formatted is not None:
            values[monday_column_id] = formatted
    return values


def push_rows_to_monday(
    rows: Iterable[Dict[str, Any]],
    board_id: int,
    mapping: Dict[str, Any],
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
