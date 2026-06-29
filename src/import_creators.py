import argparse
import pandas as pd
from dedupe_utils import creator_keys, is_blocked_creator, load_blocklist
from discovery_filters import DEFAULT_MIN_FIT_SCORE, filter_creators
from monday_client import create_creator_item, get_existing_creator_keys, GROUP_IDS


def normalize_row(row: dict) -> dict:
    cleaned = {}

    for key, value in row.items():
        if pd.isna(value):
            cleaned[key] = ""
        else:
            cleaned[key] = str(value).strip()

    return cleaned


def remove_blocked_and_duplicates(creators: list[dict]) -> tuple[list[dict], int, int]:
    blocklist = load_blocklist()
    existing_keys = get_existing_creator_keys()
    seen_keys = set()
    importable = []
    blocked_count = 0
    duplicate_count = 0

    for creator in creators:
        keys = creator_keys(creator)
        label = creator.get("handle") or creator.get("creator_name") or creator.get("name") or "Unknown creator"

        if is_blocked_creator(creator, blocklist):
            blocked_count += 1
            print(f"Skipped blocked creator: {label}")
            continue

        if keys & existing_keys or keys & seen_keys:
            duplicate_count += 1
            print(f"Skipped duplicate creator: {label}")
            continue

        seen_keys.update(keys)
        importable.append(creator)

    return importable, blocked_count, duplicate_count


def import_csv(
    file_path: str,
    group_key: str = "new_leads",
    min_fit_score: int = DEFAULT_MIN_FIT_SCORE,
    apply_fit_filter: bool = True,
    apply_dedupe: bool = True,
) -> None:
    group_id = GROUP_IDS.get(group_key)

    if not group_id:
        valid_groups = ", ".join(GROUP_IDS.keys())
        raise ValueError(f"Invalid group key: {group_key}. Options: {valid_groups}")

    df = pd.read_csv(file_path)
    creators = [normalize_row(row.to_dict()) for _, row in df.iterrows()]

    if apply_fit_filter:
        creators, rejected = filter_creators(creators, min_fit_score=min_fit_score)
        print(f"Fit filter: keeping {len(creators)} creators, skipping {len(rejected)} non-fit creators")

        for creator, fit in rejected:
            label = creator.get("handle") or creator.get("creator_name") or creator.get("name") or "Unknown creator"
            print(f"Skipped non-fit creator {label}: score {fit.score} / reasons: {', '.join(fit.reasons)}")

    if apply_dedupe:
        creators, blocked_count, duplicate_count = remove_blocked_and_duplicates(creators)
        print(f"Dedupe/blocklist filter: keeping {len(creators)} creators, skipped {duplicate_count} duplicates and {blocked_count} blocked creators")

    print(f"Importing {len(creators)} creators into monday group: {group_key}")

    for index, creator in enumerate(creators):
        try:
            result = create_creator_item(creator, group_id=group_id)
            item = result["data"]["create_item"]
            print(f"Created item: {item['name']} / ID: {item['id']}")

        except Exception as error:
            print(f"Failed row {index + 1}: {creator}")
            print(f"Error: {error}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import creators into the monday.com Influencer Directory.")
    parser.add_argument("--file", required=True, help="CSV file path")
    parser.add_argument(
        "--group",
        default="new_leads",
        help="Group key: new_leads, needs_review, outreach_sent, in_conversation, booked_call, do_not_contact, contacted, not_a_fit",
    )
    parser.add_argument(
        "--min-fit-score",
        type=int,
        default=DEFAULT_MIN_FIT_SCORE,
        help="Minimum TikTok/Shorts lookalike fit score required before importing",
    )
    parser.add_argument(
        "--skip-fit-filter",
        action="store_true",
        help="Import every row without the TikTok/Shorts lookalike fit filter",
    )
    parser.add_argument(
        "--skip-dedupe",
        action="store_true",
        help="Do not check monday.com for existing creators before importing",
    )

    args = parser.parse_args()
    import_csv(
        args.file,
        args.group,
        min_fit_score=args.min_fit_score,
        apply_fit_filter=not args.skip_fit_filter,
        apply_dedupe=not args.skip_dedupe,
    )
