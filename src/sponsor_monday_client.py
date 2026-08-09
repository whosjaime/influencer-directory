from __future__ import annotations

import json
import re
from dataclasses import dataclass

import requests

from sponsor_dedupe import ExistingSponsorIndex, email_domain, normalize_brand_name, normalize_domain, normalize_email, normalize_text
from sponsor_models import SponsorLead


MONDAY_API_URL = "https://api.monday.com/v2"

PROTECTED_OUTREACH_STATUSES = {
    "outreach sent", "contacted", "follow up", "follow-up", "in conversation",
    "call booked", "booked call", "working with", "client", "do not contact",
    "rejected", "not interested", "closed",
}

COLUMN_ALIASES = {
    "brand_name": ["brand", "sponsor", "company", "brand name", "sponsor name"],
    "brand_domain": ["domain", "website", "brand domain", "sponsor domain", "brand website"],
    "contact_email": ["contact email", "email", "sponsor email", "partnership email", "brand email"],
    "email_type": ["email type", "contact type"],
    "contact_source": ["email source", "contact source", "source url"],
    "sponsor_category": ["brand category", "sponsor category", "category"],
    "sponsor_subcategory": ["brand subcategory", "sponsor subcategory", "subcategory"],
    "creator_name": ["creator", "creator name", "influencer", "channel"],
    "creator_url": ["creator url", "channel url", "creator profile", "creator link"],
    "creator_subscribers": ["creator subscribers", "subscribers", "subscriber count"],
    "creator_genre": ["creator genre", "genre", "creator niche", "niche"],
    "creator_tags": ["creator tags", "tags"],
    "source_platform": ["platform", "source platform"],
    "video_url": ["video url", "sponsored video", "content url", "sponsor video"],
    "video_title": ["video title", "content title"],
    "sponsored_date": ["sponsored date", "published date", "ad date", "sponsorship date"],
    "evidence": ["evidence", "sponsor evidence", "sponsorship evidence", "notes"],
    "paid_product_placement": ["paid promotion", "paid placement", "paid product placement"],
    "lead_score": ["lead score", "score", "warm lead score"],
    "lead_temperature": ["temperature", "lead temperature", "warmth"],
    "sponsorship_key": ["sponsorship key", "event key", "sponsor event key"],
    "brand_key": ["brand key", "dedupe key", "sponsor key"],
    "outreach_status": ["outreach status", "status", "lead status"],
    "date_found": ["date found", "found date", "date added"],
}


@dataclass
class ColumnInfo:
    id: str
    title: str
    type: str


