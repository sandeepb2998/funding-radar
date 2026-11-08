from urllib.error import HTTPError
import unittest

from test_collector import NOW
from collect import COUNTRIES
from sec import collect_sec, parse_filing, parse_index

FILING = {"cik": "1234567", "company": "Example Robotics Inc.", "form": "D",
          "filed_on": "2026-11-06", "accession": "0001234567-26-000001",
          "path": "edgar/data/1234567/0001234567-26-000001.txt"}
INDEX = ("CIK|Company Name|Form Type|Date Filed|Filename\n"
         "1234567|Example Robotics Inc.|D|2026-11-06|edgar/data/1234567/0001234567-26-000001.txt\n"
         "1234567|Example Robotics Inc.|D/A|2026-11-06|edgar/data/1234567/0001234567-26-000002.txt\n").encode()


def filing_xml(sold="12000000", target="20000000", sale="2026-11-02", state="CA",
               description="CALIFORNIA", industry="Other Technology", amend="false", form="D"):
    return f"""<edgarSubmission><submissionType>{form}</submissionType>
    <primaryIssuer><cik>0001234567</cik><entityName>Example Robotics Inc.</entityName>
    <issuerAddress><street1>Private address must not be published</street1><stateOrCountry>{state}</stateOrCountry>
    <stateOrCountryDescription>{description}</stateOrCountryDescription></issuerAddress></primaryIssuer>
    <offeringData><industryGroup><industryGroupType>{industry}</industryGroupType></industryGroup>
    <typeOfFiling><newOrAmendment><isAmendment>{amend}</isAmendment></newOrAmendment>
    <dateOfFirstSale><value>{sale}</value></dateOfFirstSale></typeOfFiling>
    <typesOfSecuritiesOffered><isEquityType>true</isEquityType></typesOfSecuritiesOffered>
    <offeringSalesAmounts><totalOfferingAmount>{target}</totalOfferingAmount><totalAmountSold>{sold}</totalAmountSold></offeringSalesAmounts>
    </offeringData></edgarSubmission>""".encode()


class SecParserTests(unittest.TestCase):
    def test_index_keeps_initial_filings_not_amendments(self):
        self.assertEqual(parse_index(INDEX), [FILING])

    def test_offering_target_is_not_amount_sold_and_dates_remain_separate(self):
        row = parse_filing(filing_xml(), FILING, NOW, COUNTRIES)
        self.assertEqual(row["amount"], 12_000_000)
        self.assertEqual(row["announcement"]["date"], "2026-11-02")
        self.assertEqual(row["filing"]["filed_on"], "2026-11-06")
        self.assertEqual(row["location"]["country"], "United States")
        self.assertNotIn("Private address", str(row))
        self.assertEqual(row["stage"], "Private offering")

    def test_old_first_sale_is_never_replaced_by_recent_filing_date(self):
        row = parse_filing(filing_xml(sale="2023-01-03"), FILING, NOW, COUNTRIES)
        self.assertEqual(row["announcement"]["date"], "2023-01-03")

    def test_funds_zero_sales_amendments_and_wrong_forms_are_excluded(self):
        for changes in ({"industry": "Pooled Investment Fund"}, {"sold": "0"},
                        {"amend": "true"}, {"form": "D/A"}):
            with self.subTest(changes=changes):
                self.assertIsNone(parse_filing(filing_xml(**changes), FILING, NOW, COUNTRIES))

    def test_foreign_issuer_is_not_us_just_because_it_files_with_sec(self):
        row = parse_filing(filing_xml(state="A1", description="CANADA"), FILING, NOW, COUNTRIES)
        self.assertEqual(row["location"]["country"], "Canada")
        unknown = parse_filing(filing_xml(state="ZZ", description="UNRECOGNIZED"), FILING, NOW, COUNTRIES)
        self.assertIsNone(unknown["location"]["country"])

    def test_bad_values_and_inconsistent_dates_fail_visibly(self):
        for changes in ({"sold": "NaN"}, {"sold": "-1"}, {"sold": "unknown"},
                        {"sale": "2026-11-07"}, {"sale": "2026-02-30"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_filing(filing_xml(**changes), FILING, NOW, COUNTRIES)

    def test_submission_wrapper_and_namespaces(self):
        xml = filing_xml().replace(b"<edgarSubmission>", b'<edgarSubmission xmlns="urn:sec:test">')
        row = parse_filing(b"<SEC-DOCUMENT>\n<XML>" + xml + b"</XML>", FILING, NOW, COUNTRIES)
        self.assertEqual(row["amount"], 12_000_000)

    def test_rejects_non_index_and_untrusted_paths(self):
        for body in (b"<html>Access denied</html>", INDEX.replace(b"edgar/data/1234567/", b"../../")):
            with self.assertRaises(ValueError):
                parse_index(body)

    def test_denial_stops_requests_and_preserves_known_data(self):
        original = parse_filing(filing_xml(), FILING, NOW, COUNTRIES)
        calls = []

        def denied(url):
            calls.append(url)
            raise HTTPError(url, 403, "Forbidden", {}, None)

        records, state, status = collect_sec([original], {}, NOW, COUNTRIES, fetch=denied)
        self.assertEqual(records, [original])
        self.assertEqual(status["status"], "error")
        self.assertEqual(len(calls), 1)

    def test_bounded_queue_is_persistent_and_completed_documents_are_not_refetched(self):
        def fetch(url):
            return INDEX if url.endswith(".idx") else filing_xml()
        records, state, status = collect_sec([], {}, NOW, COUNTRIES, fetch=fetch, limit=0)
        self.assertEqual(status["pending"], 1)
        self.assertEqual(records, [])
        records, state, status = collect_sec(records, state, NOW, COUNTRIES, fetch=fetch, limit=1)
        self.assertEqual(len(records), 1)
        self.assertEqual(status["pending"], 0)
        records2, _, _ = collect_sec(records, state, NOW, COUNTRIES,
                                      fetch=lambda _: self.fail("Completed inputs should be cached"))
        self.assertEqual(records2, records)
