import re

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

BAD_EMAIL_KEYWORDS = [
    "example.com",
    "yourdomain.com",
    "domain.com",
    "email.com",
]


def extract_emails(text: str) -> list[str]:
    if not text:
        return []

    found = EMAIL_PATTERN.findall(text)
    cleaned = []

    for email in found:
        email = email.strip().lower().rstrip(".,;:)]}")
        if any(bad in email for bad in BAD_EMAIL_KEYWORDS):
            continue
        if email not in cleaned:
            cleaned.append(email)

    return cleaned


def first_email(text: str) -> str:
    emails = extract_emails(text)
    return emails[0] if emails else ""