class SponsorMondayClient:
    def __init__(self, token: str, board_id: int, group_id: str = "", api_version: str = "2025-04") -> None:
        self.token = token
        self.board_id = int(board_id)
        self.requested_group_id = group_id
        self.api_version = api_version
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": token,
                "Content-Type": "application/json",
                "API-Version": api_version,
            }
        )
        self._columns: dict[str, ColumnInfo] | None = None
        self._groups: list[dict] | None = None

    def _request(self, query: str, variables: dict | None = None) -> dict:
        response = self.session.post(
            MONDAY_API_URL,
            json={"query": query, "variables": variables or {}},
            timeout=30,
        )
        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError(f"Invalid monday response: {response.text[:1000]}") from exc
        if response.status_code != 200 or data.get("errors"):
            raise RuntimeError(f"monday API error: {json.dumps(data, indent=2)[:3000]}")
        return data

    @staticmethod
    def _normalize_title(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (value or "").strip().lower()).strip()

    def load_schema(self) -> tuple[dict[str, ColumnInfo], list[dict]]:
        if self._columns is not None and self._groups is not None:
            return self._columns, self._groups

        query = """
        query SponsorBoardSchema($board_id: ID!) {
          boards(ids: [$board_id]) {
            id
            name
            groups { id title }
            columns { id title type }
          }
        }
        """
        data = self._request(query, {"board_id": self.board_id})
        boards = data.get("data", {}).get("boards", [])
        if not boards:
            raise RuntimeError(f"Sponsor monday board {self.board_id} was not found or is not accessible.")
        board = boards[0]
        self._groups = board.get("groups", []) or []

        raw_columns = [ColumnInfo(id=c["id"], title=c.get("title", ""), type=c.get("type", "")) for c in board.get("columns", [])]
        by_title = {self._normalize_title(column.title): column for column in raw_columns}
        resolved: dict[str, ColumnInfo] = {}
        for field, aliases in COLUMN_ALIASES.items():
            for alias in aliases:
                column = by_title.get(self._normalize_title(alias))
                if column:
                    resolved[field] = column
                    break
        self._columns = resolved
        return resolved, self._groups

    def resolved_group_id(self) -> str:
        _, groups = self.load_schema()
        if self.requested_group_id:
            if any(group.get("id") == self.requested_group_id for group in groups):
                return self.requested_group_id
            raise RuntimeError(f"SPONSOR_MONDAY_GROUP_ID {self.requested_group_id!r} is not on board {self.board_id}.")

        for group in groups:
            if self._normalize_title(group.get("title", "")) in {"new leads", "new lead", "leads"}:
                return group.get("id", "")
        return groups[0].get("id", "") if groups else ""

    def _dedupe_column_ids(self) -> list[str]:
        columns, _ = self.load_schema()
        fields = ["brand_name", "brand_domain", "contact_email", "brand_key", "sponsorship_key", "outreach_status"]
        return [columns[field].id for field in fields if field in columns]

    @staticmethod
    def _column_fragment(column_ids: list[str]) -> str:
        if not column_ids:
            return "column_values { id text value }"
        safe = [column_id for column_id in column_ids if re.fullmatch(r"[A-Za-z0-9_]+", column_id)]
        quoted = ", ".join(json.dumps(column_id) for column_id in safe)
        return f"column_values(ids: [{quoted}]) {{ id text value }}"

    def _get_all_items(self) -> list[dict]:
        column_fragment = self._column_fragment(self._dedupe_column_ids())
        initial_query = f"""
        query SponsorItems($board_id: ID!) {{
          boards(ids: [$board_id]) {{
            items_page(limit: 500) {{
              cursor
              items {{ id name {column_fragment} }}
            }}
          }}
        }}
        """
        data = self._request(initial_query, {"board_id": self.board_id})
        boards = data.get("data", {}).get("boards", [])
        if not boards:
            return []
        page = boards[0].get("items_page", {}) or {}
        items = list(page.get("items", []) or [])
        cursor = page.get("cursor")

        next_query = f"""
        query NextSponsorItems($cursor: String!) {{
          next_items_page(limit: 500, cursor: $cursor) {{
            cursor
            items {{ id name {column_fragment} }}
          }}
        }}
        """
        while cursor:
            next_data = self._request(next_query, {"cursor": cursor})
            page = next_data.get("data", {}).get("next_items_page", {}) or {}
            items.extend(page.get("items", []) or [])
            cursor = page.get("cursor")
        return items

    def load_existing_index(self) -> ExistingSponsorIndex:
        columns, _ = self.load_schema()
        id_to_field = {column.id: field for field, column in columns.items()}
        index = ExistingSponsorIndex()

        for item in self._get_all_items():
            keys: set[str] = set()
            item_brand = normalize_brand_name(item.get("name", ""))
            if item_brand:
                keys.add(f"brand:{item_brand}")

            values: dict[str, str] = {}
            for column in item.get("column_values", []) or []:
                field = id_to_field.get(column.get("id", ""))
                if field:
                    values[field] = column.get("text") or ""

            brand_name = normalize_brand_name(values.get("brand_name", ""))
            domain = normalize_domain(values.get("brand_domain", ""))
            email = normalize_email(values.get("contact_email", ""))
            e_domain = email_domain(email)
            brand_key = normalize_text(values.get("brand_key", ""))
            event_key = normalize_text(values.get("sponsorship_key", ""))
            status = normalize_text(values.get("outreach_status", ""))

            if brand_name:
                keys.add(f"brand:{brand_name}")
            if domain:
                keys.add(f"domain:{domain}")
            if email:
                keys.add(f"email:{email}")
            if e_domain:
                keys.add(f"domain:{e_domain}")
            if brand_key:
                keys.add(brand_key)

            index.brand_keys.update(keys)
            if event_key:
                index.event_keys.add(event_key)
            if status in PROTECTED_OUTREACH_STATUSES:
                index.protected_brand_keys.update(keys)

        print(
            f"Daily monday duplicate scan: {len(index.brand_keys)} brand keys and "
            f"{len(index.event_keys)} sponsorship events loaded from the full board."
        )
        return index

    @staticmethod
    def _column_value(column: ColumnInfo, field: str, value: object, lead: SponsorLead) -> object | None:
        if value in (None, "", []):
            return None
        column_type = (column.type or "").lower()

        if column_type == "email":
            text = str(value)
            return {"email": text, "text": text}
        if column_type == "link":
            url = str(value)
            labels = {
                "brand_domain": lead.brand_name or "Website",
                "creator_url": lead.creator_name or "Creator",
                "video_url": "Sponsored Video",
                "contact_source": "Email Source",
            }
            return {"url": url if "://" in url else f"https://{url}", "text": labels.get(field, url)[:255]}
        if column_type == "date":
            return {"date": str(value)[:10]}
        if column_type == "status":
            return {"label": str(value)}
        if column_type == "dropdown":
            labels = value if isinstance(value, list) else [str(value)]
            return {"labels": [str(label)[:255] for label in labels if str(label).strip()]}
        if column_type == "checkbox":
            checked = bool(value) and str(value).lower() not in {"false", "0", "no"}
            return {"checked": "true" if checked else "false"}
        if column_type in {"numbers", "numeric"}:
            return str(value)
        return ", ".join(map(str, value)) if isinstance(value, list) else str(value)

    def _build_values(self, lead: SponsorLead) -> dict:
        columns, _ = self.load_schema()
        raw = lead.as_dict()
        raw["outreach_status"] = "New Lead"
        values: dict[str, object] = {}
        for field, column in columns.items():
            value = raw.get(field)
            formatted = self._column_value(column, field, value, lead)
            if formatted not in (None, "", {}):
                values[column.id] = formatted
        return values

    def create_lead(self, lead: SponsorLead) -> dict:
        group_id = self.resolved_group_id()
        column_values = self._build_values(lead)
        mutation = """
        mutation CreateSponsorLead($board_id: ID!, $item_name: String!, $column_values: JSON!, $group_id: String) {
          create_item(
            board_id: $board_id,
            group_id: $group_id,
            item_name: $item_name,
            column_values: $column_values,
            create_labels_if_missing: true
          ) { id name }
        }
        """
        variables = {
            "board_id": self.board_id,
            "group_id": group_id or None,
            "item_name": lead.brand_name,
            "column_values": json.dumps(column_values),
        }
        return self._request(mutation, variables)
