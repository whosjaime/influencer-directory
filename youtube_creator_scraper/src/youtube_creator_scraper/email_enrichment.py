from __future__ import annotations

import re
from html import unescape
from typing import List, Set

EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.+-])", re.IGNORECASE)
BAD_EMAIL_PARTS = {
    "example.com",
    "domain.com",
    "email.com",
    "yourname",
    "youremail",
    "name@example",
    "test@",
}


def clean_email(email: str) -> str:
    return email.strip().strip(".,;:()[]{}<>\"'").lower()


def extract_public_emails(text: str | None) -> List[str]:
    """Extract emails that appear directly in public text, such as a YouTube channel description.

    This does not bypass YouTube's email button, CAPTCHA, login walls, or private data.
    """
    if not text:
        return []

    found: Set[str] = set()
    for match in EMAIL_RE.findall(unescape(text)):
        email = clean_email(match)
        if any(bad in email for bad in BAD_EMAIL_PARTS):
            continue
        if email.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            continue
        found.add(email)
    return sorted(found)
