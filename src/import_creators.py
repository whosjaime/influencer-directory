import argparse
import pandas as pd
from discovery_filters import DEFAULT_MIN_FIT_SCORE, filter_creators
from monday_client import create_creator_item, GROUP_IDS


def normalize_row(row: dict) -> dict:
    cleaned = {}

    for key, value in row.items():
        if pd.isna(value):
            cleaned[key] = ""
        else:
            cleaned[key] = str(value).strip()

    return cleaned


def import_csv(
    file_path: str,
    group_key: str = "new_leads",
    min_fit_score: int = DEFAULT_MIN_FIT_SCORE,
    apply_fit_filter: bool = True,
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
            print(f"Skipped {label}: score {fit.score} / reasons: {', '.join(fit.reasons)}")

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

    args = parser.parse_args()
    import_csv(
        args.file,
        args.group,
        min_fit_score=args.min_fit_score,
        apply_fit_filter=not args.skip_fit_filter,
    )
