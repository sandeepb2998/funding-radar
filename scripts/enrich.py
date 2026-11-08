"""Optional licensed business-contact lookup. Results are private, never site data."""

import csv
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from collect import canonical_url, iso, key, timestamp

ROOT = Path(__file__).resolve().parents[1]
MAX_DOMAINS = 20


def reviewed_domains(companies):
    result = {}
    for company in companies:
        domain = company["domain"].lower().strip()
        if not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}", domain):
            raise ValueError("Reviewed company has an invalid domain")
        evidence = canonical_url(company["evidence_url"])
        if not company["company"].strip():
            raise ValueError("Reviewed company name is empty")
        name = key(company["company"])
        if name in result:
            raise ValueError("Duplicate reviewed company name")
        result[name] = {"domain": domain, "evidence_url": evidence}
    return result


def founder_contacts(response, domain):
    contacts = []
    for person in response["data"]["emails"]:
        role = person.get("position") or ""
        if not re.search(r"\bfounder\b", role, re.I) or re.search(r"\b(former|ex|previous)\b", role, re.I):
            continue
        email = person.get("value", "")
        verification = person.get("verification") or {}
        if (person.get("type") != "personal"
                or verification.get("status") != "valid"
                or email.rsplit("@", 1)[-1].lower() != domain
                or not person.get("first_name") or not person.get("last_name")):
            continue
        sources = []
        for source in person.get("sources", []):
            uri = source.get("uri")
            if uri and urlsplit(uri).scheme in ("https", "http"):
                sources.append(canonical_url(uri))
        contacts.append({
            "name": f"{person['first_name']} {person['last_name']}",
            "role": role, "email": email, "verification": "valid",
            "verified_at": verification.get("date"), "sources": sources,
        })
    return contacts


def lookup(domain, api_key):
    query = urlencode({"domain": domain, "api_key": api_key, "limit": 100, "type": "personal"})
    request = Request(f"https://api.hunter.io/v2/domain-search?{query}", headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            payload = response.read(2 * 1024 * 1024 + 1)
            if len(payload) > 2 * 1024 * 1024:
                raise ValueError("Provider response exceeded size limit")
            data = json.loads(payload)
    except HTTPError as error:
        # URL and provider bodies may contain the secret; never log either.
        raise RuntimeError(f"Hunter returned HTTP {error.code}") from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError("Hunter connection failed") from None
    if not isinstance(data.get("data", {}).get("emails"), list):
        raise ValueError("Hunter returned an unexpected response schema")
    return data


def enrich(records, companies, api_key, now, provider=lookup):
    domains = reviewed_domains(companies)
    cutoff = now - timedelta(days=1)
    recent = [r for r in records if timestamp(r["first_seen_at"]) >= cutoff]
    output = {"generated_at": iso(now), "provider": "Hunter", "status": "ok",
              "contacts": [], "coverage": [], "domain_queries": 0}
    cache = {}
    for record in recent:
        reviewed = domains.get(key(record["company"]))
        item = {"company": record["company"], "funding_id": record["id"]}
        if not reviewed:
            output["coverage"].append(dict(item, status="needs_reviewed_domain"))
            continue
        if not api_key:
            output["coverage"].append(dict(item, status="provider_not_configured"))
            continue
        domain = reviewed["domain"]
        if domain not in cache:
            if len(cache) >= MAX_DOMAINS:
                output["coverage"].append(dict(item, status="daily_query_limit"))
                continue
            try:
                cache[domain] = founder_contacts(provider(domain, api_key), domain)
            except (RuntimeError, ValueError, KeyError, TypeError):
                cache[domain] = None
                output["status"] = "partial"
                print("Contact provider request failed; no contact data or credentials logged.", file=sys.stderr)
            output["domain_queries"] += 1
        contacts = cache[domain]
        status = "provider_error" if contacts is None else "contacts_available" if contacts else "no_verified_founder_returned"
        output["coverage"].append(dict(item, domain=domain, status=status))
        for contact in contacts or []:
            output["contacts"].append(dict(item, domain=domain, domain_evidence=reviewed["evidence_url"], **contact))
    return output


def safe_csv(value):
    text = str(value or "")
    return "'" + text if re.match(r"^\s*[=+\-@\t\r]", text) else text


def main():
    now = datetime.now(timezone.utc)
    records = json.loads((ROOT / "data/funding.json").read_text())["records"]
    companies = json.loads((ROOT / "config/companies.json").read_text())
    output = enrich(records, companies, os.environ.get("HUNTER_API_KEY", ""), now)
    directory = ROOT / "private"
    directory.mkdir(exist_ok=True, mode=0o700)
    json_path, csv_path = directory / "contacts.json", directory / "contacts.csv"
    for path in (json_path, csv_path):
        path.touch(mode=0o600, exist_ok=True)
        path.chmod(0o600)
    json_path.write_text(json.dumps(output, indent=2) + "\n")
    fields = ["company", "domain", "name", "role", "email", "verification", "verified_at", "domain_evidence", "sources"]
    with csv_path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(fields)
        for contact in output["contacts"]:
            writer.writerow([safe_csv(" | ".join(contact[field]) if isinstance(contact[field], list) else contact[field]) for field in fields])
    print(f"Private enrichment: {output['domain_queries']} domain queries, {len(output['contacts'])} provider-verified founder contacts. Status: {output['status']}.")
    return 1 if output["status"] != "ok" else 0


if __name__ == "__main__":
    sys.exit(main())
