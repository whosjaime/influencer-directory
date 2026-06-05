import argparse
import html
import os
import re
import time
from datetime import date
from urllib.parse import quote_plus, urlparse

import requests
from dotenv import load_dotenv

from dedupe_utils import creator_keys, is_blocked_creator, load_blocklist
from email_utils import first_email
from monday_client import create_creator_item, get_existing_creator_keys, GROUP_IDS

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")
BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

PATTERNS = {
    "instagram": re.compile(r"https?://(?:www\.)?instagram\.com/[A-Za-z0-9._]+/?", re.I),
    "tiktok": re.compile(r"https?://(?:www\.)?tiktok\.com/@[A-Za-z0-9._-]+/?", re.I),
}

BAD_PATHS = {
    "instagram": {"p", "reel", "reels", "stories", "explore", "accounts", "about", "developer", "directory"},
    "tiktok": {"tag", "music", "discover", "channel", "following", "live", "login", "signup"},
}

SEEDS = [
    "male entertainment creator United States",
    "male comedy skits creator United States",
    "male prank creator United States",
    "male challenge creator United States",
    "happy energetic comedy creator United States",
]


def http_get(url: str, timeout: int = 25) -> str:
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout)
        if response.status_code >= 400:
            return ""
        return response.text or ""
    except Exception:
        return ""


def is_valid_profile(platform: str, url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return False

    first = path.split("/")[0].lower()
    if first in BAD_PATHS.get(platform, set()):
        return False

    if platform == "instagram":
        return "instagram.com" in parsed.netloc and len(path.split("/")) == 1
    if platform == "tiktok":
        return "tiktok.com" in parsed.netloc and first.startswith("@")
    return False


def normalize_url(platform: str, url: str) -> str:
    url = html.unescape(url).split("?")[0].split("#")[0].rstrip("/")
    parsed = urlparse(url)
    path = parsed.path.strip("/")

    if platform == "instagram":
        return f"https://www.instagram.com/{path.split('/')[0]}/"
    if platform == "tiktok":
        return f"https://www.tiktok.com/{path.split('/')[0]}"
    return url


def handle_from_url(platform: str, url: str) -> str:
    path = urlparse(url).path.strip("/")
    if not path:
        return ""
    handle = path.split("/")[0]
    return handle if handle.startswith("@") else f"@{handle}"


def add_urls(platform: str, text: str, found: list[str], limit: int) -> list[str]:
    text = html.unescape(text or "")
    for match in PATTERNS[platform].findall(text):
        normalized = normalize_url(platform, match)
        if is_valid_profile(platform, normalized) and normalized not in found:
            found.append(normalized)
            if len(found) >= limit:
                return found
    return found


def build_queries(platform: str, search: str) -> list[str]:
    site = "site:instagram.com" if platform == "instagram" else "site:tiktok.com/@"
    base = [search, f"{search} influencer", f"{search} creator"] + SEEDS
    return [f"{site} {q}" for q in base]


def google_search(platform: str, query: str, limit: int, found: list[str]) -> list[str]:
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        return found

    for start in [1, 11, 21, 31, 41]:
        if len(found) >= limit:
            break
        params = {
            "key": GOOGLE_API_KEY,
            "cx": GOOGLE_CSE_ID,
            "q": query,
            "num": 10,
            "start": start,
        }
        try:
            response = requests.get("https://www.googleapis.com/customsearch/v1", params=params, timeout=30)
            data = response.json()
        except Exception as error:
            print(f"Google search failed: {error}")
            break

        if response.status_code >= 400:
            print(f"Google search API error {response.status_code}: {data}")
            break

        for item in data.get("items", []):
            for key in ["link", "snippet", "title"]:
                found = add_urls(platform, item.get(key, ""), found, limit)
                if len(found) >= limit:
                    return found
    return found


def brave_search(platform: str, query: str, limit: int, found: list[str]) -> list[str]:
    if not BRAVE_SEARCH_API_KEY:
        return found

    headers = {"Accept": "application/json", "X-Subscription-Token": BRAVE_SEARCH_API_KEY}
    for offset in [0, 20, 40]:
        if len(found) >= limit:
            break
        try:
            response = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers=headers,
                params={"q": query, "count": 20, "offset": offset},
                timeout=30,
            )
            data = response.json()
        except Exception as error:
            print(f"Brave search failed: {error}")
            break

        if response.status_code >= 400:
            print(f"Brave search API error {response.status_code}: {data}")
            break

        for item in data.get("web", {}).get("results", []):
            for key in ["url", "description", "title"]:
                found = add_urls(platform, item.get(key, ""), found, limit)
                if len(found) >= limit:
                    return found
    return found


def html_search(platform: str, query: str, limit: int, found: list[str]) -> list[str]:
    pages = [
        f"https://www.bing.com/search?q={quote_plus(query)}&count=50",
        f"https://duckduckgo.com/html/?q={quote_plus(query)}",
    ]
    for page in pages:
        found = add_urls(platform, http_get(page), found, limit)
        if len(found) >= limit:
            break
    return found


