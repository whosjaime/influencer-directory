import argparse
import html
import re
import time
from datetime import date
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests
from dotenv import load_dotenv

from dedupe_utils import creator_keys, is_blocked_creator, load_blocklist
from email_utils import first_email
from monday_client import create_creator_item, get_existing_creator_keys, GROUP_IDS

load_dotenv()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ManifestMediaLeadResearch/1.0; +https://github.com/whosjaime/influencer-directory)",
    "Accept-Language": "en-US,en;q=0.9",
}

SOCIAL_PATTERNS = {
    "instagram": re.compile(r"https?://(?:www\.)?instagram\.com/[A-Za-z0-9._]+/?", re.I),
    "tiktok": re.compile(r"https?://(?:www\.)?tiktok\.com/@[A-Za-z0-9._-]+/?", re.I),
}

BAD_PATH_PARTS = {
    "instagram": {"p", "reel", "reels", "stories", "explore", "accounts", "about", "developer", "directory"},
    "tiktok": {"tag", "music", "discover", "channel", "following", "live"},
}


def http_get(url: str, timeout: int = 25) -> str:
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    if response.status_code >= 400:
        return ""
    return response.text or ""


def unwrap_duckduckgo_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if "uddg" in query:
        return unquote(query["uddg"][0])
    return url


