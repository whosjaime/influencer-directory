from __future__ import annotations

import re
from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, Iterable, List, Tuple

from dateutil import parser as date_parser


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def normalize_url(value: str | None) -> str:
    value = (value or "").strip().lower()
    value = value.replace("https://", "").replace("http://", "").replace("www.", "")
    return value.rstrip("/")


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_iso8601_duration_seconds(duration: str | None) -> int:
    if not duration:
        return 0
    match = re.fullmatch(r"P(?:\d+D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return 0
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def keyword_hits(text: str, keywords: Iterable[str]) -> List[str]:
    normalized = normalize_text(text)
    return sorted({kw for kw in keywords if normalize_text(kw) in normalized})


def summarize_videos(videos: List[Dict[str, Any]], positive_keywords: List[str], caution_keywords: List[str]) -> Dict[str, Any]:
    if not videos:
        return {
            "recent_video_count": 0,
            "last_posted_at": "",
            "avg_recent_views": 0,
            "median_recent_views": 0,
            "shorts_ratio": 0,
            "videos_last_30_days": 0,
            "keyword_hits": [],
            "caution_hits": [],
            "best_recent_video_url": "",
            "best_recent_video_title": "",
        }

    view_counts: List[int] = []
    shorts_count = 0
    videos_last_30_days = 0
    all_text: List[str] = []
    best_video = None
    best_views = -1
    newest_dt = None
    now = datetime.now(timezone.utc)

    for video in videos:
        snippet = video.get("snippet", {})
        stats = video.get("statistics", {})
        details = video.get("contentDetails", {})
        title = snippet.get("title", "")
        description = snippet.get("description", "")
        all_text.append(f"{title} {description}")
        views = parse_int(stats.get("viewCount"))
        view_counts.append(views)
        if views > best_views:
            best_views = views
            best_video = video

        if 0 < parse_iso8601_duration_seconds(details.get("duration")) <= 75:
            shorts_count += 1

        published_at = snippet.get("publishedAt")
        if published_at:
            try:
                dt = date_parser.isoparse(published_at)
                if newest_dt is None or dt > newest_dt:
                    newest_dt = dt
                if (now - dt).days <= 30:
                    videos_last_30_days += 1
            except Exception:
                pass

    combined_text = " ".join(all_text)
    best_snippet = (best_video or {}).get("snippet", {})
    best_video_id = (best_video or {}).get("id", "")

    return {
        "recent_video_count": len(videos),
        "last_posted_at": newest_dt.date().isoformat() if newest_dt else "",
        "avg_recent_views": round(sum(view_counts) / len(view_counts)) if view_counts else 0,
        "median_recent_views": round(median(view_counts)) if view_counts else 0,
        "shorts_ratio": round(shorts_count / len(videos), 2) if videos else 0,
        "videos_last_30_days": videos_last_30_days,
        "keyword_hits": keyword_hits(combined_text, positive_keywords),
        "caution_hits": keyword_hits(combined_text, caution_keywords),
        "best_recent_video_url": f"https://www.youtube.com/watch?v={best_video_id}" if best_video_id else "",
        "best_recent_video_title": best_snippet.get("title", ""),
    }


def score_channel(channel: Dict[str, Any], video_summary: Dict[str, Any], profile: Dict[str, Any]) -> Tuple[int, List[str]]:
    stats = channel.get("statistics", {})
    snippet = channel.get("snippet", {})
    branding = channel.get("brandingSettings", {}).get("channel", {})
    subscribers = parse_int(stats.get("subscriberCount"))
    text = " ".join([
        snippet.get("title", ""),
        snippet.get("description", ""),
        branding.get("description", ""),
        " ".join(video_summary.get("keyword_hits", [])),
    ])

    score = 0
    reasons: List[str] = []

    if profile.get("min_subscribers", 0) <= subscribers <= profile.get("max_subscribers", 10**12):
        score += 20
        reasons.append("subscriber range fit")
    if profile.get("ideal_min_subscribers", 0) <= subscribers <= profile.get("ideal_max_subscribers", 10**12):
        score += 10
        reasons.append("ideal subscriber range")

    if video_summary.get("shorts_ratio", 0) >= 0.6:
        score += 15
        reasons.append("mostly Shorts-format")
    elif video_summary.get("shorts_ratio", 0) >= 0.35:
        score += 7
        reasons.append("some Shorts-format")

    if video_summary.get("videos_last_30_days", 0) >= 4:
        score += 15
        reasons.append("active posting")
    elif video_summary.get("videos_last_30_days", 0) >= 1:
        score += 7
        reasons.append("recently posted")

    median_views = video_summary.get("median_recent_views", 0)
    if median_views >= 100000:
        score += 15
        reasons.append("strong recent median views")
    elif median_views >= 25000:
        score += 10
        reasons.append("solid recent median views")
    elif median_views >= 5000:
        score += 4
        reasons.append("some recent traction")

    hits = keyword_hits(text, profile.get("positive_keywords", []))
    if len(hits) >= 4:
        score += 20
        reasons.append("strong keyword fit: " + ", ".join(hits[:6]))
    elif hits:
        score += 8
        reasons.append("keyword fit: " + ", ".join(hits[:6]))

    caution_hits = video_summary.get("caution_hits", []) + keyword_hits(text, profile.get("caution_keywords", []))
    if caution_hits:
        score -= 15
        reasons.append("manual review caution: " + ", ".join(sorted(set(caution_hits))[:6]))

    return max(score, 0), reasons


def tier_from_score(score: int) -> str:
    if score >= 75:
        return "Tier 1"
    if score >= 55:
        return "Tier 2"
    return "Tier 3"
