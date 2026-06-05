from pathlib import Path
from urllib.parse import urlparse

BLOCKLIST_PATH = Path("data/do_not_scrape.txt")


def normalize_text(value: str) -> str:
    if not value:
        return ""
    return str(value).strip().lower()


def normalize_handle(value: str) -> str:
    value = normalize_text(value)
    value = value.replace("https://www.instagram.com/", "")
    value = value.replace("https://instagram.com/", "")
    value = value.replace("https://www.tiktok.com/@", "")
    value = value.replace("https://tiktok.com/@", "")
    value = value.strip("/@ ")
    return value


def normalize_url(value: str) -> str:
    value = normalize_text(value)
    if not value:
        return ""
    parsed = urlparse(value)
    netloc = parsed.netloc.replace("www.", "")
    path = parsed.path.strip("/")
    return f"{netloc}/{path}".strip("/")


def creator_keys(creator: dict) -> set[str]:
    keys = set()

    for field in ["handle", "creator_name", "name", "public_email"]:
        raw = creator.get(field, "")
        if raw:
            keys.add(normalize_text(raw))

    handle = normalize_handle(creator.get("handle", ""))
    if handle:
        keys.add(handle)
        keys.add(f"@{handle}")

    profile_url = normalize_url(creator.get("profile_url", ""))
    if profile_url:
        keys.add(profile_url)

    email = normalize_text(creator.get("public_email", ""))
    if email:
        keys.add(email)
        if "@" in email:
            keys.add(email.split("@")[-1])

    return {key for key in keys if key}


def load_blocklist(path: Path = BLOCKLIST_PATH) -> set[str]:
    if not path.exists():
        return set()

    entries = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entries.add(normalize_text(line))
        entries.add(normalize_handle(line))
        entries.add(normalize_url(line))

    return {entry for entry in entries if entry}


def is_blocked_creator(creator: dict, blocklist: set[str] | None = None) -> bool:
    blocklist = blocklist if blocklist is not None else load_blocklist()
    keys = creator_keys(creator)
    return any(key in blocklist for key in keys)


def dedupe_key(creator: dict) -> str:
    platform = normalize_text(creator.get("platform", ""))
    handle = normalize_handle(creator.get("handle", ""))
    profile_url = normalize_url(creator.get("profile_url", ""))
    email = normalize_text(creator.get("public_email", ""))
    name = normalize_text(creator.get("creator_name", "") or creator.get("name", ""))

    if platform and handle:
        return f"{platform}:{handle}"
    if profile_url:
        return f"url:{profile_url}"
    if email:
        return f"email:{email}"
    return f"name:{name}"
