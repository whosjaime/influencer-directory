# Sponsor Lead Scanner Setup

This workflow is intentionally isolated from the existing Influencer Directory monday board.

It scans recent public YouTube sponsorship signals, classifies the creator, identifies the sponsor, looks for a public business contact on the sponsor's own website, blocks duplicates against the full client monday board, and imports only qualified NEW sponsor companies.

## Required GitHub secrets

Go to:

`Settings -> Secrets and variables -> Actions -> Secrets`

Add:

- `YOUTUBE_API_KEY` — Google Cloud API key with YouTube Data API v3 enabled
- `SPONSOR_MONDAY_TOKEN` — the CLIENT monday API token
- `DISCORD_WEBHOOK_URL` — webhook for the CLIENT Discord channel (optional but recommended)

You can use `SPONSOR_MONDAY_API_KEY` instead of `SPONSOR_MONDAY_TOKEN`.

The sponsor scanner deliberately does NOT fall back to the old `MONDAY_TOKEN`, `MONDAY_API_KEY`, or old board ID. This prevents an accidental write into the existing Manifest Media board.

## Required GitHub variables

Go to:

`Settings -> Secrets and variables -> Actions -> Variables`

Add:

- `SPONSOR_MONDAY_BOARD_ID` — required
- `SPONSOR_MONDAY_GROUP_ID` — optional. Leave blank to auto-select a group named New Leads/Leads, otherwise the first group.
- `SPONSOR_TARGET_DAILY_LEADS` — default `20`
- `SPONSOR_MIN_LEAD_SCORE` — default `70`
- `SPONSOR_SEARCH_REGION` — default `US`
- `SPONSOR_SEARCH_LANGUAGE` — default `en`

Leave these disabled for now:

- `ENABLE_INSTAGRAM_SPONSOR_SCAN=false`
- `ENABLE_TIKTOK_SPONSOR_SCAN=false`

The code is structured for more sources, but the working V1 source is YouTube. Instagram/TikTok should only be enabled after their official source adapters and client credentials are configured.

## Recommended monday board columns

The code reads the client board schema and automatically finds columns by title, so you do not need to hardcode monday column IDs.

Recommended columns:

| Column title | Recommended type |
| --- | --- |
| Brand | Text |
| Brand Domain | Link or Text |
| Contact Email | Email |
| Email Type | Text or Dropdown |
| Email Source | Link |
| Brand Category | Dropdown |
| Brand Subcategory | Dropdown |
| Creator | Text |
| Creator URL | Link |
| Creator Subscribers | Numbers |
| Creator Genre | Dropdown |
| Creator Tags | Dropdown or Text |
| Platform | Dropdown |
| Sponsored Video | Link |
| Video Title | Text |
| Sponsored Date | Date |
| Evidence | Long Text |
| Paid Promotion | Checkbox or Status |
| Lead Score | Numbers |
| Temperature | Status |
| Brand Key | Text |
| Sponsorship Key | Text |
| Outreach Status | Status |
| Date Found | Date |

The board does not need every column to run. Missing optional columns are simply skipped. For the strongest duplicate protection, keep `Brand`, `Brand Domain`, `Contact Email`, `Brand Key`, `Sponsorship Key`, and `Outreach Status`.

## Duplicate protection

Duplicate prevention is intentionally strict.

Every daily run:

1. Scans every item on the full client monday board using cursor pagination.
2. Builds duplicate keys from brand names, domains, public contact emails, brand keys, and sponsorship event keys.
3. Scans YouTube.
4. Enriches the sponsor and checks duplicates again using the final/canonical website and email.
5. Scans the complete monday board a second time immediately before writes.
6. Adds each successful write to the in-run duplicate index immediately.
7. GitHub Actions concurrency prevents two sponsor scanner workflows from writing at the same time.

A repeat sponsorship from an existing company is NOT counted as a new lead and is NOT imported again.

Protected outreach statuses include Outreach Sent, Contacted, Follow Up, In Conversation, Call Booked, Working With, Client, Do Not Contact, Rejected, Not Interested, and Closed.

## Daily lead target

The default target is 20 qualified NEW sponsor companies.

The scanner searches in widening windows:

- previous 24 hours
- previous 72 hours
- previous 7 days

It deduplicates across all windows. If fewer than 20 genuinely new qualified companies are available, it reports the lower number rather than lowering the quality threshold or re-importing a duplicate.

## Sponsor detection

Signals include:

- YouTube's paid product placement flag
- explicit `Sponsored by ...`
- `Thanks to ... for sponsoring ...`
- `Brought to you by ...`
- `In partnership with ...`
- `#ad`
- `#sponsored`
- YouTube brand partner metadata when available
- external sponsor links in the video description

## Creator classification

The scanner stores a primary genre and useful tags based on the channel/video metadata.

Primary genres include Gaming, Tech, Finance, Business, Beauty, Fashion, Fitness, Health, Food, Travel, Sports, Automotive, Family, Comedy, Entertainment, Education, Music, Home, Outdoors, Pets, Lifestyle, and Other.

Tags can include Minecraft, Fortnite, Roblox, Family Friendly, Challenges, Pranks, Comedy, Reactions, Long Form, Short Form, Tech, and Lifestyle.

## Public contact enrichment

When a sponsor domain is available, the scanner checks the sponsor's public website and a small number of public contact/partnership/creator/marketing pages.

Email preference is roughly:

1. sponsorships@
2. partnerships@
3. creators@ / influencer@
4. marketing@
5. business development
6. press/media
7. hello@ / info@
8. support@ only as a fallback

It does not guess private email addresses. Emails must be publicly exposed on the sponsor's own website and match the sponsor's domain.

## Discord

If `DISCORD_WEBHOOK_URL` is configured, the daily run posts a summary containing:

- new qualified leads
- duplicates blocked
- rejected low-confidence detections
- YouTube videos scanned
- up to 20 newly created sponsor leads with creator genre, score, and email status

## Run manually

After the secrets and variables are configured:

`Actions -> Daily Sponsor Lead Scan -> Run workflow`

The scheduled workflow runs once per day after it is merged into the repository's default branch.
