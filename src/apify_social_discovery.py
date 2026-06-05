import argparse
import os
import time
from datetime import date
from typing import Any

import requests
from dotenv import load_dotenv

from email_utils import first_email
from monday_client import create_creator_item, GROUP_IDS

load_dotenv()

APIFY_TOKEN = os.getenv("APIFY_TOKEN")
APIFY_BASE_URL = "https://api.apify.com/v2"

DEFAULT_ACTORS = {
    "instagram": os.getenv("APIFY_INSTAGRAM_ACTOR_ID", "apify/instagram-scraper"),
    "tiktok": os.getenv("APIFY_TIKTOK_ACTOR_ID", "clockworks/tiktok-scraper"),
}


def apify_request(method: str, url: str, **kwargs) -> requests.Response:
    if not APIFY_TOKEN:
        raise ValueError("Missing APIFY_TOKEN. Add it to your .env file or GitHub Secrets.")

    params = kwargs.pop("params", {}) or {}
    params["token"] = APIFY_TOKEN
    response = requests.request(method, url, params=params, timeout=120, **kwargs)
    return response


def build_actor_input(platform: str, search: str, max_results: int) -> dict[str, Any]:
    platform = platform.lower().strip()

    if platform == "instagram":
        return {
            "search": search,
            "searchType": "user",
            "resultsLimit": max_results,
            "addParentData": False,
        }

    if platform == "tiktok":
        return {
            "searchQueries": [search],
            "maxItems": max_results,
            "shouldDownloadVideos": False,
            "shouldDownloadCovers": False,
            "shouldDownloadSubtitles": False,
            "shouldDownloadSlideshowImages": False,
        }

    raise ValueError("Platform must be instagram or tiktok.")


def run_actor(platform: str, search: str, max_results: int) -> list[dict[str, Any]]:
    actor_id = DEFAULT_ACTORS[platform]
    actor_input = build_actor_input(platform, search, max_results)

    start_url = f"{APIFY_BASE_URL}/acts/{actor_id}/runs"
    start_response = apify_request("POST", start_url, json=actor_input)

    try:
        start_data = start_response.json()
    except Exception as exc:
        raise RuntimeError(f"Invalid Apify start response: {start_response.text}") from exc

    if start_response.status_code not in [200, 201] or "data" not in start_data:
        raise RuntimeError(f"Apify actor start failed: {start_data}")

    run_id = start_data["data"]["id"]
    status_url = f"{APIFY_BASE_URL}/actor-runs/{run_id}"

    while True:
        status_response = apify_request("GET", status_url)
        status_data = status_response.json()
        status = status_data.get("data", {}).get("status")

        if status in ["SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"]:
            break

        print(f"Apify run status: {status}. Waiting...")
        time.sleep(10)

    if status != "SUCCEEDED":
        raise RuntimeError(f"Apify actor did not succeed. Final status: {status}")

    dataset_id = status_data["data"].get("defaultDatasetId")
    if not dataset_id:
        return []

    items_url = f"{APIFY_BASE_URL}/datasets/{dataset_id}/items"
    items_response = apify_request("GET", items_url, params={"clean": "true", "limit": max_results})
    items = items_response.json()

    if not isinstance(items, list):
        raise RuntimeError(f"Unexpected Apify dataset response: {items}")

    return items


def first_available(item: dict[str, Any], keys: list[str], default: Any = "") -> Any:
    for key in keys:
        value = item.get(key)
        if value not in [None, "", [], {}]:
            return value
    return default


def number_to_string(value: Any) -> str:
    if value in [None, ""]:
        return ""
    try:
        return str(int(float(value)))
    except Exception:
        return str(value)


def normalize_profile_url(platform: str, handle: str, url: str = "") -> str:
    if url:
        return url

    clean_handle = handle.lstrip("@")
    if not clean_handle:
        return ""

    if platform == "instagram":
        return f"https://www.instagram.com/{clean_handle}/"
    if platform == "tiktok":
        return f"https://www.tiktok.com/@{clean_handle}"
    return ""


