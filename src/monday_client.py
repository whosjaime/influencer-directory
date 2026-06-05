import json
import requests
from config import MONDAY_TOKEN, MONDAY_BOARD_ID, MONDAY_DEFAULT_GROUP_ID

MONDAY_API_URL = "https://api.monday.com/v2"

HEADERS = {
    "Authorization": MONDAY_TOKEN,
    "Content-Type": "application/json",
    "API-Version": "2025-04",
}

COLUMN_IDS = {
    "outreach_status": "color_mm4185f6",
    "tier": "color_mm41a1b0",
    "headhunter": "color_mm413k3m",
    "followers": "numeric_mm41rm3s",
    "handle": "text_mm41z276",
    "platform": "dropdown_mm41fn22",
    "public_email": "email_mm41zs1s",
    "creator_name": "text_mm41bddw",
    "last_posted_date": "date_mm41savv",
    "creator_type": "dropdown_mm414dr3",
    "last_contacted": "date_mm4191xe",
    "date_added": "date_mm418sy2",
    "niche": "dropdown_mm41g7af",
    "engagement_rate": "numeric_mm41dtpe",
    "bio": "long_text_mm41xm9j",
    "location": "text_mm41c0pf",
    "country": "dropdown_mm41wnna",
    "profile_url": "link_mm417svc",
    "creator_gender": "dropdown_mm413aa2",
}

GROUP_IDS = {
    "new_leads": "group_mm41wfhq",
    "needs_review": "group_mm41rfsm",
    "outreach_sent": "group_mm41qywz",
    "in_conversation": "group_mm419y5e",
    "booked_call": "group_mm41w4m2",
    "do_not_contact": "group_mm418gan",
    "contacted": "group_mm41ywnh",
    "not_a_fit": "group_mm41x4x9",
}


def monday_request(query: str, variables: dict) -> dict:
    response = requests.post(
        MONDAY_API_URL,
        headers=HEADERS,
        json={"query": query, "variables": variables},
        timeout=30,
    )

    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError(f"Invalid monday response: {response.text}") from exc

    if response.status_code != 200 or "errors" in data:
        raise RuntimeError(f"monday API error: {json.dumps(data, indent=2)}")

    return data


def status_value(label: str) -> dict | None:
    if not label:
        return None
    return {"label": label}


def dropdown_value(label: str) -> dict | None:
    if not label:
        return None
    return {"labels": [label]}


def date_value(date_string: str) -> dict | None:
    if not date_string:
        return None
    return {"date": date_string}


def email_value(email: str) -> dict | None:
    if not email:
        return None
    return {"email": email, "text": email}


def link_value(url: str, text: str = "Profile") -> dict | None:
    if not url:
        return None
    return {"url": url, "text": text or url}


def clean_column_values(values: dict) -> dict:
    return {key: value for key, value in values.items() if value not in [None, "", {}]}


def build_creator_column_values(creator: dict) -> dict:
    profile_url = creator.get("profile_url", "")
    creator_name = creator.get("creator_name", "") or creator.get("name", "")

    values = {
        COLUMN_IDS["creator_name"]: creator_name,
        COLUMN_IDS["handle"]: creator.get("handle", ""),
        COLUMN_IDS["platform"]: dropdown_value(creator.get("platform", "")),
        COLUMN_IDS["public_email"]: email_value(creator.get("public_email", "")),
        COLUMN_IDS["profile_url"]: link_value(profile_url, creator_name or "Profile"),
        COLUMN_IDS["followers"]: creator.get("followers", ""),
        COLUMN_IDS["engagement_rate"]: creator.get("engagement_rate", ""),
        COLUMN_IDS["bio"]: creator.get("bio", ""),
        COLUMN_IDS["location"]: creator.get("location", ""),
        COLUMN_IDS["country"]: dropdown_value(creator.get("country", "")),
        COLUMN_IDS["niche"]: dropdown_value(creator.get("niche", "")),
        COLUMN_IDS["creator_type"]: dropdown_value(creator.get("creator_type", "")),
        COLUMN_IDS["creator_gender"]: dropdown_value(creator.get("creator_gender", "")),
        COLUMN_IDS["outreach_status"]: status_value(creator.get("outreach_status", "Not Contacted")),
        COLUMN_IDS["tier"]: status_value(creator.get("tier", "Not Yet Tiered")),
        COLUMN_IDS["headhunter"]: status_value(creator.get("headhunter", "Unassigned")),
        COLUMN_IDS["date_added"]: date_value(creator.get("date_added", "")),
        COLUMN_IDS["last_posted_date"]: date_value(creator.get("last_posted_date", "")),
        COLUMN_IDS["last_contacted"]: date_value(creator.get("last_contacted", "")),
    }

    return clean_column_values(values)


def create_creator_item(creator: dict, group_id: str = MONDAY_DEFAULT_GROUP_ID) -> dict:
    item_name = creator.get("name") or creator.get("creator_name") or creator.get("handle")

    if not item_name:
        raise ValueError("Creator must have a name, creator_name, or handle.")

    column_values = build_creator_column_values(creator)

    mutation = """
    mutation CreateCreatorItem(
        $board_id: ID!,
        $group_id: String!,
        $item_name: String!,
        $column_values: JSON!
    ) {
        create_item(
            board_id: $board_id,
            group_id: $group_id,
            item_name: $item_name,
            column_values: $column_values,
            create_labels_if_missing: true
        ) {
            id
            name
        }
    }
    """

    variables = {
        "board_id": MONDAY_BOARD_ID,
        "group_id": group_id,
        "item_name": item_name,
        "column_values": json.dumps(column_values),
    }

    return monday_request(mutation, variables)
