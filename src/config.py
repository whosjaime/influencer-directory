import os
from dotenv import load_dotenv

load_dotenv()

MONDAY_TOKEN = os.getenv("MONDAY_TOKEN") or os.getenv("MONDAY_API_KEY")
MONDAY_BOARD_ID = int(os.getenv("MONDAY_BOARD_ID", "18416535896"))
MONDAY_DEFAULT_GROUP_ID = os.getenv("MONDAY_DEFAULT_GROUP_ID", "group_mm41wfhq")

if not MONDAY_TOKEN:
    raise ValueError("Missing monday token. Add MONDAY_TOKEN or MONDAY_API_KEY to your environment.")
