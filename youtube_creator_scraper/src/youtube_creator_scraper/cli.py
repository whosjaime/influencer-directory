from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

from .scoring import normalize_text, normalize_url, parse_int, score_channel, summarize_videos, tier_from_score
from .youtube_api import YouTubeClient


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_do_not_contact(path: Path) -> Dict[str, Set[str]]:
    blocked = {"channel_ids": set(), "handles": set(), "names": set(), "urls": set()}
    if not path.exists():
        return blocked
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = normalize_text(row.get("name"))
            channel_id = normalize_text(row.get("channel_id"))
            handle = normalize_text(row.get("handle"))
            url = normalize_url(row.get("channel_url"))
            if name:
                blocked["names"].add(name)
            if channel_id:
                blocked["channel_ids"].add(channel_id)
            if handle:
                blocked["handles"].add(handle.lstrip("@"))
            if url:
                blocked["urls"].add(url)
    return blocked


def is_blocked(channel: Dict[str, Any], blocked: Dict[str, Set[str]]) -> bool:
    snippet = channel.get("snippet", {})
    channel_id = normalize_text(channel.get("id"))
    title = normalize_text(snippet.get("title"))
    custom_url = normalize_text(snippet.get("customUrl", "")).lstrip("@")
    url = normalize_url(f"https://www.youtube.com/channel/{channel_id}")
    handle_url = normalize_url(f"https://www.youtube.com/{snippet.get('customUrl', '')}") if custom_url else ""

    return (
        channel_id in blocked["channel_ids"]
        or title in blocked["names"]
        or custom_url in blocked["handles"]
        or url in blocked["urls"]
        or bool(handle_url and handle_url in blocked["urls"])
    )


def channel_to_row(channel: Dict[str, Any], profile_name: str, profile: Dict[str, Any], video_summary: Dict[str, Any], score: int, reasons: List[str]) -> Dict[str, Any]:
    snippet = channel.get("snippet", {})
    stats = channel.get("statistics", {})
    channel_id = channel.get("id", "")
    custom_url = snippet.get("customUrl", "")
    youtube_url = f"https://www.youtube.com/{custom_url}" if custom_url else f"https://www.youtube.com/channel/{channel_id}"
    description = snippet.get("description", "")

    return {
        "name": snippet.get("title", ""),
        "creator_type": profile_name,
        "youtube_url": youtube_url,
        "channel_id": channel_id,
        "handle": custom_url,
        "subscribers": parse_int(stats.get("subscriberCount")),
        "total_views": parse_int(stats.get("viewCount")),
        "video_count": parse_int(stats.get("videoCount")),
        "country": snippet.get("country", ""),
        "last_posted_date": video_summary.get("last_posted_at", ""),
        "videos_last_30_days": video_summary.get("videos_last_30_days", 0),
        "shorts_ratio": video_summary.get("shorts_ratio", 0),
        "avg_recent_views": video_summary.get("avg_recent_views", 0),
        "median_recent_views": video_summary.get("median_recent_views", 0),
        "best_recent_video": video_summary.get("best_recent_video_url", ""),
        "best_recent_video_title": video_summary.get("best_recent_video_title", ""),
        "keyword_hits": ", ".join(video_summary.get("keyword_hits", [])),
        "caution_hits": ", ".join(video_summary.get("caution_hits", [])),
        "fit_score": score,
        "tier": tier_from_score(score),
        "notes": "; ".join(reasons),
        "description_preview": description[:300].replace("\n", " "),
        "outreach_status": "Needs Review",
        "source_query_profile": profile.get("description", ""),
    }


def discover(args: argparse.Namespace) -> None:
    profiles = load_json(Path(args.config))
    selected_profiles = profiles if args.profile == "all" else {args.profile: profiles[args.profile]}
    do_not_contact = load_do_not_contact(Path(args.do_not_contact))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    client = YouTubeClient(api_key=args.api_key)
    discovered_ids: Dict[str, Set[str]] = {profile_name: set() for profile_name in selected_profiles}

    for profile_name, profile in selected_profiles.items():
        for query in profile["queries"]:
            print(f"Searching: {profile_name} / {query}")
            page_token = None
            pages = 0
            while pages < args.pages_per_query:
                data = client.search_channels(query=query, max_results=50, page_token=page_token)
                for item in data.get("items", []):
                    channel_id = item.get("snippet", {}).get("channelId")
                    if channel_id:
                        discovered_ids[profile_name].add(channel_id)
                page_token = data.get("nextPageToken")
                pages += 1
                if not page_token:
                    break

    rows: List[Dict[str, Any]] = []
    seen_channel_ids: Set[str] = set()

    for profile_name, channel_ids in discovered_ids.items():
        profile = selected_profiles[profile_name]
        channels = client.get_channels(channel_ids)
        for channel in channels:
            channel_id = channel.get("id", "")
            if channel_id in seen_channel_ids:
                continue
            seen_channel_ids.add(channel_id)
            if is_blocked(channel, do_not_contact):
                continue

            uploads_playlist = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", "")
            video_items = client.get_playlist_items(uploads_playlist, max_results=args.recent_videos) if uploads_playlist else []
            video_ids = [item.get("contentDetails", {}).get("videoId", "") for item in video_items]
            videos = client.get_videos(video_ids)
            video_summary = summarize_videos(videos, profile.get("positive_keywords", []), profile.get("caution_keywords", []))
            score, reasons = score_channel(channel, video_summary, profile)
            if score < args.min_score:
                continue
            rows.append(channel_to_row(channel, profile_name, profile, video_summary, score, reasons))

    rows.sort(key=lambda r: (r["fit_score"], r["median_recent_views"], r["subscribers"]), reverse=True)

    fieldnames = list(rows[0].keys()) if rows else [
        "name", "creator_type", "youtube_url", "channel_id", "handle", "subscribers",
        "total_views", "video_count", "country", "last_posted_date", "videos_last_30_days",
        "shorts_ratio", "avg_recent_views", "median_recent_views", "best_recent_video",
        "best_recent_video_title", "keyword_hits", "caution_hits", "fit_score", "tier",
        "notes", "description_preview", "outreach_status", "source_query_profile"
    ]

    csv_path = out_dir / "youtube_creator_leads.csv"
    jsonl_path = out_dir / "youtube_creator_leads.jsonl"

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Saved {len(rows)} leads to {csv_path}")
    print(f"Saved JSONL to {jsonl_path}")


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find YouTube creator leads for Minecraft/product-led Shorts campaigns.")
    parser.add_argument("--api-key", default=os.getenv("YOUTUBE_API_KEY"), help="YouTube Data API key. Defaults to YOUTUBE_API_KEY env var.")
    parser.add_argument("--config", default="config/profile_types.json", help="Profile config JSON path.")
    parser.add_argument("--profile", default="all", help="Profile name from config, or all.")
    parser.add_argument("--do-not-contact", default="data/do_not_contact.csv", help="CSV of already-contacted creators to exclude.")
    parser.add_argument("--out-dir", default="output", help="Output directory.")
    parser.add_argument("--pages-per-query", type=int, default=1, help="Each search page costs quota. Start with 1.")
    parser.add_argument("--recent-videos", type=int, default=20, help="How many recent uploads to score.")
    parser.add_argument("--min-score", type=int, default=40, help="Minimum fit score to keep.")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    discover(parse_args(argv))


if __name__ == "__main__":
    main()
