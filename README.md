# Manifest Media Influencer Directory

This repo imports creator/influencer leads into the Manifest Media monday.com Influencer Directory board.

## monday board

- Board ID: `18416535896`
- Default group: `New Leads`
- Default group ID: `group_mm41wfhq`

## What this does now

This first version imports creators from a CSV into monday.com.

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
- last contacted date

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

Next, add the creator discovery layer:

```text
YouTube search/API → creator data → public website/contact extraction → email verification → dedupe → send to monday
```

Keep this tool focused on public creator/business information only. Do not use it to collect private personal emails or bypass platform restrictions.
