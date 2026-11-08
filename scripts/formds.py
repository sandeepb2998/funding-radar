"""Collect factual offering disclosures from FormDs' public, SEC-derived pages."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html.parser import HTMLParser
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

from sec import US_STATES

BASE = "https://www.formds.com"
LIST_URL = BASE + "/filings/newest"
MAX_BYTES = 4 * 1024 * 1024
AGENT = "FundingRadar/1.2 (+https://github.com/sandeepb2998/funding-radar/issues)"


@dataclass
class Element:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def elements(self, tag=None, cls=None):
        for child in self.children:
            if isinstance(child, Element):
                if (tag is None or child.tag == tag) and (cls is None or cls in child.attrs.get("class", "").split()):
                    yield child
                yield from child.elements(tag, cls)

    def text(self):
        return " ".join(" ".join(c.text() if isinstance(c, Element) else c for c in self.children).split())


class Page(HTMLParser):
    def __init__(self, body):
        super().__init__(convert_charrefs=True)
        self.root = Element("root")
        self.stack = [self.root]
        self.hidden = 0
        self.feed(body.decode("utf-8") if isinstance(body, bytes) else body)

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if self.hidden:
            return
        node = Element(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in ("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"):
            self.stack.append(node)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
            return
        if self.hidden:
            return
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, text):
        if not self.hidden:
            self.stack[-1].children.append(text)


def fetch_page(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "www.formds.com" or not (parts.path == "/robots.txt" or parts.path.startswith(("/filings/", "/issuers/"))):
        raise ValueError("Invalid public FormDs URL")
    time.sleep(0.5)
    request = Request(url, headers={"User-Agent": AGENT})
    with urlopen(request, timeout=25) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("Oversized FormDs response")
    return body


def money(text):
    if not re.fullmatch(r"\$[\d,]+(?:\.\d{1,2})?", text):
        raise ValueError("Expected an exact reported dollar amount, not a rounded figure or target")
    amount = Decimal(text[1:].replace(",", ""))
    if amount > 10**15:
        raise ValueError("Implausible reported amount")
    return int(amount) if amount == int(amount) else float(amount)


def cells(row):
    return [child for child in row.children if isinstance(child, Element) and child.tag in ("td", "th")]


def parse_listing(body):
    root = Page(body).root
    table = next(root.elements("table", "newest-filings-table"), None)
    if table is None:
        raise ValueError("Missing newest-filings table; source layout or access changed")
    records, dates, invalid = [], [], 0
    for row in table.elements("tr"):
        columns = cells(row)
        if columns and columns[0].tag == "th":
            continue
        if len(columns) != 6:
            raise ValueError("Unexpected filing-list columns")
        filed = columns[4].text()
        datetime.strptime(filed, "%Y-%m-%d")
        dates.append(filed)
        if columns[5].text() != "New Filing" or columns[2].text() in ("Yet to Sell", "$0"):
            continue
        try:
            amount = money(columns[2].text())
        except ValueError as error:
            invalid += 1
            print(f"FormDs: skipping an unparseable reported amount ({error})")
            continue
        if amount <= 0:
            continue
        link = next(columns[0].elements("a"), None)
        if link is None or not re.fullmatch(r"/issuers/[a-zA-Z0-9-]+", link.attrs.get("href", "")):
            raise ValueError("Missing issuer profile link")
        records.append({"url": BASE + link.attrs["href"], "company": link.text(),
                        "filed_on": filed, "amount": amount})
    has_next = any(re.search(r"/filings/newest\?page=\d+", link.attrs.get("href", "")) and
                   ("Next" in link.text() or "next" in link.attrs.get("rel", ""))
                   for link in root.elements("a"))
    return records, min(dates) if dates else None, has_next, invalid


def parse_profile(body, url, now):
    root = Page(body).root
    header = next(root.elements("header", "fp-header"), None)
    table = next(root.elements("table", "fp-table"), None)
    if header is None or table is None:
        raise ValueError("Missing issuer header or filing history")
    name = next(header.elements("h1"), None)
    category = next(header.elements("p", "fp-kicker"), None)
    if name is None or category is None:
        raise ValueError("Missing issuer identity or industry")
    if not category.text().startswith("Form D \u00b7 "):
        raise ValueError("Unrecognized issuer classification")
    industry = category.text().split("\u00b7", 1)[1].strip()
    facts = {}
    for block in root.elements("dl"):
        for group in block.elements("div"):
            label, value = next(group.elements("dt"), None), next(group.elements("dd"), None)
            if label is not None and value is not None:
                facts[label.text()] = value.text()
    if industry == "Pooled Investment Fund" or "pooled" in facts.get("Securities", "").lower() or facts.get("Business combination") == "Yes":
        return None
    history = [cells(row) for row in table.elements("tr")]
    history = [row for row in history if len(row) == 6 and row[1].text() in ("Initial", "Amendment")]
    if not history:
        raise ValueError("No recognizable filing history")
    latest = history[0]
    if latest[1].text() != "Initial":
        return None
    amount = money(latest[2].text())
    if amount <= 0:
        return None
    filed = datetime.strptime(latest[0].text(), "%b %d, %Y").date()
    first_sale_text = facts.get("First sale", "")
    if not first_sale_text or first_sale_text in ("Yet to occur", "Not reported", "Unknown", "\u2014"):
        first_sale = None
    else:
        first_sale = datetime.strptime(first_sale_text, "%b %d, %Y").date()
        if first_sale > filed:
            raise ValueError("Reported first sale is after filing")
    if filed > now.date():
        raise ValueError("Future filing date")
    link = next(latest[5].elements("a"), None)
    sec_url = link.attrs.get("href", "") if link else ""
    match = re.fullmatch(r"https://www\.sec\.gov/Archives/edgar/data/(\d+)/(\d{10})(\d{2})(\d{6})/xslFormDX\d+/primary_doc\.xml", sec_url)
    if not match:
        raise ValueError("Missing recognizable official filing reference")
    cik = match[1]
    accession = "-".join(match.group(i) for i in (2, 3, 4))
    header_cik = re.search(r"\bCIK\s+(\d+)", header.text())
    if not header_cik or int(header_cik[1]) != int(cik):
        raise ValueError("Issuer identity does not match the linked SEC document")
    snapshot = next((p for p in root.elements("p", "fp-caption") if p.text().startswith("Offering snapshot reported")), None)
    if snapshot is None or not any(a.attrs.get("href") == sec_url for a in snapshot.elements("a")):
        raise ValueError("First-sale snapshot is not tied to the latest filing")
    location_match = re.search(r",\s*([A-Z]{2})\s*\u00b7\s*CIK\s+(\d+)", header.text())
    if location_match and int(location_match[2]) != int(cik):
        raise ValueError("Profile CIK does not match the linked SEC document")
    us = bool(location_match and location_match[1] in US_STATES)
    stamp = now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {
        "id": "sec-" + accession, "kind": "sec_form_d", "company": name.text(),
        "amount": amount, "currency": "USD", "stage": "Private offering",
        "published_at": str(filed) + "T00:00:00Z", "first_seen_at": stamp, "last_seen_at": stamp,
        "headline": f"{name.text()}: Form D reports ${amount:,} cumulatively sold in a private offering",
        "quality": "FormDs SEC-derived disclosure; not independently fetched from SEC or proof of a completed VC round",
        "sources": [{"name": "FormDs - SEC-derived filings", "url": url},
                    {"name": "Linked SEC filing", "url": sec_url}],
        "announcement": {"date": str(first_sale) if first_sale else None,
                         "status": "reported_first_sale" if first_sale else "unverified",
                         "source_url": url, "note": "Issuer-reported first sale as published by FormDs; amount sold is cumulative, not necessarily new money this week."},
        "location": {"country": "United States" if us else None, "country_code": "US" if us else None,
                     "region": "North America" if us else None, "status": "reported" if us else "unknown",
                     "source_url": url, "note": "US state in the tracker's issuer-location header; foreign or unrecognized locations remain unknown."},
        "filing": {"accession": accession, "cik": cik, "form": "D", "filed_on": str(filed),
                   "first_sale_on": str(first_sale) if first_sale else None, "industry": industry,
                   "amount_basis": "cumulative_amount_sold", "provider": "FormDs"},
    }


def collect_formds(previous_records, previous_state, now, fetch=fetch_page, pages=8, limit=60):
    cutoff = (now - timedelta(days=180)).date().isoformat()
    week = (now - timedelta(days=6)).date().isoformat()
    records = {r["id"]: dict(r) for r in previous_records if r["filing"]["filed_on"] >= cutoff}
    processed = {k: v for k, v in previous_state.get("processed", {}).items() if v >= cutoff}
    pending = {key: value for key, value in previous_state.get("pending", {}).items() if value["filed_on"] >= cutoff}
    cursor = max(5, previous_state.get("next_page", 5))
    source = {"name": "FormDs - SEC-derived filings", "url": LIST_URL, "status": "ok",
              "items_read": 0, "accepted": 0, "invalid": 0, "excluded": 0, "pending": 0, "error": None}
    try:
        policy = RobotFileParser(BASE + "/robots.txt")
        try:
            rules = fetch(BASE + "/robots.txt").decode("utf-8")
        except HTTPError as error:
            if error.code != 404:
                raise
            print("FormDs: no robots.txt published (HTTP 404).")
            rules = ""
        if re.search(r"<(?:html|!doctype)", rules, re.I):
            raise ValueError("Unexpected HTML instead of crawl policy")
        policy.parse(rules.splitlines())
        delay = max(0.5, policy.crawl_delay(AGENT) or 0)
        rate = policy.request_rate(AGENT)
        if rate:
            if rate.requests <= 0:
                raise ValueError("Invalid crawl request rate")
            delay = max(delay, rate.seconds / rate.requests)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        source.update(status="error", error=str(error), pending=len(pending))
        print(f"FormDs: cannot establish crawl policy ({error}); no filing pages requested.")
        return list(records.values()), {"processed": processed, "pending": pending, "next_page": cursor}, source
    deadline = time.monotonic() + 240

    def request(url):
        if not policy.can_fetch(AGENT, url):
            raise PermissionError("Public tracker crawl policy disallows this path")
        if time.monotonic() + delay + 25 > deadline:
            raise TimeoutError("Per-run crawl budget reached; remaining work resumes later")
        if delay > 0.5:
            time.sleep(delay - 0.5)
        return fetch(url)

    blocked = False
    page_numbers = list(range(1, min(pages, 4) + 1)) + list(range(cursor, cursor + max(0, pages - 4)))
    for page_number in page_numbers:
        try:
            entries, oldest, more, invalid = parse_listing(request(LIST_URL + (f"?page={page_number}" if page_number > 1 else "")))
            source["items_read"] += len(entries)
            source["invalid"] += invalid
            if invalid:
                source["status"] = "partial"
            source["oldest_indexed_on"] = min(source.get("oldest_indexed_on", oldest) or oldest or week, oldest or week)
            for entry in entries:
                if entry["filed_on"] < week:
                    continue
                key = f"{entry['url']}|{entry['filed_on']}|{entry['amount']}"
                if key not in processed:
                    pending[key] = entry
            if page_number >= cursor:
                cursor = page_number + 1
            if not more or (oldest and oldest < week):
                cursor = 5
                break
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            source.update(status="error", error=f"HTTP {error.code}" if isinstance(error, HTTPError) else str(error))
            print(f"FormDs: {source['error']}; stopping requests for this run.")
            blocked = True
            break
    if not blocked:
        ordered = sorted(pending.items(), key=lambda item: (
            bool(re.search(r"\bfund\b|\blp\b|\bl\.p\.|\bpartners\b", item[1]["company"], re.I)),
            -datetime.strptime(item[1]["filed_on"], "%Y-%m-%d").toordinal(), item[0]))
        for key, entry in ordered[:limit]:
            try:
                row = parse_profile(request(entry["url"]), entry["url"], now)
                if row and row["filing"]["filed_on"] >= cutoff:
                    if row["id"] in records:
                        row["first_seen_at"] = records[row["id"]]["first_seen_at"]
                    records[row["id"]] = row
                    source["accepted"] += 1
                else:
                    source["excluded"] += 1
            except (HTTPError, URLError, TimeoutError, OSError) as error:
                source.update(status="partial" if source["accepted"] else "error",
                              error=f"HTTP {error.code}" if isinstance(error, HTTPError) else str(error))
                print(f"FormDs: {source['error']}; stopping requests for this run.")
                break
            except ValueError as error:
                source["invalid"] += 1
                source["status"] = "partial"
                print(f"FormDs {entry['url']}: invalid profile ({error})")
                continue
            processed[key] = entry["filed_on"]
            pending.pop(key)
    source["pending"] = len(pending)
    source["next_page"] = cursor
    state = {"processed": processed, "pending": pending, "next_page": cursor}
    return list(records.values()), state, source
