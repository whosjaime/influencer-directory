from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse


ANCHOR_CREATORS = [
    "@joshbrownjsy",
    "Josh Brown JSY",
    "@DylanMcElliott",
    "Dylan McElliott",
]

SHORT_FORM_SIGNALS = {
    "tiktok",
    "shorts",
    "short-form",
    "short form",
    "reels",
    "viral",
    "trend",
    "trends",
    "pov",
    "skit",
    "ugc",
}

LOOKALIKE_SIGNALS = {
    "challenge",
    "challenges",
    "prank",
    "pranks",
    "comedy",
    "funny",
    "vlog",
    "vlogs",
    "adventure",
    "story",
    "storytime",
    "public",
    "street",
    "family-friendly",
    "family friendly",
    "brand safe",
    "brand-safe",
    "toy",
    "minecraft",
}

EXCLUDE_SIGNALS = {
    "finance",
    "crypto",
    "trading",
    "stock market",
    "politics",
    "political",
    "news",
    "education",
    "educational",
    "tutorial",
    "podcast",
    "documentary",
    "music video",
    "official music",
    "beauty",
    "makeup",
    "fashion",
    "onlyfans",
    "nsfw",
    "adult",
    "alcohol",
    "vape",
    "weed",
    "gambling",
}

MIN_FOLLOWERS = 100_000
MAX_FOLLOWERS = 999_999
DEFAULT_MIN_FIT_SCORE = 55


@dataclass
class FitResult:
    accepted: bool
    score: int
    reasons: list[str]


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def creator_text(creator: dict) -> str:
    fields = [
        "name",
        "creator_name",
        "handle",
        "platform",
        "profile_url",
        "bio",
        "niche",
        "creator_type",
        "notes",
        "best_video",
        "highlight_video",
    ]
    return " ".join(normalize_text(creator.get(field, "")) for field in fields)


def parse_followers(value: object) -> int | None:
    text = normalize_text(value).replace(",", "")
    if not text:
        return None

    multiplier = 1
    if text.endswith("k"):
        multiplier = 1_000
        text = text[:-1]
    elif text.endswith("m"):
        multiplier = 1_000_000
        text = text[:-1]

    try:
        return int(float(text) * multiplier)
    except ValueError:
        return None


def profile_domain(creator: dict) -> str:
    raw_url = normalize_text(creator.get("profile_url", ""))
    if not raw_url:
        return ""
    parsed = urlparse(raw_url if "://" in raw_url else f"https://{raw_url}")
    return parsed.netloc.replace("www.", "")


def contains_any(text: str, signals: set[str]) -> bool:
    return any(signal in text for signal in signals)


def is_tiktok_creator(creator: dict) -> bool:
    text = creator_text(creator)
    domain = profile_domain(creator)
    return "tiktok" in text or domain == "tiktok.com"


def is_youtube_creator(creator: dict) -> bool:
    text = creator_text(creator)
    domain = profile_domain(creator)
    return "youtube" in text or "youtu.be" in domain or "youtube.com" in domain


def has_short_form_signal(creator: dict) -> bool:
    text = creator_text(creator)
    return contains_any(text, SHORT_FORM_SIGNALS)


def score_creator_fit(creator: dict) -> FitResult:
    text = creator_text(creator)
    followers = parse_followers(creator.get("followers", ""))
    score = 0
    reasons: list[str] = []

    if contains_any(text, EXCLUDE_SIGNALS):
        score -= 60
        reasons.append("blocked niche/safety mismatch")

    if is_tiktok_creator(creator):
        score += 45
        reasons.append("TikTok-first profile")

    if is_youtube_creator(creator):
        score += 10
        reasons.append("YouTube profile")
        if has_short_form_signal(creator):
            score += 30
            reasons.append("YouTube Shorts/TikTok-style signal")
        else:
            score -= 50
            reasons.append("YouTube profile without Shorts/TikTok-style signal")

    if has_short_form_signal(creator):
        score += 15
        reasons.append("short-form language match")

    if contains_any(text, LOOKALIKE_SIGNALS):
        score += 20
        reasons.append("Josh Brown / Dylan McElliott lookalike content match")

    if "family-friendly" in text or "family friendly" in text or "brand safe" in text or "brand-safe" in text:
        score += 15
        reasons.append("family-friendly / brand-safe signal")

    if followers is not None:
        if MIN_FOLLOWERS <= followers <= MAX_FOLLOWERS:
            score += 20
            reasons.append("follower count in 100k-999k range")
        else:
            score -= 35
            reasons.append("outside 100k-999k follower range")

    if normalize_text(creator.get("last_posted_date", "")):
        score += 5
        reasons.append("has recent posting date")

    accepted = score >= DEFAULT_MIN_FIT_SCORE
    return FitResult(accepted=accepted, score=score, reasons=reasons)


def should_import_creator(creator: dict, min_fit_score: int = DEFAULT_MIN_FIT_SCORE) -> FitResult:
    result = score_creator_fit(creator)
    accepted = result.score >= min_fit_score
    return FitResult(accepted=accepted, score=result.score, reasons=result.reasons)


def filter_creators(creators: list[dict], min_fit_score: int = DEFAULT_MIN_FIT_SCORE) -> tuple[list[dict], list[tuple[dict, FitResult]]]:
    accepted: list[dict] = []
    rejected: list[tuple[dict, FitResult]] = []

    for creator in creators:
        fit = should_import_creator(creator, min_fit_score=min_fit_score)
        creator["fit_score"] = str(fit.score)
        creator["fit_notes"] = "; ".join(fit.reasons)

        if fit.accepted:
            accepted.append(creator)
        else:
            rejected.append((creator, fit))

    return accepted, rejected


def discovery_query_bank() -> list[str]:
    """Queries to use upstream so discovery starts with TikTok/Shorts-style creators."""
    return [
        "site:tiktok.com/@ comedy challenge creator family friendly",
        "site:tiktok.com/@ POV skit creator brand safe",
        "site:tiktok.com/@ TikTok creator challenge prank comedy",
        "site:youtube.com/@ YouTube Shorts challenge comedy creator",
        "site:youtube.com/@ TikTok style Shorts creator family friendly",
        "creators like @joshbrownjsy TikTok challenge comedy",
        "creators like Dylan McElliott YouTube Shorts TikTok creator",
    ]
