from __future__ import annotations

import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

from sponsor_dedupe import normalize_domain, normalize_email


EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)

PREFERRED_EMAILS = {
    "sponsorships": (100, "Sponsorships"),
    "sponsor": (98, "Sponsorships"),
    "partnerships": (96, "Partnerships"),
    "partnership": (94, "Partnerships"),
    "creators": (92, "Creator Partnerships"),
    "creator": (90, "Creator Partnerships"),
    "influencers": (90, "Influencer Marketing"),
    "influencer": (88, "Influencer Marketing"),
    "marketing": (84, "Marketing"),
    "bizdev": (82, "Business Development"),
    "business": (78, "Business"),
    "press": (65, "Press"),
    "media": (64, "Media"),
    "hello": (58, "General"),
    "info": (55, "General"),
    "contact": (55, "General"),
    "support": (35, "Support"),
}

BLOCKED_LOCALPARTS = {
    "noreply", "no-reply", "donotreply", "do-not-reply", "privacy", "legal", "abuse",
    "security", "careers", "jobs", "hr", "billing", "accounts", "webmaster",
}

CONTACT_PATH_HINTS = {
    "contact", "partnership", "partner", "sponsor", "creator", "influencer", "affiliate",
    "marketing", "press", "media", "about",
}

CATEGORY_RULES = {
    "Software / SaaS": {"software", "saas", "platform", "productivity", "workflow", "cloud", "app"},
    "Cybersecurity / VPN": {"vpn", "cybersecurity", "cyber security", "online privacy", "password manager"},
    "Finance": {"banking", "credit card", "investing", "finance", "financial", "payments", "insurance"},
    "Food & Beverage": {"meal", "food", "recipe", "snack", "beverage", "coffee", "nutrition"},
    "Health & Wellness": {"wellness", "health", "supplement", "vitamin", "therapy", "sleep", "fitness"},
    "Beauty": {"beauty", "skincare", "skin care", "cosmetics", "makeup", "haircare"},
    "Fashion": {"fashion", "apparel", "clothing", "footwear", "jewelry", "jewellery"},
    "Gaming": {"gaming", "game", "games", "esports"},
    "Consumer Tech": {"headphones", "keyboard", "laptop", "smartphone", "camera", "electronics", "gadget"},
    "Travel": {"travel", "hotel", "flight", "vacation", "tourism", "booking"},
    "Education": {"education", "learning", "course", "language learning", "tutoring"},
    "Home": {"furniture", "mattress", "home", "kitchen", "cleaning", "decor"},
    "Automotive": {"automotive", "vehicle", "car", "cars", "auto"},
    "Entertainment": {"streaming", "entertainment", "movies", "music", "podcast"},
}

SUBCATEGORY_RULES = {
    "VPN": {"vpn", "virtual private network"},
    "Cybersecurity": {"cybersecurity", "cyber security", "online security"},
    "Password Manager": {"password manager", "passwords"},
    "Meal Delivery": {"meal delivery", "meal kit", "meal kits"},
    "Web Hosting": {"web hosting", "hosting provider", "hosting"},
    "Website Builder": {"website builder", "build a website"},
    "Personal Finance": {"personal finance", "budgeting"},
    "Banking": {"bank account", "banking"},
    "Credit Cards": {"credit card", "credit cards"},
    "Supplements": {"supplement", "supplements", "vitamin", "vitamins"},
    "Skincare": {"skincare", "skin care"},
    "Apparel": {"apparel", "clothing"},
}


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.links.append(value)

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.text_parts.append(value)


@dataclass
class BrandEnrichment:
    domain: str
    contact_email: str = ""
    email_type: str = ""
    contact_source: str = ""
    category: str = "Other"
    subcategory: str = ""


