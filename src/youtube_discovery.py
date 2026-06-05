import argparse
import os
import time
from datetime import date

import requests
from dotenv import load_dotenv

from email_utils import first_email
from monday_client import create_creator_item, GROUP_IDS

load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


def youtube_get(endpoint: str, params: dict) -> dict:
    if not YOUTUBE_API_KEY:
        raise ValueError("Missing YOUTUBE_API_KEY. Add it to your .env file or GitHub Secrets.")

    params = {**params, "key": YOUTUBE_API_KEY}
    response = requests.get(f"{YOUTUBE_API_BASE}/{endpoint}", params=params, timeout=30)
    data = response.json()

    if response.status_code != 200 or "error" in data:
        raise RuntimeError(f"YouTube API error: {data}")

    return data


def search_channels(keyword: str, max_results: int = 25, page_token: str | None = None) -> dict:
    params = {
        "part": "snippet",
        "type": "channel",
        "q": keyword,
        "maxResults": min(max_results, 50),
    }
    if page_token:
        params["pageToken"] = page_token

    return youtube_get("search", params)


def get_channel_details(channel_ids: list[str]) -> list[dict]:
    if not channel_ids:
        return []

    data = youtube_get(
        "channels",
        {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(channel_ids),
            "maxResults": 50,
        },
    )

    return data.get("items", [])


def get_recent_video_average(channel_id: str, limit: int = 5) -> int:
    data = youtube_get(
        "search",
        {
            "part": "snippet",
            "channelId": channel_id,
            "type": "video",
            "order": "date",
            "maxResults": min(limit, 10),
        },
    )

    video_ids = [item["id"]["videoId"] for item in data.get("items", []) if item.get("id", {}).get("videoId")]

    if not video_ids:
        return 0

    video_data = youtube_get(
        "videos",
        {
            "part": "statistics",
            "id": ",".join(video_ids),
            "maxResults": len(video_ids),
        },
    )

    views = []
    for item in video_data.get("items", []):
        view_count = item.get("statistics", {}).get("viewCount")
        if view_count:
            views.append(int(view_count))

    if not views:
        return 0

    return round(sum(views) / len(views))


def infer_creator_size(subscribers: int) -> str:
    if subscribers >= 1_000_000:
        return "Macro: 1M+"
    if subscribers >= 500_000:
        return "Large: 500k–1M"
    if subscribers >= 100_000:
        return "Mid: 100k–500k"
    if subscribers >= 10_000:
        return "Micro: 10k–100k"
    if subscribers > 0:
        return "Nano: Under 10k"
    return "Unknown"


def channel_to_creator(channel: dict, keyword: str, niche: str = "") -> dict:
    snippet = channel.get("snippet", {})
    stats = channel.get("statistics", {})
    channel_id = channel.get("id", "")

    title = snippet.get("title", "")
    description = snippet.get("description", "")
    custom_url = snippet.get("customUrl", "")
    country = snippet.get("country", "")

    subscribers = int(stats.get("subscriberCount", 0)) if stats.get("subscriberCount") else 0
    profile_url = f"https://www.youtube.com/channel/{channel_id}" if channel_id else ""
    handle = custom_url if custom_url else channel_id
    public_email = first_email(description)

    creator = {
        "name": title,
        "creator_name": title,
        "handle": handle,
        "platform": "YouTube",
        "public_email": public_email,
        "profile_url": profile_url,
        "followers": str(subscribers),
        "engagement_rate": "",
        "bio": description[:1800],
        "location": country,
        "country": country if country else "Unknown",
        "niche": niche or keyword,
        "creator_type": "Individual Creator",
        "creator_gender": "Unknown",
        "outreach_status": "Not Contacted",
        "tier": "Not Yet Tiered",
        "headhunter": "Unassigned",
        "date_added": date.today().isoformat(),
        "last_posted_date": "",
        "last_contacted": "",
    }

    return creator


def discover_youtube_creators(
    keyword: str,
    niche: str = "",
    min_subscribers: int = 0,
    max_creators: int = 25,
    require_email: bool = False,
    group_key: str = "new_leads",
    sleep_seconds: float = 0.2,
) -> None:
    group_id = GROUP_IDS.get(group_key)
    if not group_id:
        raise ValueError(f"Invalid group key: {group_key}")

    created_count = 0
    page_token = None

    while created_count < max_creators:
        batch_size = min(50, max_creators - created_count)
        search_data = search_channels(keyword, max_results=batch_size, page_token=page_token)
        channel_ids = [item["snippet"]["channelId"] for item in search_data.get("items", [])]
        details = get_channel_details(channel_ids)

        if not details:
            break

        for channel in details:
            creator = channel_to_creator(channel, keyword=keyword, niche=niche)
            subscribers = int(creator.get("followers") or 0)

            if subscribers < min_subscribers:
                continue
            if require_email and not creator.get("public_email"):
                continue

            try:
                result = create_creator_item(creator, group_id=group_id)
                item = result["data"]["create_item"]
                print(f"Created: {item['name']} / {creator['followers']} subscribers / email: {creator['public_email'] or 'none'}")
                created_count += 1
                time.sleep(sleep_seconds)
            except Exception as error:
                print(f"Failed creator: {creator.get('creator_name')} / error: {error}")

            if created_count >= max_creators:
                break

        page_token = search_data.get("nextPageToken")
        if not page_token:
            break

    print(f"Done. Created {created_count} creator leads for keyword: {keyword}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Discover YouTube creators and send them to monday.com.")
    parser.add_argument("--keyword", required=True, help="Search keyword, like Minecraft YouTuber or beauty creator")
    parser.add_argument("--niche", default="", help="monday niche label, like Minecraft, Beauty, Tech, Family")
    parser.add_argument("--min-subscribers", type=int, default=0, help="Minimum subscriber count")
    parser.add_argument("--max-creators", type=int, default=25, help="Maximum creators to add")
    parser.add_argument("--require-email", action="store_true", help="Only add channels with public emails in description")
    parser.add_argument("--group", default="new_leads", help="monday group key")

    args = parser.parse_args()

    discover_youtube_creators(
        keyword=args.keyword,
        niche=args.niche,
        min_subscribers=args.min_subscribers,
        max_creators=args.max_creators,
        require_email=args.require_email,
        group_key=args.group,
    )
