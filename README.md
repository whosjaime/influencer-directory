# Manifest Media Influencer Directory

This repo imports creator/influencer leads into the Manifest Media monday.com Influencer Directory board.

## monday board

- Board ID: `18416535896`
- Default group: `New Leads`
- Default group ID: `group_mm41wfhq`

## What this does now

This imports creator leads from a CSV into monday.com and filters out low-fit creators before they hit the board.

It supports:

- creator name
- handle
- platform
- public email
- profile URL
- followers/subscribers
- engagement rate
- bio/description
- location
- country
- niche
- creator type
- creator gender
- outreach status
- tier
- headhunter
- date added
- last posted date

## Current creator target

The directory should prioritize TikTokers and YouTube Shorts-style creators, not random broad YouTube channels.

Use these as style anchors:

- `@joshbrownjsy`
- `https://www.youtube.com/@DylanMcElliott`

Best-fit creators should look like:

- TikTok-first creators
- YouTube Shorts creators with clear short-form / TikTok-style signals
- challenge, prank, comedy, POV, skit, trend, street/public, UGC, adventure, toy-friendly, Minecraft-friendly, or family-friendly creators
- preferably 100k-999k followers/subscribers
- brand-safe and age-appropriate

The import now skips broad YouTube channels unless they have clear TikTok/Shorts/lookalike signals.

Blocked or heavily down-ranked examples:

- finance
- crypto/trading
- politics/news
- education/tutorial-only
- podcast/documentary
- music-only
- beauty/fashion-only
- NSFW/adult/alcohol/vape/gambling content

## Fit filter

The import uses `src/discovery_filters.py` before creating monday.com items.

Default minimum fit score: `55`

Run import with the default TikTok/Shorts filter:

```bash
python src/import_creators.py --file data/sample_creators.csv --group new_leads
```

Make the filter stricter:

```bash
python src/import_creators.py --file data/sample_creators.csv --group new_leads --min-fit-score 70
```

Bypass the fit filter only when manually importing a cleaned list:

```bash
python src/import_creators.py --file data/sample_creators.csv --group new_leads --skip-fit-filter
```

## Discovery query direction

Use query language like this upstream:

```text
site:tiktok.com/@ comedy challenge creator family friendly
site:tiktok.com/@ POV skit creator brand safe
site:tiktok.com/@ TikTok creator challenge prank comedy
site:youtube.com/@ YouTube Shorts challenge comedy creator
site:youtube.com/@ TikTok style Shorts creator family friendly
creators like @joshbrownjsy TikTok challenge comedy
creators like Dylan McElliott YouTube Shorts TikTok creator
```

Avoid generic searches like:

```text
YouTube creators
small YouTubers
family channels
gaming channels
creators under 1M
```

Those searches are too broad and cause random YouTube channels to enter the list.

## Local setup

Create a `.env` file:

```env
MONDAY_TOKEN=your_monday_token_here
MONDAY_BOARD_ID=18416535896
MONDAY_DEFAULT_GROUP_ID=group_mm41wfhq
```

You can also use `MONDAY_API_KEY` instead of `MONDAY_TOKEN`.

Install dependencies:

```bash
pip install -r requirements.txt
```

Run import:

```bash
python src/import_creators.py --file data/sample_creators.csv --group new_leads
```

## GitHub Actions setup

In GitHub, go to:

```text
Settings → Secrets and variables → Actions → New repository secret
```

Add one of these secrets:

```text
MONDAY_TOKEN
```

or:

```text
MONDAY_API_KEY
```

Then run the workflow manually:

```text
Actions → Import Creators to monday → Run workflow
```

## Group keys

- `new_leads`
- `needs_review`
- `outreach_sent`
- `in_conversation`
- `booked_call`
- `do_not_contact`
- `contacted`
- `not_a_fit`

## CSV format

Use `data/sample_creators.csv` as the template.

Required minimum fields:

```csv
name,creator_name,handle,platform,public_email,profile_url
```

Recommended full fields:

```csv
name,creator_name,handle,platform,public_email,profile_url,followers,engagement_rate,bio,location,country,niche,creator_type,creator_gender,outreach_status,tier,headhunter,date_added,last_posted_date,last_contacted
```

## Next build phase

Next, connect the discovery layer directly:

```text
TikTok / YouTube Shorts search → creator data → public website/contact extraction → email verification → dedupe → fit filter → send to monday
```

Keep this tool focused on public creator/business information only. Do not use it to collect private personal emails or bypass platform restrictions.
