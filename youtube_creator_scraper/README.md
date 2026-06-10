# YouTube Creator Scraper

YouTube-first creator discovery for finding creators that fit Minecraft/product-led Shorts campaigns.

This is intentionally **not** a TikTok/Instagram scraper. The old tracker showed that the best usable signal was YouTube channel fit, creator tier, recent content, and whether the creator could make Minecraft / challenge / skit-style videos.

## What it does

- Searches YouTube channels through the official YouTube Data API.
- Scores creators by subscriber range, recent posting, Shorts ratio, recent views, and keyword fit.
- Blocks creators already contacted by using `data/do_not_contact.csv`.
- Exports Monday-ready CSV and JSONL lead files.

## Setup

```bash
cd youtube_creator_scraper
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export YOUTUBE_API_KEY="YOUR_API_KEY_HERE"
```

## Run

```bash
python -m src.youtube_creator_scraper.cli --profile all --pages-per-query 1 --recent-videos 20 --min-score 40
```

Outputs:

```text
output/youtube_creator_leads.csv
output/youtube_creator_leads.jsonl
```

## Workflow

1. Add already-contacted creators to `data/do_not_contact.csv`.
2. Run the scraper.
3. Review Tier 1 and Tier 2 manually.
4. Check visual fit, age suitability, collab ability, and brand safety.
5. Import approved leads into Monday or the outreach sheet.

## Notes

YouTube does not reliably expose public business emails through the API. Keep email/contact discovery as a manual review or approved enrichment step.