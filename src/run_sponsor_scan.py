from __future__ import annotations

from datetime import date, datetime

from brand_enrichment import BrandEnricher
from creator_classifier import classify_creator
from discord_notifier import DiscordNotifier
from sponsor_config import load_sponsor_config
from sponsor_dedupe import ExistingSponsorIndex, make_brand_key, make_sponsorship_key, normalize_domain
from sponsor_detector import detect_sponsors, to_sponsor_lead
from sponsor_models import SponsorLead
from sponsor_monday_client import SponsorMondayClient
from youtube_sponsor_scanner import YouTubeSponsorScanner


LOOKBACK_WINDOWS_HOURS = [24, 72, 168]


def _score_lead(lead: SponsorLead) -> int:
    score = 0
    signals = set(lead.signals)

    if "explicit sponsor phrase" in signals:
        score += 35
    if lead.paid_product_placement:
        score += 25
    if "YouTube brand partner" in signals:
        score += 20
    if "ad/sponsored disclosure" in signals:
        score += 12
    if lead.brand_domain:
        score += 15
    if lead.contact_email:
        score += 15
    if lead.creator_genre and lead.creator_genre != "Other":
        score += 5
    if lead.sponsor_category and lead.sponsor_category != "Other":
        score += 3

    try:
        sponsored = date.fromisoformat(lead.sponsored_date)
        age_days = (date.today() - sponsored).days
        if 0 <= age_days <= 7:
            score += 5
    except ValueError:
        pass

    return min(100, score)


def _temperature(score: int) -> str:
    if score >= 90:
        return "Very Hot"
    if score >= 80:
        return "Hot"
    if score >= 70:
        return "Warm"
    return "Needs Review"


def _candidate_identity(lead: SponsorLead) -> str:
    return lead.brand_key or f"name:{lead.brand_name.strip().lower()}"


def _enrich_lead(lead: SponsorLead, enricher: BrandEnricher) -> SponsorLead:
    if not lead.brand_domain:
        lead.lead_score = _score_lead(lead)
        lead.lead_temperature = _temperature(lead.lead_score)
        return lead

    enrichment = enricher.enrich(lead.brand_domain)
    if enrichment.domain:
        lead.brand_domain = normalize_domain(enrichment.domain)
    lead.contact_email = enrichment.contact_email
    lead.email_type = enrichment.email_type
    lead.contact_source = enrichment.contact_source
    lead.sponsor_category = enrichment.category
    lead.sponsor_subcategory = enrichment.subcategory

    # Enrichment can reveal a canonical redirected domain. Rebuild both keys before
    # the duplicate check so aliases and redirected sponsor URLs do not create doubles.
    lead.brand_key = make_brand_key(lead.brand_name, lead.brand_domain)
    lead.sponsorship_key = make_sponsorship_key(
        lead.source_platform,
        lead.video_id,
        lead.brand_name,
        lead.brand_domain,
    )
    lead.lead_score = _score_lead(lead)
    lead.lead_temperature = _temperature(lead.lead_score)
    return lead


def _blocked_by_index(index: ExistingSponsorIndex, lead: SponsorLead) -> bool:
    return index.is_duplicate_brand(lead) or index.is_duplicate_event(lead) or index.is_protected(lead)


