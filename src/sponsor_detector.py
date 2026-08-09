from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from sponsor_dedupe import make_brand_key, make_sponsorship_key, normalize_brand_name, normalize_domain
from sponsor_models import ChannelRecord, SponsorLead, VideoRecord


SPONSOR_PATTERNS = [
    re.compile(r"(?:this\s+(?:video|episode)\s+is\s+)?sponsored\s+by\s+([^\n\r.!?|]{2,80})", re.I),
    re.compile(r"(?:thanks|thank\s+you)\s+to\s+([^\n\r.!?|]{2,80}?)\s+for\s+(?:sponsoring|supporting)\b", re.I),
    re.compile(r"(?:in\s+partnership\s+with|partnered\s+with|brought\s+to\s+you\s+by)\s+([^\n\r.!?|]{2,80})", re.I),
    re.compile(r"(?:today'?s\s+sponsor\s+is|sponsor\s+of\s+today'?s\s+(?:video|episode)\s+is)\s+([^\n\r.!?|]{2,80})", re.I),
]

URL_RE = re.compile(r"https?://[^\s<>{}\[\]\"']+", re.I)
AD_SIGNAL_RE = re.compile(r"(?:^|\s)#(?:ad|sponsored|partner)(?:\s|$)|paid\s+partnership", re.I)

NON_SPONSOR_DOMAINS = {
    "youtube.com", "youtu.be", "instagram.com", "tiktok.com", "twitter.com", "x.com",
    "facebook.com", "threads.net", "discord.com", "discord.gg", "twitch.tv", "patreon.com",
    "linktr.ee", "beacons.ai", "solo.to", "bio.site", "stan.store", "google.com", "apple.com",
}
SHORTENER_DOMAINS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "amzn.to", "geni.us"}


@dataclass
class DetectedSponsor:
    brand_name: str
    domain: str
    evidence: str
    explicit_phrase: bool
    ad_hashtag: bool
    from_brand_partner: bool


def _clean_brand(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" :-–—,;()[]")
    value = re.sub(r"\s+(?:using|and\s+get|to\s+get|for\s+more|with\s+code|use\s+code).*$", "", value, flags=re.I)
    return value[:80].strip()


def _url_domain(url: str) -> str:
    return normalize_domain(url.rstrip(".,;:!?)\"]}"))