class BrandEnricher:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (compatible; SponsorLeadScanner/1.0; public-business-contact-research)",
                "Accept": "text/html,application/xhtml+xml",
            }
        )

    def _fetch(self, url: str) -> tuple[str, str]:
        try:
            response = self.session.get(url, timeout=12, allow_redirects=True)
        except requests.RequestException:
            return "", ""
        content_type = response.headers.get("Content-Type", "").lower()
        if response.status_code >= 400 or "html" not in content_type:
            return "", ""
        return response.url, response.text[:1_500_000]

    @staticmethod
    def _parse_page(page_html: str) -> tuple[list[str], str]:
        parser = _PageParser()
        try:
            parser.feed(page_html)
        except Exception:
            pass
        text = " ".join(parser.text_parts)
        return parser.links, re.sub(r"\s+", " ", html.unescape(text))[:200_000]

    @staticmethod
    def _same_brand_domain(candidate: str, brand_domain: str) -> bool:
        candidate = normalize_domain(candidate)
        brand_domain = normalize_domain(brand_domain)
        return candidate == brand_domain or candidate.endswith(f".{brand_domain}") or brand_domain.endswith(f".{candidate}")

    @staticmethod
    def _email_rank(email: str, domain: str) -> tuple[int, str]:
        email = normalize_email(email)
        if "@" not in email:
            return (-1, "")
        local, host = email.rsplit("@", 1)
        local = local.lower()
        host = normalize_domain(host)
        if local in BLOCKED_LOCALPARTS:
            return (-1, "")
        if not BrandEnricher._same_brand_domain(host, domain):
            return (-1, "")

        best_score = 45
        best_type = "Public Business Contact"
        for keyword, (score, label) in PREFERRED_EMAILS.items():
            if keyword in local and score > best_score:
                best_score = score
                best_type = label
        return (best_score, best_type)

    @staticmethod
    def _classify(text: str) -> tuple[str, str]:
        lowered = text.lower()
        category_scores: dict[str, int] = {}
        for category, keywords in CATEGORY_RULES.items():
            category_scores[category] = sum(1 for keyword in keywords if keyword in lowered)
        category = max(category_scores, key=category_scores.get) if category_scores and max(category_scores.values()) > 0 else "Other"

        sub_scores: dict[str, int] = {}
        for subcategory, keywords in SUBCATEGORY_RULES.items():
            sub_scores[subcategory] = sum(1 for keyword in keywords if keyword in lowered)
        subcategory = max(sub_scores, key=sub_scores.get) if sub_scores and max(sub_scores.values()) > 0 else ""
        return category, subcategory

    def enrich(self, domain: str) -> BrandEnrichment:
        domain = normalize_domain(domain)
        if not domain:
            return BrandEnrichment(domain="")

        homepage_url = f"https://{domain}"
        final_url, homepage_html = self._fetch(homepage_url)
        if not homepage_html:
            final_url, homepage_html = self._fetch(f"http://{domain}")
        if not homepage_html:
            return BrandEnrichment(domain=domain)

        final_domain = normalize_domain(final_url) or domain
        if final_domain and final_domain not in {"bit.ly", "tinyurl.com", "t.co", "goo.gl"}:
            domain = final_domain

        links, homepage_text = self._parse_page(homepage_html)
        pages: list[tuple[str, str]] = [(final_url or homepage_url, homepage_html)]

        relevant_urls: list[str] = []
        for href in links:
            absolute = urljoin(final_url or homepage_url, href)
            parsed = urlparse(absolute)
            if parsed.scheme not in {"http", "https"}:
                continue
            if not self._same_brand_domain(parsed.netloc, domain):
                continue
            haystack = f"{parsed.path} {parsed.query}".lower()
            if any(hint in haystack for hint in CONTACT_PATH_HINTS):
                clean = absolute.split("#", 1)[0]
                if clean not in relevant_urls:
                    relevant_urls.append(clean)
            if len(relevant_urls) >= 6:
                break

        for url in relevant_urls:
            fetched_url, page_html = self._fetch(url)
            if page_html:
                pages.append((fetched_url or url, page_html))

        ranked_emails: list[tuple[int, str, str, str]] = []
        all_text = [homepage_text]
        for source_url, page_html in pages:
            _, page_text = self._parse_page(page_html)
            all_text.append(page_text)
            decoded = html.unescape(page_html)
            for email in set(EMAIL_RE.findall(decoded)) | set(EMAIL_RE.findall(page_text)):
                email = normalize_email(email).strip(".,;:()[]<>")
                rank, email_type = self._email_rank(email, domain)
                if rank >= 0:
                    ranked_emails.append((rank, email, email_type, source_url))

        ranked_emails.sort(key=lambda item: (-item[0], item[1]))
        best = ranked_emails[0] if ranked_emails else None
        category, subcategory = self._classify(" ".join(all_text))

        return BrandEnrichment(
            domain=domain,
            contact_email=(best[1] if best else ""),
            email_type=(best[2] if best else ""),
            contact_source=(best[3] if best else ""),
            category=category,
            subcategory=subcategory,
        )
