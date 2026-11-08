import test from "node:test";
import assert from "node:assert/strict";
import {filterRecords, recordDate, toCSV, csvCell, safeURL} from "../web/app.js";

const now = new Date("2026-11-08T14:00:00Z");
const records = [
  {company: "Example Labs", headline: "Example Labs raises $10M", amount: 10_000_000, currency: "$", stage: "Seed",
    published_at: "2026-11-08T10:00:00Z", first_seen_at: "2026-11-08T12:00:00Z",
    sources: [{name: "Example News", url: "https://news.example/1"}], quality: "Headline-extracted; verify source"},
  {company: "Example Systems", headline: "Example Systems raises EUR 5M", amount: 5_000_000, currency: "EUR", stage: "Series A",
    published_at: "2026-10-15T10:00:00Z", first_seen_at: "2026-10-15T12:00:00Z",
    sources: [{name: "Other News", url: "https://other.example/2"}], quality: "Headline-extracted; verify source"}
];
const filters = {search: "", stage: "", source: "", days: 0, dateBasis: "coverage", region: "", country: ""};

test("search is case-insensitive and trimmed", () => {
  assert.equal(filterRecords(records, {...filters, search: "  LABS "}, now).length, 1);
});
test("stage, source, and date filters compose", () => {
  assert.deepEqual(filterRecords(records, {...filters, stage: "Seed", source: "Example News", days: 1}, now), [records[0]]);
  assert.equal(filterRecords(records, {...filters, source: "Other News", days: 7}, now).length, 0);
});
test("all collected includes older announcements", () => {
  assert.equal(filterRecords(records, filters, now).length, 2);
});
test("date windows use UTC calendar days, including date-only announcements", () => {
  const rows = [{...records[0], published_at: "2026-11-07T15:00:00Z"}, {...records[1], published_at: "2026-11-07T13:00:00Z"}];
  assert.deepEqual(filterRecords(rows, {...filters, days: 1}, now), []);
  assert.equal(filterRecords(rows, {...filters, days: 2}, now).length, 2);
});
test("September funding is not November funding when an article is republished", () => {
  const row = {...records[0], announcement: {date: "2026-09-22", status: "reviewed"}};
  assert.equal(filterRecords([row], {...filters, dateBasis: "timeline", days: 30}, now).length, 0);
  assert.deepEqual(filterRecords([row], {...filters, dateBasis: "timeline"}, now), [row]);
  assert.deepEqual(filterRecords([row], {...filters, days: 1}, now), [row]);
});
test("undated and disputed announcements never fall back to article dates", () => {
  const rows = [...records, {...records[0], announcement: {date: "2026-11-08", status: "disputed"}}];
  assert.equal(filterRecords(rows, {...filters, dateBasis: "timeline"}, now).length, 0);
  assert.equal(filterRecords(rows, {...filters, dateBasis: "reviewed"}, now).length, 0);
  assert.ok(Number.isNaN(recordDate(records[0], "timeline")));
});
test("reviewed-only mode excludes automatic earliest-report estimates", () => {
  const rows = [
    {...records[0], announcement: {date: "2026-11-07", status: "first_reported"}},
    {...records[1], announcement: {date: "2026-11-08", status: "reviewed"}}
  ];
  assert.deepEqual(filterRecords(rows, {...filters, dateBasis: "timeline"}, now), [rows[1], rows[0]]);
  assert.deepEqual(filterRecords(rows, {...filters, dateBasis: "reviewed"}, now), [rows[1]]);
  assert.deepEqual(filterRecords(rows, {...filters, dateBasis: undefined}, now), rows);
});
test("regions and countries compose without guessing from currency", () => {
  const rows = [{...records[0], location: {region: "North America", country: "United States"}}, records[1]];
  assert.deepEqual(filterRecords(rows, {...filters, region: "North America", country: "United States"}, now), [rows[0]]);
  assert.equal(filterRecords(rows, {...filters, region: "Europe"}, now).length, 0);
  assert.deepEqual(filterRecords(rows, {...filters, region: "Unknown", country: "Unknown"}, now), [rows[1]]);
  assert.equal(filterRecords(rows, {...filters, region: "North America", country: "Unknown"}, now).length, 0);
});
test("future or malformed announcement dates are excluded", () => {
  for (const date of ["2026-11-09", "2026-99-01", "invalid"]) {
    const row = {...records[0], announcement: {date, status: "reviewed"}};
    assert.equal(filterRecords([row], {...filters, dateBasis: "timeline"}, now).length, 0);
  }
});
test("recent filing does not become a recent first sale", () => {
  const row = {...records[0], kind: "sec_form_d",
    published_at: "2026-11-06T00:00:00Z",
    announcement: {date: "2026-10-22", status: "reported_first_sale"},
    filing: {filed_on: "2026-11-06", first_sale_on: "2026-10-22", amount_basis: "cumulative_amount_sold"}};
  assert.equal(filterRecords([row], {...filters, days: 7}, now).length, 1);
  assert.equal(filterRecords([row], {...filters, days: 7, dateBasis: "timeline"}, now).length, 0);
  assert.equal(filterRecords([row], {...filters, dateBasis: "reviewed"}, now).length, 0);
  const csv = toCSV([row]);
  assert.ok(csv.includes("cumulative_amount_sold"));
  assert.ok(csv.includes("2026-11-06"));
  assert.ok(!csv.includes("2026-11-06T00:00:00Z"));
});
test("CSV escaping prevents spreadsheet formulas", () => {
  for (const value of ["=HYPERLINK(\"bad\")", "+cmd", "-cmd", "@cmd", "  =cmd"]) assert.ok(csvCell(value).startsWith("\"'"));
  assert.equal(csvCell('A "quoted", company'), '"A ""quoted"", company"');
});
test("CSV exports requested rows, with source evidence and original currency", () => {
  const csv = toCSV([records[0]]);
  assert.equal(csv.split("\r\n").length, 2);
  assert.ok(csv.includes("https://news.example/1"));
  assert.ok(csv.includes('"$"'));
  assert.ok(!csv.includes("Example Systems"));
  assert.ok(!csv.toLowerCase().includes("email"));
});
test("CSV distinguishes announcement and article dates and exports geography evidence", () => {
  const csv = toCSV([{...records[0], announcement: {date: "2026-09-22", status: "reviewed", source_url: "https://issuer.example/announcement"},
    location: {country: "United States", region: "North America", status: "reviewed", source_url: "https://issuer.example/company"}}]);
  for (const value of ["2026-09-22", "2026-11-08T10:00:00Z", "North America", "United States", "https://issuer.example/announcement", "https://issuer.example/company"]) assert.ok(csv.includes(value));
  assert.ok(toCSV([records[0]]).includes('"Unknown"'));
});
test("untrusted URLs cannot execute scripts or leak credentials", () => {
  for (const value of ["javascript:alert(1)", "data:text/html,test", "https://user:pass@example.test", "/relative"]) assert.equal(safeURL(value), null);
  assert.equal(safeURL("https://news.example/1"), "https://news.example/1");
});