def item_to_creator(item: dict[str, Any], platform: str, niche: str, search: str, creator_gender: str = "Unknown") -> dict[str, str]:
    platform = platform.lower().strip()
    platform_label = "Instagram" if platform == "instagram" else "TikTok"

    username = first_available(item, ["username", "userName", "uniqueId", "authorMeta.name", "handle"])
    if isinstance(username, dict):
        username = first_available(username, ["name", "username", "uniqueId"])

    full_name = first_available(item, ["fullName", "name", "nickname", "authorMeta.nickName", "displayName"], username)
    bio = first_available(item, ["biography", "bio", "signature", "description", "authorMeta.signature"], "")
    followers = first_available(item, ["followersCount", "followerCount", "fans", "authorMeta.fans", "subscribers"], "")
    profile_url = first_available(item, ["url", "profileUrl", "webVideoUrl", "authorMeta.profileUrl"], "")
    public_email = first_available(item, ["email", "publicEmail", "businessEmail"], "") or first_email(str(bio))
    location = first_available(item, ["location", "city", "country", "region"], "")
    country = first_available(item, ["country", "region"], "Unknown")

    handle = str(username or "").strip()
    if handle and not handle.startswith("@"):
        handle = f"@{handle}"

    profile_url = normalize_profile_url(platform, handle, str(profile_url or ""))

    return {
        "name": str(full_name or handle),
        "creator_name": str(full_name or handle),
        "handle": handle,
        "platform": platform_label,
        "public_email": str(public_email or ""),
        "profile_url": profile_url,
        "followers": number_to_string(followers),
        "engagement_rate": "",
        "bio": str(bio or "")[:1800],
        "location": str(location or ""),
        "country": str(country or "Unknown"),
        "niche": niche or search,
        "creator_type": "Individual Creator",
        "creator_gender": creator_gender,
        "outreach_status": "Not Contacted",
        "tier": "Not Yet Tiered",
        "headhunter": "Unassigned",
        "date_added": date.today().isoformat(),
        "last_posted_date": "",
        "last_contacted": "",
    }


def discover_social_creators(
    platform: str,
    search: str,
    niche: str = "",
    max_creators: int = 25,
    min_followers: int = 0,
    group_key: str = "new_leads",
    creator_gender: str = "Unknown",
) -> None:
    platform = platform.lower().strip()
    if platform not in ["instagram", "tiktok"]:
        raise ValueError("Platform must be instagram or tiktok.")

    group_id = GROUP_IDS.get(group_key)
    if not group_id:
        raise ValueError(f"Invalid group key: {group_key}")

    items = run_actor(platform=platform, search=search, max_results=max_creators)
    created_count = 0

    for item in items:
        creator = item_to_creator(item, platform=platform, niche=niche, search=search, creator_gender=creator_gender)
        followers_raw = creator.get("followers") or "0"

        try:
            followers = int(float(followers_raw))
        except Exception:
            followers = 0

        if followers < min_followers:
            continue
        if not creator.get("handle") and not creator.get("creator_name"):
            continue

        try:
            result = create_creator_item(creator, group_id=group_id)
            item_result = result["data"]["create_item"]
            print(
                f"Created: {item_result['name']} / {creator['platform']} / "
                f"{creator['followers']} followers / email: {creator['public_email'] or 'blank'}"
            )
            created_count += 1
        except Exception as error:
            print(f"Failed creator: {creator.get('creator_name')} / error: {error}")

    print(f"Done. Created {created_count} {platform} creator leads for search: {search}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Discover Instagram or TikTok creators through Apify and send them to monday.com.")
    parser.add_argument("--platform", required=True, choices=["instagram", "tiktok"], help="instagram or tiktok")
    parser.add_argument("--search", required=True, help="Search keyword, hashtag, niche, or creator category")
    parser.add_argument("--niche", default="", help="monday niche label, like Beauty, Fitness, Gaming, Fashion")
    parser.add_argument("--max-creators", type=int, default=25, help="Maximum creators to add")
    parser.add_argument("--min-followers", type=int, default=0, help="Minimum follower count")
    parser.add_argument("--group", default="new_leads", help="monday group key")
    parser.add_argument("--creator-gender", default="Unknown", choices=["Woman", "Man", "Non-binary", "Mixed Team", "Unknown"], help="Gender tag to apply to this search batch")

    args = parser.parse_args()

    discover_social_creators(
        platform=args.platform,
        search=args.search,
        niche=args.niche,
        max_creators=args.max_creators,
        min_followers=args.min_followers,
        group_key=args.group,
        creator_gender=args.creator_gender,
    )