def discover_urls(platform: str, search: str, limit: int) -> list[str]:
    if GOOGLE_API_KEY and GOOGLE_CSE_ID:
        print("Using Google Custom Search API.")
    elif BRAVE_SEARCH_API_KEY:
        print("Using Brave Search API.")
    else:
        print("No search API key found. Using free search fallback, which may return 0 on GitHub runners.")

    found: list[str] = []
    for query in build_queries(platform, search):
        before = len(found)
        found = google_search(platform, query, limit, found)
        if not (GOOGLE_API_KEY and GOOGLE_CSE_ID):
            found = brave_search(platform, query, limit, found)
        if not (GOOGLE_API_KEY and GOOGLE_CSE_ID) and not BRAVE_SEARCH_API_KEY:
            found = html_search(platform, query, limit, found)
        print(f"Search query: {query} / found {len(found) - before} new profiles")
        if len(found) >= limit:
            break
        time.sleep(0.4)
    return found[:limit]


def meta_description(page: str) -> str:
    patterns = [
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, page or "", re.I | re.S)
        if match:
            return html.unescape(match.group(1)).strip()
    return ""


def title_text(page: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", page or "", re.I | re.S)
    if not match:
        return ""
    title = html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    return title.replace("• Instagram photos and videos", "").replace("| TikTok", "").strip(" -")


def to_creator(platform: str, url: str, search: str, niche: str, gender: str, location: str) -> dict[str, str]:
    page = http_get(url)
    bio = meta_description(page)
    title = title_text(page)
    handle = handle_from_url(platform, url)
    name = title if title and "TikTok" not in title and "Instagram" not in title else handle
    platform_label = "Instagram" if platform == "instagram" else "TikTok"
    country = "United States" if "united states" in location.lower() or location.lower() in ["us", "usa"] else "Unknown"

    return {
        "name": name,
        "creator_name": name,
        "handle": handle,
        "platform": platform_label,
        "public_email": first_email(bio),
        "profile_url": url,
        "followers": "",
        "engagement_rate": "",
        "bio": bio[:1800],
        "location": location,
        "country": country,
        "niche": niche or search,
        "creator_type": "Individual Creator",
        "creator_gender": gender,
        "outreach_status": "Not Contacted",
        "tier": "Not Yet Tiered",
        "headhunter": "Unassigned",
        "date_added": date.today().isoformat(),
        "last_posted_date": "",
        "last_contacted": "",
    }


def has_duplicate(creator: dict, existing_keys: set[str]) -> bool:
    return any(key in existing_keys for key in creator_keys(creator))


def run(platform: str, search: str, niche: str, max_creators: int, group_key: str, creator_gender: str, location: str) -> None:
    group_id = GROUP_IDS.get(group_key)
    if not group_id:
        raise ValueError(f"Invalid group key: {group_key}")

    blocklist = load_blocklist()
    existing_keys = get_existing_creator_keys()
    run_keys: set[str] = set()
    urls = discover_urls(platform, search, max_creators)
    print(f"Found {len(urls)} candidate {platform} profile URLs for search: {search}")

    created = skipped_run = skipped_existing = skipped_blocked = 0
    for url in urls:
        creator = to_creator(platform, url, search, niche, creator_gender, location)
        keys = creator_keys(creator)

        if is_blocked_creator(creator, blocklist):
            skipped_blocked += 1
            print(f"Skipped blocklisted creator: {creator['creator_name']} / {creator['handle']}")
            continue
        if any(key in run_keys for key in keys):
            skipped_run += 1
            print(f"Skipped same-run duplicate: {creator['creator_name']} / {creator['handle']}")
            continue
        if has_duplicate(creator, existing_keys):
            skipped_existing += 1
            print(f"Skipped existing monday creator: {creator['creator_name']} / {creator['handle']}")
            continue

        run_keys.update(keys)
        existing_keys.update(keys)

        try:
            result = create_creator_item(creator, group_id=group_id)
            item = result["data"]["create_item"]
            print(f"Created: {item['name']} / {creator['platform']} / email: {creator['public_email'] or 'blank'} / {creator['profile_url']}")
            created += 1
            time.sleep(0.5)
        except Exception as error:
            print(f"Failed creator: {creator['creator_name']} / error: {error}")

    print(
        f"Done. Created {created} {platform} leads. "
        f"Skipped {skipped_run} same-run duplicates, {skipped_existing} existing monday creators, and {skipped_blocked} blocklisted creators."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Discover public Instagram or TikTok creators and send them to monday.com.")
    parser.add_argument("--platform", required=True, choices=["instagram", "tiktok"])
    parser.add_argument("--search", required=True)
    parser.add_argument("--niche", default="Entertainment")
    parser.add_argument("--location", default="United States")
    parser.add_argument("--max-creators", type=int, default=100)
    parser.add_argument("--group", default="new_leads")
    parser.add_argument("--creator-gender", default="Man", choices=["Woman", "Man", "Non-binary", "Mixed Team", "Unknown"])
    args = parser.parse_args()

    run(
        platform=args.platform,
        search=args.search,
        niche=args.niche,
        max_creators=args.max_creators,
        group_key=args.group,
        creator_gender=args.creator_gender,
        location=args.location,
    )
