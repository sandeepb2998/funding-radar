import unittest
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from urllib.error import HTTPError

from test_collector import NOW, SOURCE, record
from formds import LIST_URL, collect_formds, parse_listing, parse_profile
from urllib.parse import parse_qs, urlsplit
from build import public_data
from collect import main

URL = "https://www.formds.com/issuers/example-robotics-inc"
SEC_URL = "https://www.sec.gov/Archives/edgar/data/1234567/000123456726000001/xslFormDX01/primary_doc.xml"


def listing(amount="$12,000,000", form="New Filing"):
    return f"""<table class="newest-filings-table"><tr><th>Company</th></tr>
    <tr><td><a href="/issuers/example-robotics-inc">Example Robotics Inc.</a></td><td>Yes</td>
    <td>{amount}</td><td>$12,000,000</td><td>2026-11-06</td><td>{form}</td></tr></table>""".encode()


def profile(amount="$12,000,000", first_sale="Oct 22, 2026", form="Initial",
            industry="Other Technology", location="San Francisco, CA", combination="No"):
    return f"""<header class="fp-header"><p class="fp-kicker">Form D · {industry}</p>
    <h1>Example Robotics Inc.</h1><p>{location} · CIK 0001234567</p></header>
    <p class="fp-caption">Offering snapshot reported Nov 6, 2026 · <a href="{SEC_URL}">SEC filing</a></p>
    <dl><div><dt>Reported sold</dt><dd>$12M</dd><small>Offering amount: $20M</small></div>
    <div><dt>First sale</dt><dd>{first_sale}</dd></div></dl>
    <table class="fp-table"><tr><th>Filed</th><th>Filing type</th><th>Reported sold</th><th>Change</th><th>Investors</th><th>Source</th></tr>
    <tr><th>Nov 6, 2026</th><td>{form}</td><td>{amount}</td><td>No comparison</td><td>12</td>
    <td><a href="{SEC_URL}">SEC filing</a></td></tr></table>
    <dl><div><dt>Securities</dt><dd>Equity</dd></div><div><dt>Business combination</dt><dd>{combination}</dd></div></dl>
    <section id="issuer-people"><p>Private Person private@example.test</p></section>
    <address>Private street address</address>""".encode()


