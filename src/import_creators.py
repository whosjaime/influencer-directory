import argparse
import pandas as pd
from monday_client import create_creator_item, GROUP_IDS


def normalize_row(row: dict) -> dict:
    cleaned = {}

    for key, value in row.items():
        if pd.isna(value):
            cleaned[key] = ""
        else:
            cleaned[key] = str(value).strip()

    return cleaned


def import_csv(file_path: str, group_key: str = "new_leads") -> None:
    group_id = GROUP_IDS.get(group_key)

    if not group_id:
        valid_groups = ", ".join(GROUP_IDS.keys())
        raise ValueError(f"Invalid group key: {group_key}. Options: {valid_groups}")

    df = pd.read_csv(file_path)

    print(f"Importing {len(df)} creators into monday group: {group_key}")

    for index, row in df.iterrows():
        creator = normalize_row(row.to_dict())

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

    args = parser.parse_args()
    import_csv(args.file, args.group)
