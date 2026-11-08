"""Collect factual funding signals from public RSS, without copying article bodies."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from formds import collect_formds
from sec import collect_sec

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 4 * 1024 * 1024
UTC = timezone.utc
VERB = re.compile(
    r"^(?P<company>.+?)\s+(?:(?:has|just|today|reportedly)\s+)*"
    r"(?P<verb>raises?|raised|secures?|secured|closes?|closed|"
    r"lands?|landed|bags?|receives?|received|announces?|announced|"
    r"completes?|completed)\b(?P<rest>.+)$", re.I
)
AMOUNT = re.compile(
    r"(?<![\w$])(?P<currency>US\$|CA\$|C\$|A\$|S\$|USD|EUR|GBP|INR|CAD|AUD|SGD|[$€£₹])"
    r"\s*(?P<number>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*"
    r"(?P<unit>billion|million|thousand|crores?|lakhs?|lacs?|bln|mln|mn|mm|bn|cr|[bmk])?\b(?!\d|[.,]\d)", re.I
)
CURRENCIES = {
    "$": "$", "US$": "USD", "€": "EUR", "£": "GBP", "₹": "INR",
    "CA$": "CAD", "C$": "CAD", "A$": "AUD", "S$": "SGD",
}
EXCLUDED = re.compile(
    r"\b(venture\s+(?:capital|fund|firm)|fund\s+(?:i{1,3}|iv|v|\d+)|"
    r"fund|fundraising\s+target|plans?\s+to|seeks?|seeking|"
    r"in\s+talks|could|may|reportedly|rumou?r|valuation|"
    r"acqui(?:res?|red|sition)|merger|ipo|revenue|contracts?|orders?|"
    r"federal|municipal|taxpayer|government\s+funding|state\s+funding|"
    r"dividends?|preferred\s+shares|share\s+repurchase|combined|"
    r"lawsuit|donations?|grants?|crowdfunding|roundup|round-up)\b", re.I
)
COUNTRIES = {
    "US": ("United States", "North America"), "CA": ("Canada", "North America"),
    "MX": ("Mexico", "Latin America & Caribbean"), "BR": ("Brazil", "Latin America & Caribbean"),
    "GB": ("United Kingdom", "Europe"), "DE": ("Germany", "Europe"),
    "FR": ("France", "Europe"), "FI": ("Finland", "Europe"),
    "SE": ("Sweden", "Europe"), "NO": ("Norway", "Europe"),
    "DK": ("Denmark", "Europe"), "NL": ("Netherlands", "Europe"),
    "IE": ("Ireland", "Europe"), "ES": ("Spain", "Europe"),
    "IT": ("Italy", "Europe"), "CH": ("Switzerland", "Europe"),
    "AT": ("Austria", "Europe"), "BE": ("Belgium", "Europe"),
    "PL": ("Poland", "Europe"), "EE": ("Estonia", "Europe"),
    "PT": ("Portugal", "Europe"), "GR": ("Greece", "Europe"),
    "IL": ("Israel", "Middle East & Africa"), "AE": ("United Arab Emirates", "Middle East & Africa"),
    "SA": ("Saudi Arabia", "Middle East & Africa"), "ZA": ("South Africa", "Middle East & Africa"),
    "KE": ("Kenya", "Middle East & Africa"), "NG": ("Nigeria", "Middle East & Africa"),
    "EG": ("Egypt", "Middle East & Africa"), "IN": ("India", "Asia-Pacific"),
    "CN": ("China", "Asia-Pacific"), "JP": ("Japan", "Asia-Pacific"),
    "SG": ("Singapore", "Asia-Pacific"), "AU": ("Australia", "Asia-Pacific"),
    "NZ": ("New Zealand", "Asia-Pacific"), "KR": ("South Korea", "Asia-Pacific"),
}
LOCATION_PREFIXES = {
    "US": r"US|U\.S\.|American|United States|San Francisco|Los Angeles|Chicago|New York",
    "CA": r"Canada|Canadian|Toronto|Vancouver",
    "GB": r"UK|U\.K\.|United Kingdom|British|London|Oxford",
    "DE": r"Germany|German|Berlin|Munich", "FR": r"France|French|Paris",
    "FI": r"Finland|Finnish|Helsinki", "SE": r"Sweden|Swedish|Stockholm",
    "NO": r"Norway|Norwegian|Oslo", "DK": r"Denmark|Danish|Copenhagen",
    "NL": r"Netherlands|Dutch|Amsterdam", "IE": r"Ireland|Irish|Dublin",
    "IL": r"Israel|Israeli|Tel Aviv", "IN": r"India|Indian|Bengaluru|Bangalore|Mumbai",
    "CN": r"China|Chinese|Beijing|Shanghai", "JP": r"Japan|Japanese|Tokyo",
    "SG": r"Singapore|Singaporean", "AU": r"Australia|Australian|Sydney",
    "BR": r"Brazil|Brazilian", "MX": r"Mexico|Mexican",
}


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(text):
    parser = TextOnly()
    parser.feed(text or "")
    return " ".join(html.unescape("".join(parser.parts)).split())


def key(text):
    return "".join(c for c in unicodedata.normalize("NFKC", text.replace("\u2122", "").replace("\u00ae", "")).casefold() if c.isalnum())


def location_fact(code=None, source_url=None, status="unknown", note=""):
    country, region = COUNTRIES[code] if code else (None, None)
    return {"country": country, "country_code": code, "region": region,
            "status": status, "source_url": source_url, "note": note}


def headline_location(title, source_url):
    for code, names in LOCATION_PREFIXES.items():
        match = re.match(
            rf"^(?:{names})(?:['\u2019]s\s+|[- ]based\s+|\s+(?:[\w-]+\s+){{0,3}}(?:startup|start-up|company|firm)\s+)",
            title, re.I,
        )
        if match:
            return location_fact(code, source_url, "reported", "Company location stated in headline; not verified headquarters.")
    return location_fact()


def timestamp(value):
    if not value:
        raise ValueError("Missing publication date")
    try:
        result = parsedate_to_datetime(value)
    except (ValueError, TypeError):
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Publication date has no timezone")
    return result.astimezone(UTC)


def iso(value):
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_url(value):
    parts = urlsplit(value.strip())
    if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password:
        raise ValueError("Invalid source URL")
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.startswith("utm_") and k not in ("fbclid", "gclid")]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, urlencode(query), ""))


def feed_url(source):
    if source.get("kind") == "news_search":
        country = source.get("country", "US")
        return "https://news.google.com/rss/search?" + urlencode({
            "q": source["query"], "hl": f"en-{country}",
            "gl": country, "ceid": f"{country}:en",
        })
    return source["url"]


def parse_feed(content):
    if len(content) > MAX_BYTES or b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise ValueError("Oversized feed or unsupported XML declarations")
    root = ET.fromstring(content)
    if root.tag.split("}")[-1] not in ("rss", "feed", "RDF"):
        raise ValueError("Response is not an RSS/Atom feed")
    entries = []
    for node in root.iter():
        if node.tag.split("}")[-1] not in ("item", "entry"):
            continue
        fields = {}
        for child in node:
            tag = child.tag.split("}")[-1]
            if tag == "link":
                if child.attrib.get("rel", "alternate") == "alternate":
                    fields["link"] = child.attrib.get("href") or child.text or ""
            elif tag in ("title", "pubDate", "published", "date", "source"):
                fields[tag] = "".join(child.itertext())
                if tag == "source":
                    fields["publisher_url"] = child.attrib.get("url")
        entries.append({
            "title": plain(fields.get("title", "")),
            "url": fields.get("link", ""),
            "published": fields.get("pubDate") or fields.get("published") or fields.get("date"),
            "publisher": plain(fields.get("source", "")),
            "publisher_url": fields.get("publisher_url"),
        })
    return entries


def extract(entry, source, now):
    title = entry["title"]
    publisher = entry.get("publisher", "")
    if source.get("kind") == "news_search" and publisher:
        suffix = " - " + publisher
        if title.endswith(suffix):
            title = title[:-len(suffix)].strip()
        publisher_host = urlsplit(entry.get("publisher_url") or "").hostname or ""
        if publisher_host.endswith((".gov", ".gov.uk", ".gov.in", ".mil")):
            return None
    title = re.sub(r"^(?:exclusive\s*[:|]\s*|\{funding alert\}\s*|\[funding alert\]\s*)", "", title, flags=re.I)
    if re.search(r"\b(reportedly|rumou?red|could|may)\b", title, re.I):
        return None
    match = VERB.match(title)
    if not match:
        return None
    subject = match["company"].strip(" ,:;")
    if re.search(r"\b(fund|capital|ventures|investors?|founders?|senator|congressman|county|council)\b", subject, re.I):
        return None
    if "," in subject or re.search(r"\b(promises?|says?|aims?|startups|companies|firms)\b", subject, re.I):
        return None
    # Valuation clauses are common after a real raise; never use their amounts.
    rest = re.split(r"\b(?:at a|at|with a)\s+.*?\bvaluation\b", match["rest"], flags=re.I)[0]
    if EXCLUDED.search(subject + " " + rest):
        return None
    if re.search(r"\bseries\s+[A-K]\s+(?:and|&)\s+(?:series\s+)?[A-K]\b|\bpre[- ]seed\s+(?:and|&)\s+seed\b", rest, re.I):
        return None
    if match["verb"].lower().startswith(("announc", "complet")) and not re.search(
        r"\b(funding|financing|round|seed|series\s+[A-K]|investment)\b", rest, re.I
    ):
        return None
    amount = AMOUNT.search(rest)
    if not amount or amount.start() > 50:
        return None
    suffix = rest[amount.end():]
    if re.match(r"\s*(?:[-\u2013\u2014+/]|\b(?:or|trillion|trn|tn)\b|\bto\s+(?=[$€£₹\d]|USD|EUR|GBP))", suffix, re.I):
        return None
    if len(list(AMOUNT.finditer(rest))) != 1:
        return None
    prefix = rest[:amount.start()]
    if re.search(r"\b(to|target|up to|over|more than|nearly|about|approximately)\b", prefix, re.I):
        return None
    if re.search(r"\b(startup|start-up|company|firm|business|platform)\s*$", subject, re.I):
        return None
    for _ in range(2):
        subject = re.sub(r"^(?:[\w'\u2019.-]+\s+){0,5}(?:startup|start-up|company)\s+", "", subject, flags=re.I)
        subject = re.sub(r"^(?:[\w'\u2019.-]+\s+){1,5}(?:platform|firm|app)\s+", "", subject, flags=re.I)
        subject = re.sub(r"^[\w-]+-based\s+", "", subject, flags=re.I)
        subject = re.sub(r"^(?:[\w-]+\s+){1,3}spin[- ]?out\s+", "", subject, flags=re.I)
        subject = re.sub(r"^(?:Helsinki|London|Paris|Berlin|Amsterdam|Stockholm|Copenhagen|Dublin|Oxford|Cambridge|India|Europe|Germany|France|Finland|Sweden|China|Israel|Japan|Singapore|Australia|Canada|Norway|UK|US)['\u2019]s\s+", "", subject, flags=re.I)
    if not 2 <= len(subject) <= 80 or len(subject.split()) > 6:
        return None
    published = timestamp(entry["published"])
    if published > now + timedelta(minutes=5) or published < now - timedelta(days=180):
        return None
    raw_currency = amount["currency"].upper()
    currency = CURRENCIES.get(raw_currency, raw_currency)
    unit = (amount["unit"] or "").lower()
    if not unit:
        following_word = re.match(r"\s*([a-z]+)", suffix, re.I)
        if following_word and following_word[1].lower() not in {
            "in", "for", "from", "to", "at", "with", "of", "and", "as", "led", "backed",
            "seed", "pre", "series", "funding", "financing", "investment", "round",
            "debt", "equity", "venture",
        }:
            return None
    indian_unit = unit in ("cr", "crore", "crores", "lakh", "lakhs", "lac", "lacs")
    if indian_unit and currency != "INR":
        return None
    factor = (
        10**9 if unit in ("b", "bn", "bln", "billion") else
        10**6 if unit in ("m", "mn", "mln", "mm", "million") else
        10**7 if unit in ("cr", "crore", "crores") else
        10**5 if unit in ("lakh", "lakhs", "lac", "lacs") else
        1000 if unit in ("k", "thousand") else 1
    )
    value = Decimal(amount["number"].replace(",", "")) * factor
    if not 0 < value <= 10**12:
        return None
    stage_match = re.search(r"\b(?P<pre>pre[- ])?series\s+(?P<letter>[A-K])(?P<extension>[- ]?\d+|\+)?(?!\w)", rest, re.I)
    stage = ("Pre-Series " if stage_match["pre"] else "Series ") + stage_match["letter"].upper() + (stage_match["extension"] or "").strip() if stage_match else (
        "Pre-seed" if re.search(r"\bpre[- ]seed\b", rest, re.I) else
        "Seed" if re.search(r"\bseed\b", rest, re.I) else
        "Debt" if re.search(r"\b(debt|credit facility|loan)\b", rest, re.I) else
        "Undisclosed"
    )
    url = canonical_url(entry["url"])
    return {
        "id": hashlib.sha256(url.encode()).hexdigest()[:20],
        "company": subject,
        "amount": int(value) if value == int(value) else float(value),
        "currency": currency,
        "stage": stage,
        "published_at": iso(published),
        "first_seen_at": iso(now),
        "last_seen_at": iso(now),
        "headline": title,
        "sources": [{"name": f"{publisher} via Google News" if publisher and source.get("kind") == "news_search" else source["name"], "url": url}],
        "quality": "Headline-extracted; verify source",
        "announcement": {"date": None, "status": "unverified"},
        "location": headline_location(title, url),
    }


def same_event(left, right):
    if any(s["url"] == t["url"] for s in left["sources"] for t in right["sources"]):
        return True
    return (
        key(left["company"]) == key(right["company"])
        and left["amount"] == right["amount"]
        and left["currency"] == right["currency"]
        and (left["stage"] == right["stage"] or "Undisclosed" in (left["stage"], right["stage"]))
        and abs(timestamp(left["published_at"]) - timestamp(right["published_at"])) <= timedelta(days=7)
    )


def merge_records(existing, incoming, now):
    records = [dict(r, sources=[dict(s) for s in r["sources"]]) for r in existing
               if timestamp(r["published_at"]) >= now - timedelta(days=180)]
    for candidate in incoming:
        previous = next((r for r in records if same_event(r, candidate)), None)
        if previous is None:
            records.append(dict(candidate, sources=[dict(s) for s in candidate["sources"]]))
            continue
        if any(s["url"] == t["url"] for s in previous["sources"] for t in candidate["sources"]):
            old_identity = tuple(previous[k] for k in ("company", "amount", "currency", "stage"))
            for field in ("company", "amount", "currency", "stage", "headline", "published_at"):
                if field == "stage" and candidate["stage"] == "Undisclosed" and previous["stage"] != "Undisclosed":
                    continue
                previous[field] = candidate[field]
            if old_identity != tuple(previous[k] for k in ("company", "amount", "currency", "stage")):
                previous["announcement"] = {"date": None, "status": "unverified"}
            if key(old_identity[0]) != key(previous["company"]):
                previous["location"] = candidate.get("location", location_fact())
        elif previous["stage"] == "Undisclosed" and candidate["stage"] != "Undisclosed":
            previous["stage"] = candidate["stage"]
            previous["announcement"] = {"date": None, "status": "unverified"}
        previous["first_seen_at"] = min(previous["first_seen_at"], candidate["first_seen_at"])
        previous["last_seen_at"] = max(previous["last_seen_at"], candidate["last_seen_at"])
        old_location = previous.get("location", location_fact())
        new_location = candidate.get("location", location_fact())
        if old_location["status"] != "conflicting":
            if old_location.get("country_code") and new_location.get("country_code") and old_location["country_code"] != new_location["country_code"]:
                previous["location"] = location_fact(status="conflicting", note="Sources report different company locations; review required.")
            elif not old_location.get("country_code") and new_location.get("country_code"):
                previous["location"] = new_location
        old_date = previous.get("announcement", {})
        new_date = candidate.get("announcement", {})
        if new_date.get("status") == "first_reported" and (not old_date.get("date") or new_date["date"] < old_date["date"]):
            previous["announcement"] = new_date
        for source in candidate["sources"]:
            existing_source = next((s for s in previous["sources"] if s["url"] == source["url"]), None)
            if existing_source:
                existing_source.update(source)
            else:
                previous["sources"].append(source)
    return sorted(records, key=lambda r: (r["published_at"], r["id"]), reverse=True)


def reparse_records(records, now):
    reparsed = []
    rejected = 0
    for record in records:
        primary = record["sources"][0]
        updated = extract(
            {"title": record["headline"], "url": primary["url"], "published": record["published_at"]},
            primary, now,
        )
        if updated is None:
            rejected += 1
            continue
        if updated["stage"] == "Undisclosed":
            updated["stage"] = record["stage"]
        for field in ("id", "first_seen_at", "last_seen_at", "sources"):
            updated[field] = record[field]
        unchanged = key(updated["company"]) == key(record["company"]) and all(
            updated[k] == record[k] for k in ("amount", "currency", "stage"))
        if unchanged and record.get("announcement", {}).get("status") in ("first_reported", "unverified"):
            updated["announcement"] = record.get("announcement", updated["announcement"])
        old_location = record.get("location", {})
        if old_location.get("status") == "conflicting" or (
            key(updated["company"]) == key(record["company"]) and
            not updated["location"]["country_code"] and old_location.get("status") == "reported"
        ):
            updated["location"] = old_location
        reparsed.append(updated)
    if rejected:
        print(f"Archive revalidation: {rejected} expired or nonqualifying headlines removed.", file=sys.stderr)
    return reparsed


def fetch_feed(source):
    for attempt in range(2):
        try:
            request = Request(feed_url(source), headers={"User-Agent": "FundingRadar/1.1 (+https://sandeepb2998.github.io/funding-radar/; public RSS reader)", "Accept": "application/rss+xml, application/atom+xml, application/xml"})
            with urlopen(request, timeout=25) as response:
                body = response.read(MAX_BYTES + 1)
            return parse_feed(body), None
        except (URLError, TimeoutError, OSError, ValueError, ET.ParseError) as error:
            transient = not isinstance(error, HTTPError) or error.code in (429, 500, 502, 503, 504)
            if attempt == 0 and transient:
                time.sleep(2)
            else:
                detail = f"HTTP {error.code}" if isinstance(error, HTTPError) else f"{type(error).__name__}: {error}"
                return [], detail[:250]


def collect(previous, feeds, now, fetch=fetch_feed):
    if not feeds:
        raise ValueError("At least one feed is required")
    candidates, statuses = [], []
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(fetch, feeds))
    for source, (entries, error) in zip(feeds, results):
        status = {"name": source["name"], "url": feed_url(source), "status": "error" if error else "ok",
                  "error": error, "items_read": len(entries), "accepted": 0, "invalid": 0}
        for entry in entries[:200]:
            try:
                record = extract(entry, source, now)
            except (ValueError, TypeError, KeyError) as error:
                status["invalid"] += 1
                print(f"{source['name']}: invalid feed item ({type(error).__name__})", file=sys.stderr)
                continue
            if record:
                candidates.append(record)
                status["accepted"] += 1
        statuses.append(status)
    healthy = sum(s["status"] == "ok" for s in statuses)
    state = {
        "schema_version": 1,
        "last_attempt_at": iso(now),
        "last_success_at": iso(now) if healthy else previous.get("last_success_at"),
        "status": "ok" if healthy == len(feeds) else "partial" if healthy else "error",
        "sources": statuses,
        "records": merge_records([], reparse_records(previous.get("records", []), now) + candidates, now) if healthy else previous.get("records", []),
    }
    return state


def apply_reviews(records, reviews, now):
    """Bind reviewed facts to an existing source, not a company-name guess."""
    seen = set()
    for review in reviews:
        source_id = review["source_id"]
        if source_id in seen:
            raise ValueError(f"Duplicate reviewed source: {source_id}")
        seen.add(source_id)
        date = review.get("date")
        status = review.get("status", "reviewed")
        if status not in ("reviewed", "disputed"):
            raise ValueError("Review status must be reviewed or disputed")
        if status == "reviewed":
            if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                raise ValueError("Reviewed announcement needs an explicit ISO date")
            if datetime.strptime(date, "%Y-%m-%d").date() > now.date():
                raise ValueError("Reviewed announcement date is in the future")
        elif date is not None:
            raise ValueError("Disputed announcements must not expose an asserted date")
        evidence = canonical_url(review["evidence_url"])
        country = review.get("country_code")
        if country is not None and country not in COUNTRIES:
            raise ValueError("Unknown reviewed country code")
        location_url = canonical_url(review["location_evidence_url"]) if country else None
        for record in records:
            source_ids = {hashlib.sha256(canonical_url(s["url"]).encode()).hexdigest()[:20] for s in record["sources"]}
            if source_id not in source_ids:
                continue
            if key(record["company"]) != key(review["company"]) or any(record[k] != review[k] for k in ("amount", "currency", "stage")):
                raise ValueError(f"Reviewed round no longer matches source {source_id}; review the extraction")
            record["announcement"] = {"date": date, "status": status, "source_url": evidence,
                                      "note": review["note"]}
            if country:
                record["location"] = location_fact(country, location_url, "reviewed", review["location_note"])


def resolve_history(records, now, fetch=fetch_feed, limit=12):
    """Find earlier matching reports without calling their dates verified funding dates."""
    pending = []
    for record in records:
        if record.get("kind") == "sec_form_d":
            continue
        info = record.get("announcement", {})
        if info.get("status") in ("reviewed", "disputed"):
            continue
        checked = timestamp(info["checked_at"]) if info.get("checked_at") else None
        retry = timedelta(hours=1) if info.get("check_status") == "error" else timedelta(days=7)
        if checked is None or now - checked >= retry:
            pending.append(record)
    pending.sort(key=lambda r: r.get("announcement", {}).get("checked_at", ""))
    selected = pending[:limit]
    feeds = [{"name": f"Historical coverage: {r['company']}", "kind": "news_search",
              "query": f'"{r["company"]}" (funding OR raises OR raised OR financing)'} for r in selected]
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(fetch, feeds))
    for record, source, (entries, error) in zip(selected, feeds, results):
        info = dict(record.get("announcement", {"date": None, "status": "unverified"}), checked_at=iso(now))
        if error:
            info["check_status"] = "error"
            print(f"{source['name']}: {error}", file=sys.stderr)
        else:
            matches = []
            for entry in entries[:100]:
                try:
                    published = timestamp(entry["published"])
                    if published > now + timedelta(minutes=5):
                        continue
                    candidate = extract(entry, source, published)
                    if candidate and key(candidate["company"]) == key(record["company"]) and all(candidate[k] == record[k] for k in ("amount", "currency", "stage")):
                        matches.append(candidate)
                except (ValueError, TypeError, KeyError) as error:
                    print(f"{source['name']}: invalid historical item ({type(error).__name__})", file=sys.stderr)
            info["check_status"] = "ok" if matches else "no_match"
            if matches:
                earliest = min(matches, key=lambda r: r["published_at"])
                if not info.get("date") or earliest["published_at"][:10] < info["date"]:
                    info.update(date=earliest["published_at"][:10], status="first_reported",
                                source_url=earliest["sources"][0]["url"],
                                note="Earliest matching indexed report found; not a verified announcement or closing date.")
                if record.get("location", {}).get("status") != "conflicting" and not record.get("location", {}).get("country_code") and earliest["location"]["country_code"]:
                    record["location"] = earliest["location"]
        record["announcement"] = info
    print(f"Historical date checks: {len(selected)} attempted; {max(0, len(pending) - len(selected))} awaiting a later run.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data/funding.json")
    parser.add_argument("--feeds", type=Path, default=ROOT / "config/feeds.json")
    parser.add_argument("--reviews", type=Path, default=ROOT / "config/reviews.json")
    args = parser.parse_args()
    previous = json.loads(args.data.read_text()) if args.data.exists() else {}
    feeds = json.loads(args.feeds.read_text())
    reviews = json.loads(args.reviews.read_text())
    now = datetime.now(UTC)
    news_previous = {**previous, "records": [r for r in previous.get("records", []) if r.get("kind") != "sec_form_d"]}
    result = collect(news_previous, feeds, now)
    apply_reviews(result["records"], reviews, now)
    if result["status"] != "error":
        resolve_history(result["records"], now)
    offerings = [r for r in previous.get("records", []) if r.get("kind") == "sec_form_d"]
    official, sec_state, sec_status = collect_sec(
        [r for r in offerings if r["filing"].get("provider") == "SEC"],
        previous.get("sec_state", {}), now, COUNTRIES)
    tracked, tracker_state, tracker_status = collect_formds(
        [r for r in offerings if r["filing"].get("provider") == "FormDs"],
        previous.get("formds_state", {}), now)
    combined = {r["id"]: r for r in tracked + official}
    result["records"].extend(combined.values())
    result["sources"].extend((sec_status, tracker_status))
    result["sec_state"] = sec_state
    result["formds_state"] = tracker_state
    healthy = sum(s["status"] == "ok" for s in result["sources"])
    useful = healthy or any(s["accepted"] > 0 for s in result["sources"])
    result["status"] = "ok" if healthy == len(result["sources"]) else "partial" if useful else "error"
    if useful:
        result["last_success_at"] = iso(now)
    args.data.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.data.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n")
    temporary.replace(args.data)
    for source in result["sources"]:
        print(f"{source['name']}: {source['status']}; {source['accepted']} funding signals"
              + (f"; {source['error']}" if source["error"] else ""))
    print(f"{len(result['records'])} retained records; collection status: {result['status']}")
    return 1 if result["status"] == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