class FormDsTests(unittest.TestCase):
    def test_exact_amount_not_rounded_snapshot_or_offering_target(self):
        row = parse_profile(profile(), URL, NOW)
        self.assertEqual(row["amount"], 12_000_000)
        self.assertEqual(row["filing"]["filed_on"], "2026-11-06")
        self.assertEqual(row["announcement"]["date"], "2026-10-22")
        self.assertEqual(row["location"]["country"], "United States")
        self.assertEqual(row["filing"]["provider"], "FormDs")
        self.assertNotIn("Private Person", str(row))
        self.assertNotIn("private@example.test", str(row))
        self.assertNotIn("Private street", str(row))

    def test_listing_ignores_amendments_and_unsold_offerings(self):
        for kwargs in ({"form": "Amended"}, {"amount": "$0"}, {"amount": "Yet to Sell"}):
            self.assertEqual(parse_listing(listing(**kwargs))[0], [])
        self.assertEqual(len(parse_listing(listing())[0]), 1)
        rows, _, _, invalid = parse_listing(listing(amount="$12M"))
        self.assertEqual(rows, [])
        self.assertEqual(invalid, 1)

    def test_weekly_query_uses_the_published_list_controls_and_preserves_pagination(self):
        query = parse_qs(urlsplit(LIST_URL).query)
        self.assertEqual(query["filters_params[date_select]"], ["Last Week"])
        self.assertEqual(query["filters_params[new_amended_select]"], ["New Filings"])
        self.assertEqual(query["filters_params[list_or_map_select]"], ["Show as a list"])
        html = listing().replace(b"newest-filings-table", b"filing-cards-xs")
        html += b'<a rel="next" href="/filings/advanced_filter?filters_params%5Bdate_select%5D=Last+Week&amp;page=2">2</a>'
        self.assertTrue(parse_listing(html)[2])
        html = html.replace(b'rel="next"', b'rel="prev"')
        self.assertFalse(parse_listing(html)[2])

    def test_industry_and_fund_names_are_filtered_before_profile_requests(self):
        by_industry = listing().replace(b"</a>", b'</a><span class="hidden-xs">(Pooled Investment Fund)</span>')
        self.assertEqual(parse_listing(by_industry)[0], [])
        by_name = listing().replace(b"Example Robotics Inc.", b"Example Credit Fund LLC")
        self.assertEqual(parse_listing(by_name)[0], [])

    def test_profiles_exclude_pooled_funds_business_combinations_and_amendments(self):
        for kwargs in ({"industry": "Pooled Investment Fund"}, {"combination": "Yes"},
                       {"form": "Amendment"}, {"amount": "$0"}):
            with self.subTest(kwargs=kwargs):
                self.assertIsNone(parse_profile(profile(**kwargs), URL, NOW))
        named_fund = profile().replace(b"Example Robotics Inc.", b"Example Credit Fund 2026 LLC")
        self.assertIsNone(parse_profile(named_fund, URL, NOW))

    def test_previously_collected_named_funds_are_removed(self):
        row = parse_profile(profile(), URL, NOW)
        row["company"] = "Example Credit Fund 2026 LLC"
        def fetch(url):
            return b"User-agent: *\nDisallow: /" if url.endswith("/robots.txt") else self.fail("No pages allowed")
        rows, _, _ = collect_formds([row], {}, NOW, fetch=fetch)
        self.assertEqual(rows, [])

    def test_date_precision_and_identity_are_validated(self):
        for body in (profile(first_sale="Nov 7, 2026"), profile(amount="$12M"),
                     profile().replace(b"CIK 0001234567", b"CIK 0009999999"),
                     profile().replace(b"Offering snapshot reported", b"Unrelated snapshot")):
            with self.assertRaises(ValueError):
                parse_profile(body, URL, NOW)

    def test_foreign_location_not_inferred_from_sec_registration(self):
        row = parse_profile(profile(location="London, United Kingdom"), URL, NOW)
        self.assertIsNone(row["location"]["country"])

    def test_first_sale_unknown_stays_unknown_not_filing_date(self):
        row = parse_profile(profile(first_sale="Not reported"), URL, NOW)
        self.assertIsNone(row["announcement"]["date"])
        self.assertEqual(row["announcement"]["status"], "unverified")

    def test_source_layout_change_fails_explicitly(self):
        with self.assertRaises(ValueError):
            parse_listing(b"<html>Sign in</html>")
        with self.assertRaises(ValueError):
            parse_profile(b"<html>Sign in</html>", URL, NOW)

    def test_collection_deduplicates_and_preserves_first_discovery(self):
        def fetch(url):
            if url.endswith("/robots.txt"):
                return b"User-agent: *\nDisallow: /issuers/search"
            return listing() if "/filings/" in url else profile()
        rows, state, source = collect_formds([], {}, NOW, fetch=fetch)
        self.assertEqual(len(rows), 1)
        self.assertEqual(source["accepted"], 1)
        rows2, _, source2 = collect_formds(rows, state, NOW, fetch=fetch)
        self.assertEqual(rows2, rows)
        self.assertEqual(source2["accepted"], 0)

    def test_denial_is_not_retried_or_replaced_with_fabricated_data(self):
        calls = []
        def fetch(url):
            calls.append(url)
            raise HTTPError(url, 403, "Forbidden", {}, None)
        rows, state, source = collect_formds([], {}, NOW, fetch=fetch)
        self.assertEqual(rows, [])
        self.assertEqual(source["status"], "error")
        self.assertEqual(len(calls), 1)

    def test_bad_profile_stays_pending_for_parser_repair(self):
        def fetch(url):
            if url.endswith("/robots.txt"):
                return b"User-agent: *\nDisallow: /issuers/search"
            return listing() if "/filings/" in url else b"<html>Unexpected layout</html>"
        rows, state, source = collect_formds([], {}, NOW, fetch=fetch)
        self.assertEqual(source["invalid"], 1)
        self.assertEqual(source["pending"], 1)
        self.assertEqual(state["processed"], {})

    def test_disallowed_paths_are_not_requested(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return b"User-agent: *\nDisallow: /"
        rows, _, source = collect_formds([], {}, NOW, fetch=fetch)
        self.assertEqual(len(calls), 1)
        self.assertEqual(rows, [])
        self.assertEqual(source["status"], "error")

    def test_public_allowlist_excludes_provider_people_and_queue(self):
        row = parse_profile(profile(), URL, NOW)
        row["filing"]["email"] = "private@example.test"
        state = {"schema_version": 1, "last_attempt_at": None, "last_success_at": None, "status": "ok",
                 "records": [row], "sources": [], "formds_state": {"pending": {"private": "do not publish"}}}
        output = public_data(state)
        self.assertNotIn("formds_state", output)
        self.assertNotIn("private@example.test", str(output))
        self.assertEqual(output["records"][0]["filing"]["amount_basis"], "cumulative_amount_sold")

    def test_pipeline_preserves_filing_records_and_reports_direct_sec_failure_separately(self):
        offering = parse_profile(profile(), URL, NOW)
        news = {"schema_version": 1, "last_attempt_at": "2026-11-08T14:00:00Z",
                "last_success_at": "2026-11-08T14:00:00Z", "status": "ok",
                "records": [record()], "sources": [{"name": "News", "status": "ok", "accepted": 1, "error": None}]}
        previous = {**news, "records": [record(), offering], "formds_state": {"next_page": 9}}
        denied = {"name": "SEC", "status": "error", "accepted": 0, "error": "HTTP 403"}
        healthy = {"name": "FormDs", "status": "ok", "accepted": 1, "error": None}
        with tempfile.TemporaryDirectory() as folder:
            data, feeds, reviews = (Path(folder) / name for name in ("data.json", "feeds.json", "reviews.json"))
            data.write_text(json.dumps(previous))
            feeds.write_text(json.dumps([SOURCE]))
            reviews.write_text("[]")
            with patch("sys.argv", ["collect", "--data", str(data), "--feeds", str(feeds), "--reviews", str(reviews)]), \
                 patch("collect.collect", return_value=news) as news_call, \
                 patch("collect.resolve_history"), \
                 patch("collect.collect_sec", return_value=([], {}, denied)), \
                 patch("collect.collect_formds", return_value=([offering], {"next_page": 13}, healthy)) as tracker_call:
                self.assertEqual(main(), 0)
            self.assertEqual(len(news_call.call_args.args[0]["records"]), 1)
            self.assertEqual(tracker_call.call_args.args[0], [offering])
            saved = json.loads(data.read_text())
            self.assertEqual(saved["status"], "partial")
            self.assertEqual(len(saved["records"]), 2)
            self.assertEqual(saved["formds_state"]["next_page"], 13)
