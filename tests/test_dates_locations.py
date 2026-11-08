from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import unittest

from test_collector import NOW, SOURCE, entry, record
from collect import apply_reviews, collect, extract, headline_location, iso, key, merge_records, reparse_records, resolve_history
from build import public_data


def review(**changes):
    return {
        "source_id": record()["id"], "company": "Example Labs", "amount": 12_000_000,
        "currency": "$", "stage": "Series A", "date": "2026-09-22", "status": "reviewed",
        "evidence_url": "https://issuer.example/announcement", "note": "Original dated funding announcement.",
        "country_code": "US", "location_evidence_url": "https://issuer.example/company",
        "location_note": "Company identifies its US headquarters.", **changes,
    }


class ReviewedDateTests(unittest.TestCase):
    def test_review_corrects_reposted_date_without_rewriting_article_or_discovery(self):
        row = record()
        original = deepcopy(row)
        apply_reviews([row], [review()], NOW)
        self.assertEqual(row["announcement"]["date"], "2026-09-22")
        self.assertEqual(row["announcement"]["status"], "reviewed")
        self.assertEqual(row["published_at"], original["published_at"])
        self.assertEqual(row["first_seen_at"], original["first_seen_at"])
        self.assertEqual(row["location"]["region"], "North America")

    def test_source_anchor_prevents_same_company_next_round_receiving_old_date(self):
        row = record(sources=[{"name": "Other", "url": "https://other.example/new-round"}])
        apply_reviews([row], [review()], NOW)
        self.assertEqual(row["announcement"]["status"], "unverified")

    def test_invalid_reviews_fail_explicitly(self):
        for changes in ({"date": None}, {"date": "2026-02-30"}, {"date": "2026-11-09"},
                        {"date": "2026-9-22"}, {"status": "guessed"}, {"amount": 13_000_000},
                        {"evidence_url": "javascript:alert(1)"}, {"country_code": "ZZ"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                apply_reviews([record()], [review(**changes)], NOW)

    def test_disputed_date_remains_unknown(self):
        row = record()
        apply_reviews([row], [review(status="disputed", date=None)], NOW)
        self.assertIsNone(row["announcement"]["date"])
        self.assertEqual(row["announcement"]["status"], "disputed")

    def test_review_reapplied_after_hourly_archive_revalidation_and_merging(self):
        row = record()
        apply_reviews([row], [review()], NOW)
        state = collect({"records": [row]}, [SOURCE], NOW, lambda _: ([entry()], None))
        apply_reviews(state["records"], [review()], NOW)
        self.assertEqual(state["records"][0]["announcement"]["date"], "2026-09-22")
        self.assertEqual(state["records"][0]["location"]["country"], "United States")

    def test_removed_review_is_not_permanently_cached_as_verified(self):
        row = record()
        apply_reviews([row], [review()], NOW)
        repaired = reparse_records([row], NOW)[0]
        self.assertEqual(repaired["announcement"]["status"], "unverified")
        self.assertEqual(repaired["location"]["status"], "unknown")

    def test_production_go_ai_review_is_bound_and_september_not_november(self):
        root = Path(__file__).resolve().parents[1]
        rows = json.loads((root / "data/funding.json").read_text())["records"]
        go = next((r for r in rows if r["company"] == "Go.AI"), None)
        if go is None:
            self.skipTest("Go.AI has expired from the retained archive")
        reviews = [r for r in json.loads((root / "config/reviews.json").read_text()) if r["company"] == "Go.AI"]
        apply_reviews([go], reviews, NOW)
        self.assertEqual(go["announcement"]["date"], "2026-09-22")
        self.assertEqual(go["location"]["country"], "United States")


class HistoricalDateTests(unittest.TestCase):
    def historical(self, **changes):
        return entry(published="Tue, 22 Sep 2026 10:00:00 GMT", url="https://news.example/original", **changes)

    def test_older_report_is_labelled_first_reported_not_verified(self):
        row = record()
        resolve_history([row], NOW, lambda _: ([entry(), self.historical()], None))
        self.assertEqual(row["announcement"]["date"], "2026-09-22")
        self.assertEqual(row["announcement"]["status"], "first_reported")
        self.assertEqual(row["announcement"]["source_url"], "https://news.example/original")

    def test_search_is_not_limited_to_archive_retention(self):
        row = record()
        resolve_history([row], NOW, lambda _: ([entry(published="2023-09-22T10:00:00Z")], None))
        self.assertEqual(row["announcement"]["date"], "2023-09-22")

    def test_round_identity_and_stage_must_match(self):
        rows = [entry(title=t) for t in ("Example Labs Raises $12M in Series B", "Example Systems Raises $12M in Series A",
                                         "Example Labs Raises EUR 12M in Series A", "Example Labs Raises $15M in Series A")]
        row = record()
        resolve_history([row], NOW, lambda _: (rows, None))
        self.assertIsNone(row["announcement"]["date"])
        self.assertEqual(row["announcement"]["check_status"], "no_match")

    def test_bounded_checks_resume_with_unchecked_records(self):
        rows = [record(id=str(i), company=f"Company {i}") for i in range(3)]
        calls = []
        resolve_history(rows, NOW, lambda source: (calls.append(source) or [], "unavailable"), limit=2)
        self.assertEqual(len(calls), 2)
        resolve_history(rows, NOW, lambda source: (calls.append(source) or [], None), limit=2)
        self.assertEqual(len(calls), 3)
        self.assertIn("Company 2", calls[-1]["query"])

    def test_reviewed_dates_are_not_overridden_by_automated_search(self):
        row = record()
        apply_reviews([row], [review()], NOW)
        resolve_history([row], NOW, lambda _: self.fail("Reviewed round should not be searched"))
        self.assertEqual(row["announcement"]["status"], "reviewed")

    def test_failure_retains_prior_evidence_and_exposes_failure(self):
        row = record()
        resolve_history([row], NOW, lambda _: ([self.historical()], None))
        resolve_history([row], NOW + timedelta(days=8), lambda _: ([], "HTTP 503"))
        self.assertEqual(row["announcement"]["date"], "2026-09-22")
        self.assertEqual(row["announcement"]["check_status"], "error")

    def test_first_report_survives_reprocessing_and_article_refresh(self):
        row = record()
        resolve_history([row], NOW, lambda _: ([self.historical()], None))
        merged = merge_records(reparse_records([row], NOW), [record()], NOW)[0]
        self.assertEqual(merged["announcement"]["date"], "2026-09-22")
        self.assertEqual(merged["announcement"]["checked_at"], iso(NOW))

    def test_company_trademark_does_not_hide_historical_match(self):
        self.assertEqual(key("Go.AI\u2122"), key("Go.AI"))
        self.assertNotEqual(key("Zango.AI"), key("Go.AI"))

    def test_corrected_amount_invalidates_old_historical_match(self):
        row = record()
        resolve_history([row], NOW, lambda _: ([self.historical()], None))
        row["amount"] = 12
        self.assertEqual(reparse_records([row], NOW)[0]["announcement"]["status"], "unverified")


class LocationTests(unittest.TestCase):
    def test_explicit_company_locations(self):
        for title, country in (
            ("Germany's Example raises EUR 12M", "Germany"),
            ("Israeli cybersecurity startup Example raises $12M", "Israel"),
            ("Helsinki-based Example raises EUR 12M", "Finland"),
            ("Indian startup Example raises $12M", "India"),
        ):
            with self.subTest(title=title):
                location = headline_location(title, "https://news.example/raise")
                self.assertEqual(location["country"], country)
                self.assertEqual(location["status"], "reported")

    def test_currency_publisher_and_expansion_market_do_not_determine_location(self):
        for title in ("Example Raises EUR 12M in Series A", "Example Raises $12M to Expand in India",
                      "Example Raises $12M from Dubai-Based Investors"):
            row = extract(entry(title), {"name": "European News", "country": "IN"}, NOW)
            self.assertIsNone(row["location"]["country"])

    def test_reported_location_survives_generic_duplicate(self):
        located = extract(entry("German startup Example Labs Raises $12M in Series A"), SOURCE, NOW)
        merged = merge_records([located], [record()], NOW)[0]
        self.assertEqual(merged["location"]["country"], "Germany")
        self.assertEqual(reparse_records([merged], NOW)[0]["location"]["country"], "Germany")

    def test_conflicting_locations_remain_unknown(self):
        left = extract(entry("German startup Example Labs Raises $12M in Series A"), SOURCE, NOW)
        right = extract(entry("Indian startup Example Labs Raises $12M in Series A", url="https://other.example/report"), SOURCE, NOW)
        merged = merge_records([left], [right], NOW)[0]
        self.assertIsNone(merged["location"]["country"])
        self.assertEqual(merged["location"]["status"], "conflicting")
        self.assertEqual(reparse_records([merged], NOW)[0]["location"]["status"], "conflicting")

    def test_nested_metadata_keeps_public_privacy_boundary(self):
        state = collect({}, [SOURCE], NOW, lambda _: ([entry()], None))
        row = state["records"][0]
        apply_reviews([row], [review()], NOW)
        row["announcement"]["email"] = "private@example.test"
        row["location"]["contacts"] = ["private@example.test"]
        output = public_data(state)
        self.assertNotIn("private@example.test", json.dumps(output))
        self.assertEqual(output["records"][0]["announcement"]["date"], "2026-09-22")
        self.assertEqual(output["records"][0]["location"]["country"], "United States")
