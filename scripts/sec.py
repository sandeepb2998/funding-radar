"""Read official Form D notices; never treat an offering target as capital sold."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

BASE = "https://www.sec.gov/Archives/"
SOURCE_URL = BASE + "edgar/daily-index/"
MAX_BYTES = 8 * 1024 * 1024
US_STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split())


def is_fund_name(name):
    return bool(re.search(r"\bfunds?\b", name, re.I))


def fetch_sec(url):
    if not url.startswith(BASE):
        raise ValueError("SEC requests must use the official archive")
    time.sleep(0.5)
    agent = os.environ.get("SEC_USER_AGENT") or "FundingRadar/1.2 (+https://github.com/sandeepb2998/funding-radar/issues)"
    request = Request(url, headers={"User-Agent": agent, "Accept-Encoding": "identity"})
    with urlopen(request, timeout=25) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("Oversized SEC response")
    return body


def parse_index(body):
    text = body.decode("utf-8")
    if "CIK|Company Name|Form Type|Date Filed|Filename" not in text:
        raise ValueError("Response is not an SEC master index")
    records = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) != 5 or parts[2] != "D":
            continue
        cik, company, form, filed, path = parts
        match = re.fullmatch(r"edgar/data/(\d+)/(\d{10}-\d{2}-\d{6})\.txt", path)
        if not match or not cik.isdigit() or int(match[1]) != int(cik):
            raise ValueError("Invalid SEC filing path")
        datetime.strptime(filed, "%Y-%m-%d")
        records.append({"cik": cik, "company": company, "form": form,
                        "filed_on": filed, "path": path, "accession": match[2]})
    return records


def parse_filing(body, filing, now, countries):
    if len(body) > MAX_BYTES or b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ValueError("Unsafe or oversized SEC XML")
    match = re.search(rb"<XML>\s*(.*?)\s*</XML>", body, re.S | re.I)
    root = ET.fromstring(match[1] if match else body)
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    if root.tag != "edgarSubmission":
        raise ValueError("Not a Form D submission")

    def field(path):
        return (root.findtext(path) or "").strip()

    if field("submissionType") != "D":
        return None
    company = field("primaryIssuer/entityName")
    if not company:
        raise ValueError("Missing issuer name")
    industry = field("offeringData/industryGroup/industryGroupType")
    if (is_fund_name(company) or industry == "Pooled Investment Fund"
            or field("offeringData/industryGroup/investmentFundInfo/investmentFundType")
            or field("offeringData/typesOfSecuritiesOffered/isPooledInvestmentFundType") == "true"
            or field("offeringData/typeOfFiling/newOrAmendment/isAmendment") == "true"
            or field("offeringData/businessCombinationTransaction/isBusinessCombinationTransaction") == "true"):
        return None
    try:
        sold = Decimal(field("offeringData/offeringSalesAmounts/totalAmountSold").replace(",", ""))
    except InvalidOperation as error:
        raise ValueError("Invalid amount sold") from error
    if not sold.is_finite() or sold < 0 or sold > 10**15:
        raise ValueError("Invalid amount sold")
    if sold == 0:
        return None
    first_sale = field("offeringData/typeOfFiling/dateOfFirstSale/value")
    if field("offeringData/typeOfFiling/dateOfFirstSale/yetToOccur") == "true" or not first_sale:
        raise ValueError("Positive amount sold without an actual first-sale date")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", first_sale):
        raise ValueError("Invalid first-sale date")
    filed = datetime.strptime(filing["filed_on"], "%Y-%m-%d").date()
    if filed > now.date():
        raise ValueError("Filing date is in the future")
    if datetime.strptime(first_sale, "%Y-%m-%d").date() > filed:
        raise ValueError("First sale is after filing date")
    cik = field("primaryIssuer/cik")
    if not cik.isdigit() or int(cik) != int(filing["cik"]):
        raise ValueError("Issuer CIK does not match the index")
    state = field("primaryIssuer/issuerAddress/stateOrCountry")
    description = field("primaryIssuer/issuerAddress/stateOrCountryDescription")
    country = "US" if state in US_STATES else next(
        (code for code, (name, _) in countries.items() if name.casefold() == description.casefold()), None)
    country_name, region = countries[country] if country else (None, None)
    source_url = BASE + filing["path"]
    stamp = now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    amount = int(sold) if sold == int(sold) else float(sold)
    return {
        "id": "sec-" + filing["accession"], "kind": "sec_form_d", "company": company,
        "amount": amount, "currency": "USD", "stage": "Private offering",
        "published_at": filing["filed_on"] + "T00:00:00Z",
        "first_seen_at": stamp, "last_seen_at": stamp,
        "headline": f"{company}: Form D reports ${amount:,} cumulatively sold in a private offering",
        "quality": "Issuer-reported SEC notice; not SEC approval or proof of a completed VC round",
        "sources": [{"name": "SEC EDGAR - Form D", "url": source_url}],
        "announcement": {"date": first_sale, "status": "filed_first_sale", "source_url": source_url,
                         "note": "Issuer-reported first sale, not the filing date or completion of the offering. Amount sold is cumulative."},
        "location": {"country": country_name, "country_code": country, "region": region,
                     "status": "filed" if country else "unknown", "source_url": source_url,
                     "note": "Country from the issuer's business address, not SEC registration or incorporation."},
        "filing": {"accession": filing["accession"], "cik": cik, "form": "D",
                   "filed_on": filing["filed_on"], "first_sale_on": first_sale,
                   "industry": industry, "amount_basis": "cumulative_amount_sold", "provider": "SEC"},
    }


def collect_sec(previous_records, previous_state, now, countries, fetch=fetch_sec, limit=80):
    cutoff = (now - timedelta(days=180)).date().isoformat()
    records = {r["id"]: dict(r) for r in previous_records if r["filing"]["filed_on"] >= cutoff and not is_fund_name(r["company"])}
    processed = {k: v for k, v in previous_state.get("processed", {}).items() if v >= cutoff}
    pending = {r["accession"]: r for r in previous_state.get("pending", []) if r["filed_on"] >= cutoff}
    recent_days = [(now - timedelta(days=n)).date() for n in range(1, 8)
                   if (now - timedelta(days=n)).weekday() < 5]
    cached = set(previous_state.get("index_days", [])) & {str(d) for d in recent_days}
    status = {"name": "SEC EDGAR - Form D", "url": SOURCE_URL, "status": "ok",
              "items_read": 0, "accepted": 0, "invalid": 0, "excluded": 0, "pending": 0, "error": None}

    def failed(error):
        status["error"] = f"HTTP {error.code}" if isinstance(error, HTTPError) else f"{type(error).__name__}: {error}"
        status["status"] = "partial" if status["accepted"] else "error"
        print(f"SEC EDGAR: {status['error']}; stopping requests for this run.")

    blocked = False
    for day in recent_days:
        if str(day) in cached:
            continue
        url = f"{SOURCE_URL}{day.year}/QTR{(day.month-1)//3+1}/master.{day:%Y%m%d}.idx"
        try:
            rows = parse_index(fetch(url))
            status["items_read"] += len(rows)
            for row in rows:
                if row["accession"] not in processed:
                    pending[row["accession"]] = row
            cached.add(str(day))
        except HTTPError as error:
            if error.code == 404:
                continue
            failed(error)
            blocked = True
            break
        except (URLError, TimeoutError, OSError, ValueError) as error:
            failed(error)
            blocked = True
            break
    if not blocked:
        for filing in sorted(pending.values(), key=lambda r: (r["filed_on"], r["accession"]), reverse=True)[:limit]:
            try:
                row = parse_filing(fetch(BASE + filing["path"]), filing, now, countries)
                if row:
                    if row["id"] in records:
                        row["first_seen_at"] = records[row["id"]]["first_seen_at"]
                    records[row["id"]] = row
                    status["accepted"] += 1
                else:
                    status["excluded"] += 1
            except (HTTPError, URLError, TimeoutError, OSError) as error:
                failed(error)
                break
            except (ValueError, ET.ParseError) as error:
                status["invalid"] += 1
                status["status"] = "partial"
                print(f"SEC EDGAR {filing['accession']}: invalid filing ({error})")
                continue
            processed[filing["accession"]] = filing["filed_on"]
            pending.pop(filing["accession"])
    status["pending"] = len(pending)
    status["index_days"] = sorted(cached)
    if not cached and status["status"] == "ok":
        status.update(status="error", error="No completed daily index available")
        print("SEC EDGAR: no completed daily index available.")
    state = {"processed": processed, "pending": list(pending.values()), "index_days": sorted(cached)}
    return list(records.values()), state, status
