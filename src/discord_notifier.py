from __future__ import annotations

import requests

from sponsor_models import SponsorLead


class DiscordNotifier:
    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = (webhook_url or "").strip()

    def send_daily_summary(
        self,
        created: list[SponsorLead],
        duplicate_count: int,
        rejected_count: int,
        scanned_videos: int,
        errors: list[str] | None = None,
    ) -> None:
        if not self.webhook_url:
            return

        errors = errors or []
        lines = [
            "**Daily Sponsor Lead Scan**",
            f"New qualified leads: **{len(created)}**",
            f"Duplicates blocked: **{duplicate_count}**",
            f"Low-confidence/rejected: **{rejected_count}**",
            f"YouTube videos scanned: **{scanned_videos}**",
        ]

        if created:
            lines.append("")
            lines.append("**New leads**")
            for lead in created[:20]:
                email = lead.contact_email or "email not found"
                lines.append(
                    f"• **{lead.brand_name}** — {lead.creator_genre} creator: "
                    f"{lead.creator_name} — score {lead.lead_score}/100 — {email}"
                )

        if errors:
            lines.append("")
            lines.append(f"Warnings: {len(errors)}")
            for error in errors[:5]:
                lines.append(f"• {error[:250]}")

        content = "\n".join(lines)
        # Discord limits webhook message content to 2,000 characters.
        payload = {"content": content[:1990]}
        response = requests.post(self.webhook_url, json=payload, timeout=20)
        if response.status_code >= 400:
            raise RuntimeError(f"Discord webhook error {response.status_code}: {response.text[:500]}")