def run() -> None:
    config = load_sponsor_config()
    monday = SponsorMondayClient(
        token=config.monday_token,
        board_id=config.monday_board_id,
        group_id=config.monday_group_id,
    )
    youtube = YouTubeSponsorScanner(
        api_key=config.youtube_api_key,
        region=config.search_region,
        language=config.search_language,
    )
    enricher = BrandEnricher()
    discord = DiscordNotifier(config.discord_webhook_url)

    # Gate 1: scan the full client board before any discovery starts.
    existing = monday.load_existing_index()

    candidate_pool: dict[str, SponsorLead] = {}
    duplicate_count = 0
    rejected_count = 0
    scanned_video_ids: set[str] = set()
    errors: list[str] = []
    desired_pool_size = max(config.target_daily_leads + 10, config.target_daily_leads * 2)

    if config.enable_instagram:
        errors.append("Instagram scan is enabled in config but the Instagram source adapter is not active yet; YouTube ran normally.")
    if config.enable_tiktok:
        errors.append("TikTok scan is enabled in config but the TikTok source adapter is not active yet; YouTube ran normally.")

    for lookback_hours in LOOKBACK_WINDOWS_HOURS:
        print(f"Scanning YouTube sponsorship signals from the last {lookback_hours} hours...")
        try:
            videos, channels = youtube.discover(lookback_hours)
        except Exception as exc:
            errors.append(f"YouTube {lookback_hours}h scan failed: {exc}")
            continue

        new_videos = [video for video in videos if video.video_id not in scanned_video_ids]
        for video in new_videos:
            scanned_video_ids.add(video.video_id)
            creator = channels.get(video.channel_id)
            creator_genre, creator_tags = classify_creator(video, creator)
            detections = detect_sponsors(video, channels)

            for detection in detections:
                lead = to_sponsor_lead(video, creator, detection, creator_genre, creator_tags)
                try:
                    lead = _enrich_lead(lead, enricher)
                except Exception as exc:
                    errors.append(f"Enrichment warning for {lead.brand_name}: {exc}")
                    lead.lead_score = _score_lead(lead)
                    lead.lead_temperature = _temperature(lead.lead_score)

                # Gate 2: duplicate check after brand/domain/email enrichment.
                if _blocked_by_index(existing, lead):
                    duplicate_count += 1
                    print(f"Duplicate blocked: {lead.brand_name} ({lead.brand_domain or 'no domain'})")
                    continue

                if lead.lead_score < config.min_lead_score:
                    rejected_count += 1
                    continue

                identity = _candidate_identity(lead)
                current = candidate_pool.get(identity)
                if current is None or lead.lead_score > current.lead_score:
                    candidate_pool[identity] = lead

        if len(candidate_pool) >= desired_pool_size:
            break

    # Gate 3: scan the complete board again immediately before any writes. This catches
    # brands added by a human or another integration while the discovery run was active.
    final_index = monday.load_existing_index()

    ordered = sorted(
        candidate_pool.values(),
        key=lambda lead: (lead.lead_score, lead.sponsored_date, bool(lead.contact_email)),
        reverse=True,
    )

    created: list[SponsorLead] = []
    for lead in ordered:
        if len(created) >= config.target_daily_leads:
            break
        if _blocked_by_index(final_index, lead):
            duplicate_count += 1
            print(f"Final duplicate gate blocked: {lead.brand_name}")
            continue

        try:
            result = monday.create_lead(lead)
            item = result.get("data", {}).get("create_item", {})
            print(
                f"Created sponsor lead: {lead.brand_name} / monday item {item.get('id', '?')} / "
                f"score {lead.lead_score}"
            )
            created.append(lead)
            # Protect the rest of this same run immediately after every successful write.
            final_index.add(lead, protected=False)
        except Exception as exc:
            errors.append(f"monday create failed for {lead.brand_name}: {exc}")

    print(
        f"Sponsor scan complete: created {len(created)}/{config.target_daily_leads} target leads, "
        f"blocked {duplicate_count} duplicates, rejected {rejected_count} low-score detections, "
        f"scanned {len(scanned_video_ids)} unique YouTube videos."
    )

    try:
        discord.send_daily_summary(
            created=created,
            duplicate_count=duplicate_count,
            rejected_count=rejected_count,
            scanned_videos=len(scanned_video_ids),
            errors=errors,
        )
    except Exception as exc:
        print(f"Discord summary warning: {exc}")

    if len(created) < config.target_daily_leads:
        print(
            f"Qualified unique inventory was below the daily target. "
            f"The scanner did not lower the quality threshold or re-import duplicates to force {config.target_daily_leads}."
        )


if __name__ == "__main__":
    run()