def _external_urls(description: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_url in URL_RE.findall(description or ""):
        url = raw_url.rstrip(".,;:!?)\"]}")
        domain = _url_domain(url)
        if not domain or domain in NON_SPONSOR_DOMAINS or domain.endswith(".youtube.com"):
            continue
        key = f"{domain}|{url}"
        if key not in seen:
            seen.add(key)
            found.append((url, domain))
    return found


def _domain_for_brand(brand_name: str, description: str, match_start: int | None = None) -> str:
    urls = _external_urls(description)
    if not urls:
        return ""

    brand_key = normalize_brand_name(brand_name)
    for _, domain in urls:
        labels = domain.split(".")
        domain_key = normalize_brand_name("".join(labels[:-1] or labels))
        if brand_key and (brand_key in domain_key or domain_key in brand_key):
            return domain

    # Prefer a sponsor link close to the explicit sponsorship sentence.
    if match_start is not None:
        lines = description.splitlines()
        position = 0
        sponsor_line = 0
        for index, line in enumerate(lines):
            if position <= match_start <= position + len(line) + 1:
                sponsor_line = index
                break
            position += len(line) + 1
        nearby = "\n".join(lines[max(0, sponsor_line - 1) : sponsor_line + 4])
        nearby_urls = _external_urls(nearby)
        for _, domain in nearby_urls:
            if domain not in SHORTENER_DOMAINS:
                return domain

    non_shortened = [domain for _, domain in urls if domain not in SHORTENER_DOMAINS]
    if len(set(non_shortened)) == 1:
        return non_shortened[0]
    return ""


def _brand_from_domain(domain: str) -> str:
    host = normalize_domain(domain)
    if not host:
        return ""
    labels = host.split(".")
    core = labels[-2] if len(labels) >= 2 else labels[0]
    if core in {"go", "try", "get", "app", "shop"} and len(labels) >= 3:
        core = labels[-3]
    words = re.sub(r"[-_]", " ", core).strip()
    return words.title()


def detect_sponsors(video: VideoRecord, channels: dict[str, ChannelRecord]) -> list[DetectedSponsor]:
    description = video.description or ""
    detections: list[DetectedSponsor] = []
    ad_signal = bool(AD_SIGNAL_RE.search(description))

    for pattern in SPONSOR_PATTERNS:
        for match in pattern.finditer(description):
            brand_name = _clean_brand(match.group(1))
            if not brand_name or len(normalize_brand_name(brand_name)) < 2:
                continue
            domain = _domain_for_brand(brand_name, description, match.start())
            evidence = re.sub(r"\s+", " ", match.group(0)).strip()[:240]
            detections.append(
                DetectedSponsor(
                    brand_name=brand_name,
                    domain=domain,
                    evidence=evidence,
                    explicit_phrase=True,
                    ad_hashtag=ad_signal,
                    from_brand_partner=False,
                )
            )

    if video.brand_partner_channel_id:
        partner = channels.get(video.brand_partner_channel_id)
        if partner and partner.title:
            domain = _domain_for_brand(partner.title, description)
            detections.append(
                DetectedSponsor(
                    brand_name=partner.title,
                    domain=domain,
                    evidence=f"YouTube brand partner linked to video: {partner.title}",
                    explicit_phrase=False,
                    ad_hashtag=ad_signal,
                    from_brand_partner=True,
                )
            )

    # Fallback for clearly disclosed ads where the creator did not use an explicit
    # 'sponsored by' sentence. Only use a non-social, non-shortener external domain.
    if not detections and (video.paid_product_placement or ad_signal):
        external = [(url, domain) for url, domain in _external_urls(description) if domain not in SHORTENER_DOMAINS]
        if external:
            _, domain = external[0]
            brand_name = _brand_from_domain(domain)
            if brand_name:
                detections.append(
                    DetectedSponsor(
                        brand_name=brand_name,
                        domain=domain,
                        evidence="Paid promotion/ad disclosure with external sponsor link",
                        explicit_phrase=False,
                        ad_hashtag=ad_signal,
                        from_brand_partner=False,
                    )
                )

    # Merge repeated mentions of the same sponsor inside one description.
    merged: dict[str, DetectedSponsor] = {}
    for detection in detections:
        key = normalize_domain(detection.domain) or normalize_brand_name(detection.brand_name)
        if not key:
            continue
        current = merged.get(key)
        if current is None:
            merged[key] = detection
            continue
        current.explicit_phrase = current.explicit_phrase or detection.explicit_phrase
        current.ad_hashtag = current.ad_hashtag or detection.ad_hashtag
        current.from_brand_partner = current.from_brand_partner or detection.from_brand_partner
        if not current.domain and detection.domain:
            current.domain = detection.domain
        if len(detection.evidence) > len(current.evidence):
            current.evidence = detection.evidence

    return list(merged.values())


def to_sponsor_lead(
    video: VideoRecord,
    creator: ChannelRecord | None,
    detection: DetectedSponsor,
    creator_genre: str,
    creator_tags: list[str],
) -> SponsorLead:
    domain = normalize_domain(detection.domain)
    brand_key = make_brand_key(detection.brand_name, domain)
    sponsorship_key = make_sponsorship_key(video.platform, video.video_id, detection.brand_name, domain)
    creator_url = f"https://www.youtube.com/channel/{video.channel_id}" if video.channel_id else ""

    signals = []
    if detection.explicit_phrase:
        signals.append("explicit sponsor phrase")
    if detection.ad_hashtag:
        signals.append("ad/sponsored disclosure")
    if detection.from_brand_partner:
        signals.append("YouTube brand partner")
    if video.paid_product_placement:
        signals.append("YouTube paid product placement")
    if domain:
        signals.append("sponsor domain found")

    return SponsorLead(
        brand_name=detection.brand_name,
        brand_domain=domain,
        source_platform=video.platform,
        creator_name=(creator.title if creator else video.channel_title),
        creator_url=creator_url,
        creator_channel_id=video.channel_id,
        creator_subscribers=(creator.subscriber_count if creator else 0),
        creator_genre=creator_genre,
        creator_tags=creator_tags,
        video_id=video.video_id,
        video_url=video.video_url,
        video_title=video.title,
        sponsored_date=(video.published_at[:10] if video.published_at else ""),
        evidence=detection.evidence,
        paid_product_placement=video.paid_product_placement,
        brand_partner_channel_id=video.brand_partner_channel_id,
        brand_key=brand_key,
        sponsorship_key=sponsorship_key,
        signals=signals,
    )
