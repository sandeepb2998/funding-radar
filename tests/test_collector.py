from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect import canonical_url, collect, extract, iso, merge_records, parse_feed, timestamp
from build import build, public_data
from enrich import enrich, founder_contacts, reviewed_domains, safe_csv

NOW = datetime(2026, 11, 8, 14, 0, tzinfo=timezone.utc)
SOURCE = {"name": "Example News", "url": "https://news.example/feed"}


def entry(title="Example Labs Raises $12M in Series A", **changes):
    return {"title": title, "url": "https://news.example/raise?utm_source=rss",
            "published": "Sun, 08 Nov 2026 10:00:00 GMT", **changes}


def record(**changes):
    return {**extract(entry(), SOURCE, NOW), **changes}


class FeedTests(unittest.TestCase):
    def test_rss(self):
        body = b"""<rss><channel><item><title><![CDATA[Example &amp; Labs Raises $12M]]></title>
        <link>https://news.example/raise</link><pubDate>Sun, 08 Nov 2026 10:00:00 GMT</pubDate>
        <description>Must not republish the article body.</description></item></channel></rss>"""
        parsed = parse_feed(body)
        self.assertEqual(parsed[0]["title"], "Example & Labs Raises $12M")
        self.assertNotIn("description", parsed[0])

    def test_atom_alternate_link_and_publication_date(self):
        body = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <title>Example Labs Raises $12M</title><link rel="alternate" href="https://news.example/a"/>
        <link rel="self" href="https://news.example/api/a"/><published>2026-11-08T10:00:00Z</published>
        <updated>2026-11-09T10:00:00Z</updated></entry></feed>"""
        parsed = parse_feed(body)[0]
        self.assertEqual(parsed["url"], "https://news.example/a")
        self.assertEqual(parsed["published"], "2026-11-08T10:00:00Z")

    def test_non_feed_and_entities_rejected(self):
        for body in (b"<html>blocked</html>", b'<!DOCTYPE x [<!ENTITY x "x">]><rss/>'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse_feed(body)

    def test_oversized_feed(self):
        with self.assertRaises(ValueError):
            parse_feed(b" " * (4 * 1024 * 1024 + 1))

    def test_dates_are_timezone_aware(self):
        self.assertEqual(timestamp("2026-11-08T12:00:00+02:00").hour, 10)
        with self.assertRaises(ValueError):
            timestamp("2026-11-08")

    def test_url_cleaning(self):
        self.assertEqual(canonical_url("https://news.example/a?id=2&utm_source=x#top"), "https://news.example/a?id=2")
        for value in ("javascript:alert(1)", "//example.com/a", "https://user:pass@example.com"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_url(value)


class ExtractionTests(unittest.TestCase):
    def test_company_stage_and_amount(self):
        result = record()
        self.assertEqual(result["company"], "Example Labs")
        self.assertEqual(result["amount"], 12_000_000)
        self.assertEqual(result["stage"], "Series A")
        self.assertEqual(result["currency"], "$")
        self.assertNotIn("email", result)

    def test_currencies_and_units(self):
        for amount, expected, currency in [
            ("US$1.2 billion", 1_200_000_000, "USD"),
            ("\u20ac8.5 million", 8_500_000, "EUR"),
            ("\u00a3900k", 900_000, "GBP"), ("CA$5M", 5_000_000, "CAD"),
            ("A$2M", 2_000_000, "AUD"), ("S$3M", 3_000_000, "SGD"),
            ("INR 100 million", 100_000_000, "INR"), ("$250,000", 250_000, "$"),
        ]:
            with self.subTest(amount=amount):
                result = extract(entry(f"Example Labs Raises {amount} in Funding"), SOURCE, NOW)
                self.assertEqual((result["amount"], result["currency"]), (expected, currency))

    def test_stages(self):
        for text, stage in [("pre-seed funding", "Pre-seed"), ("seed round", "Seed"),
                            ("Series G", "Series G"), ("debt financing", "Debt"),
                            ("funding", "Undisclosed")]:
            with self.subTest(stage=stage):
                self.assertEqual(extract(entry(f"Example Raises $10M in {text}"), SOURCE, NOW)["stage"], stage)

    def test_exclude_non_deals_and_unconfirmed_rounds(self):
        headlines = [
            "Example Capital Raises $200M Fund II",
            "Example Raises $100M for New Fund",
            "Example Raises $100M Fund",
            "Example Plans to Raise $10M",
            "Example Reportedly Raises $10M",
            "Example Raises Up to $10M",
            "Example Raises About $10M",
            "Example Lands $10M Contract",
            "Example Raises $10M in Donations",
            "Example Acquires Startup for $10M",
            "Example Raises $10M in Crowdfunding",
            "Founder Raises $10M",
            "Example raises awareness of funding",
        ]
        for title in headlines:
            with self.subTest(title=title):
                self.assertIsNone(extract(entry(title), SOURCE, NOW))

    def test_raise_amount_not_valuation(self):
        result = extract(entry("Example Raises $10M at a $90M Valuation"), SOURCE, NOW)
        self.assertEqual(result["amount"], 10_000_000)

    def test_missing_company_domain_is_not_guessed(self):
        self.assertNotIn("domain", record())

    def test_expired_future_and_missing_dates(self):
        for published in (iso(NOW + timedelta(days=1)), iso(NOW - timedelta(days=181))):
            self.assertIsNone(extract(entry(published=published), SOURCE, NOW))
        with self.assertRaises(ValueError):
            extract(entry(published=None), SOURCE, NOW)

    def test_unknown_currency_not_reinterpreted_as_usd(self):
        self.assertIsNone(extract(entry("Example Raises NZ$10M"), SOURCE, NOW))

    def test_ambiguous_numbers_ranges_and_units_are_not_misreported(self):
        for amount in ("$10-20M", "$10M+", "$10M to $20M", "$10 crore", "$10 trillion", "$12,5M"):
            with self.subTest(amount=amount):
                self.assertIsNone(extract(entry(f"Example Raises {amount} in Funding"), SOURCE, NOW))

    def test_use_of_proceeds_and_punctuation_after_amount(self):
        for title in ("Example Raises $10M to Expand", "Example Raises $10M, Announces Expansion"):
            self.assertEqual(extract(entry(title), SOURCE, NOW)["amount"], 10_000_000)


class StateTests(unittest.TestCase):
    def test_idempotence_and_first_discovery_preserved(self):
        original = record()
        newer = record(first_seen_at=iso(NOW + timedelta(days=1)), last_seen_at=iso(NOW + timedelta(days=1)))
        merged = merge_records([original], [newer, newer], NOW)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["first_seen_at"], iso(NOW))
        self.assertEqual(merged[0]["last_seen_at"], newer["last_seen_at"])

    def test_cross_publisher_duplicates(self):
        other = record(id="other", sources=[{"name": "Other", "url": "https://other.example/a"}])
        merged = merge_records([record()], [other], NOW)
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0]["sources"]), 2)

    def test_corrected_source_updates_amount_preserving_discovery(self):
        original = record()
        correction = record(amount=15_000_000, first_seen_at=iso(NOW + timedelta(days=1)))
        merged = merge_records([original], [correction], NOW)
        self.assertEqual(merged[0]["amount"], 15_000_000)
        self.assertEqual(merged[0]["first_seen_at"], original["first_seen_at"])

    def test_distinct_rounds_not_collapsed(self):
        original = record()
        other = record(id="other", stage="Series B", sources=[{"name": "Other", "url": "https://other.example/b"}])
        self.assertEqual(len(merge_records([original], [other], NOW)), 2)

    def test_no_fuzzy_company_merge(self):
        other = record(id="other", company="Example Systems", sources=[{"name": "Other", "url": "https://other.example/a"}])
        self.assertEqual(len(merge_records([record()], [other], NOW)), 2)

    def test_all_failed_keeps_previous_records_and_last_success(self):
        previous = {"last_success_at": iso(NOW - timedelta(days=1)), "records": [record()]}
        result = collect(previous, [SOURCE], NOW, lambda _: ([], "Network unavailable"))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["records"], previous["records"])
        self.assertEqual(result["last_success_at"], previous["last_success_at"])

    def test_partial_failure_is_explicit(self):
        feeds = [SOURCE, {"name": "Broken", "url": "https://broken.example/feed"}]
        result = collect({}, feeds, NOW, lambda s: ([entry()], None) if s == SOURCE else ([], "HTTP 503"))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["records"]), 1)

    def test_healthy_empty_feed_is_not_failed(self):
        result = collect({}, [SOURCE], NOW, lambda _: ([], None))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["records"], [])

    def test_bad_item_does_not_discard_feed(self):
        result = collect({}, [SOURCE], NOW, lambda _: ([entry(published="bad"), entry()], None))
        self.assertEqual(result["sources"][0]["invalid"], 1)
        self.assertEqual(len(result["records"]), 1)

    def test_empty_configuration_fails(self):
        with self.assertRaises(ValueError):
            collect({}, [], NOW)


class PublicBoundaryTests(unittest.TestCase):
    def test_public_allowlist_excludes_private_data_and_provider_errors(self):
        state = collect({}, [SOURCE], NOW, lambda _: ([entry()], None))
        state["contacts"] = [{"email": "private@example.test"}]
        state["records"][0]["email"] = "private@example.test"
        state["records"][0]["domain"] = "internal.example"
        state["sources"][0]["error"] = "internal detail"
        output = json.dumps(public_data(state))
        for value in ("private@example.test", "internal.example", "internal detail", "contacts"):
            self.assertNotIn(value, output)

    def test_build_writes_only_allowlisted_files(self):
        state = collect({}, [SOURCE], NOW, lambda _: ([entry()], None))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "state.json").write_text(json.dumps(state))
            build(path / "site", path / "state.json")
            self.assertEqual({p.name for p in (path / "site").iterdir()},
                             {"index.html", "styles.css", "app.js", "data.json", ".nojekyll"})

    def test_build_refuses_existing_unrelated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "secret.txt").write_text("do not publish")
            with self.assertRaises(ValueError):
                build(path, path / "state.json")


class EnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.companies = [{"company": "Example Labs", "domain": "example.test", "evidence_url": "https://example.test/team"}]
        self.person = {"value": "founder@example.test", "type": "personal", "position": "Co-Founder",
                       "first_name": "Test", "last_name": "Founder", "verification": {"status": "valid", "date": "2026-11-08"},
                       "sources": [{"uri": "https://example.test/team"}]}

    def test_no_key_no_guess_no_call(self):
        result = enrich([record()], self.companies, "", NOW, lambda *_: self.fail("Provider should not be called"))
        self.assertEqual(result["coverage"][0]["status"], "provider_not_configured")
        self.assertEqual(result["contacts"], [])

    def test_unreviewed_domain_not_queried(self):
        result = enrich([record()], [], "not-a-real-key", NOW, lambda *_: self.fail("Provider should not be called"))
        self.assertEqual(result["coverage"][0]["status"], "needs_reviewed_domain")

    def test_only_verified_founder_in_same_domain(self):
        result = founder_contacts({"data": {"emails": [self.person]}}, "example.test")
        self.assertEqual(len(result), 1)
        for changes in ({"position": "CEO"}, {"position": "Former Founder"},
                        {"verification": {"status": "accept_all"}}, {"verification": {"status": "unknown"}},
                        {"value": "person@wrong.test"}, {"type": "generic"}, {"first_name": None}):
            with self.subTest(changes=changes):
                self.assertEqual(founder_contacts({"data": {"emails": [{**self.person, **changes}]}}, "example.test"), [])

    def test_query_limit_and_domain_dedup(self):
        records, companies = [], []
        for i in range(22):
            records.append(record(company=f"Example {i}", id=str(i)))
            companies.append({"company": f"Example {i}", "domain": f"example{i}.test", "evidence_url": f"https://example{i}.test"})
        result = enrich(records, companies, "test", NOW, lambda *_: {"data": {"emails": []}})
        self.assertEqual(result["domain_queries"], 20)
        self.assertEqual(sum(r["status"] == "daily_query_limit" for r in result["coverage"]), 2)

    def test_provider_failure_has_no_email_and_is_explicit(self):
        def broken(*_):
            raise RuntimeError("unavailable")
        result = enrich([record()], self.companies, "test", NOW, broken)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["contacts"], [])
        self.assertEqual(result["coverage"][0]["status"], "provider_error")

    def test_old_records_not_reenriched_daily(self):
        result = enrich([record(first_seen_at=iso(NOW - timedelta(days=2)))], self.companies, "test", NOW,
                        lambda *_: self.fail("Old record should not incur another lookup"))
        self.assertEqual(result["domain_queries"], 0)

    def test_bad_reviewed_domain_fails(self):
        for domain in ("https://example.test", "example.test/?x=1", "-example.test"):
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                reviewed_domains([{**self.companies[0], "domain": domain}])

    def test_csv_formula_escaping(self):
        for value in ("=CMD()", "+1", "-1", "@test", "  =CMD()"):
            self.assertTrue(safe_csv(value).startswith("'"))


if __name__ == "__main__":
    unittest.main()