def is_valid_profile_url(platform: str, url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return False

    first_part = path.split("/")[0].lower()
    if first_part in BAD_PATH_PARTS.get(platform, set()):
        return False

    if platform == "instagram":
        return "instagram.com" in parsed.netloc and len(path.split("/")) == 1

    if platform == "tiktok":
        return "tiktok.com" in parsed.netloc and first_part.startswith("@")

    return False


def normalize_profile_url(platform: str, url: str) -> str:
    url = url.split("?")[0].split("#")[0].rstrip("/")
    parsed = urlparse(url)
    path = parsed.path.strip("/")

    if platform == "instagram":
        handle = path.split("/")[0]
        return f"https://www.instagram.com/{handle}/"

    if platform == "tiktok":
        handle = path.split("/")[0]
        return f"https://www.tiktok.com/{handle}"

    return url


def extract_handle(platform: str, profile_url: str) -> str:
    parsed = urlparse(profile_url)
    path = parsed.path.strip("/")
    if not path:
        return ""
    handle = path.split("/")[0]
    return handle if handle.startswith("@") else f"@{handle}"


def search_duckduckgo(platform: str, search: str, max_results: int) -> list[str]:
    site = "instagram.com" if platform == "instagram" else "tiktok.com/@"
    query = f"site:{site} {search}"
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    html_text = http_get(url)
    if not html_text:
        return []

    html_text = html.unescape(html_text)
    candidates = []

    for href in re.findall(r'href="([^"]+)"', html_text):
        href = unwrap_duckduckgo_url(href)
        for match in SOCIAL_PATTERNS[platform].findall(href):
            normalized = normalize_profile_url(platform, match)
            if is_valid_profile_url(platform, normalized) and normalized not in candidates:
                candidates.append(normalized)
                if len(candidates) >= max_results:
                    return candidates

    # Fallback: scan full HTML text for social URLs.
    for match in SOCIAL_PATTERNS[platform].findall(html_text):
        normalized = normalize_profile_url(platform, match)
        if is_valid_profile_url(platform, normalized) and normalized not in candidates:
            candidates.append(normalized)
            if len(candidates) >= max_results:
                break

    return candidates


def extract_meta_description(html_text: str) -> str:
    patterns = [
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text, re.I | re.S)
        if match:
            return html.unescape(match.group(1)).strip()
    return ""


def extract_title(html_text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.I | re.S)
    if not match:
        return ""
    title = html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    title = title.replace("• Instagram photos and videos", "").replace("| TikTok", "").strip(" -")
    return title


def fetch_public_profile(platform: str, profile_url: str) -> dict[str, str]:
    page = http_get(profile_url)
    bio = extract_meta_description(page) if page else ""
    title = extract_title(page) if page else ""
    public_email = first_email(bio)
    handle = extract_handle(platform, profile_url)

    creator_name = title or handle
    if platform == "instagram" and "Instagram" in creator_name:
        creator_name = handle
    if platform == "tiktok" and "TikTok" in creator_name:
        creator_name = handle

    return {
        "creator_name": creator_name,
        "handle": handle,
        "bio": bio,
        "public_email": public_email,
    }


def profile_to_creator(platform: str, profile_url: str, search: str, niche: str, creator_gender: str) -> dict[str, str]:
    profile = fetch_public_profile(platform, profile_url)
    platform_label = "Instagram" if platform == "instagram" else "TikTok"
    handle = profile.get("handle") or extract_handle(platform, profile_url)
    creator_name = profile.get("creator_name") or handle

    return {
        "name": creator_name,
        "creator_name": creator_name,
        "handle": handle,
        "platform": platform_label,
        "public_email": profile.get("public_email", ""),
        "profile_url": profile_url,
        "followers": "",
        "engagement_rate": "",
        "bio": profile.get("bio", "")[:1800],
        "location": "",
        "country": "Unknown",
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


def has_duplicate_key(creator: dict, existing_keys: set[str]) -> bool:
    return any(key in existing_keys for key in creator_keys(creator))


def discover_public_social_creators(
    platform: str,
    search: str,
    niche: str = "",
    max_creators: int = 100,
    group_key: str = "new_leads",
    creator_gender: str = "Unknown",
    delay_seconds: float = 1.0,
) -> None:
    platform = platform.lower().strip()
    if platform not in ["instagram", "tiktok"]:
        raise ValueError("Platform must be instagram or tiktok.")

    group_id = GROUP_IDS.get(group_key)
    if not group_id:
        raise ValueError(f"Invalid group key: {group_key}")

    blocklist = load_blocklist()
    existing_keys = get_existing_creator_keys()
    run_keys = set()

    urls = search_duckduckgo(platform, search, max_creators)
    print(f"Found {len(urls)} candidate {platform} profile URLs for search: {search}")

    created_count = 0
    skipped_duplicates = 0
    skipped_existing = 0
    skipped_blocked = 0

    for profile_url in urls:
        creator = profile_to_creator(platform, profile_url, search, niche, creator_gender)
        current_keys = creator_keys(creator)

        if is_blocked_creator(creator, blocklist):
            skipped_blocked += 1
            print(f"Skipped blocklisted creator: {creator.get('creator_name')} / {creator.get('handle')}")
            continue
        if any(key in run_keys for key in current_keys):
            skipped_duplicates += 1
            print(f"Skipped duplicate from this run: {creator.get('creator_name')} / {creator.get('handle')}")
            continue
        if has_duplicate_key(creator, existing_keys):
            skipped_existing += 1
            print(f"Skipped existing monday creator: {creator.get('creator_name')} / {creator.get('handle')}")
            continue

        run_keys.update(current_keys)
        existing_keys.update(current_keys)

        try:
            result = create_creator_item(creator, group_id=group_id)
            item_result = result["data"]["create_item"]
            print(
                f"Created: {item_result['name']} / {creator['platform']} / "
                f"email: {creator['public_email'] or 'blank'} / {creator['profile_url']}"
            )
            created_count += 1
            time.sleep(delay_seconds)
        except Exception as error:
            print(f"Failed creator: {creator.get('creator_name')} / error: {error}")

    print(
        f"Done. Created {created_count} {platform} creator leads for search: {search}. "
        f"Skipped {skipped_duplicates} same-run duplicates, {skipped_existing} existing monday creators, "
        f"and {skipped_blocked} blocklisted creators."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Discover public Instagram or TikTok creators without Apify and send them to monday.com.")
    parser.add_argument("--platform", required=True, choices=["instagram", "tiktok"], help="instagram or tiktok")
    parser.add_argument("--search", required=True, help="Search keyword, hashtag, niche, or creator category")
    parser.add_argument("--niche", default="", help="monday niche label, like Comedy, Beauty, Fitness, Gaming, Fashion")
    parser.add_argument("--max-creators", type=int, default=100, help="Maximum creators to add")
    parser.add_argument("--group", default="new_leads", help="monday group key")
    parser.add_argument("--creator-gender", default="Unknown", choices=["Woman", "Man", "Non-binary", "Mixed Team", "Unknown"], help="Gender tag to apply to this search batch")

    args = parser.parse_args()

    discover_public_social_creators(
        platform=args.platform,
        search=args.search,
        niche=args.niche,
        max_creators=args.max_creators,
        group_key=args.group,
        creator_gender=args.creator_gender,
    )
