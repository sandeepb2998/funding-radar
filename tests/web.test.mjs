import test from "node:test";
import assert from "node:assert/strict";
import {filterRecords, toCSV, csvCell, safeURL} from "../web/app.js";

const now = new Date("2026-11-08T14:00:00Z");
const records = [
  {company: "Example Labs", headline: "Example Labs raises $10M", amount: 10_000_000, currency: "$", stage: "Seed",
    published_at: "2026-11-08T10:00:00Z", first_seen_at: "2026-11-08T12:00:00Z",
    sources: [{name: "Example News", url: "https://news.example/1"}], quality: "Headline-extracted; verify source"},
  {company: "Example Systems", headline: "Example Systems raises EUR 5M", amount: 5_000_000, currency: "EUR", stage: "Series A",
    published_at: "2026-10-15T10:00:00Z", first_seen_at: "2026-10-15T12:00:00Z",
    sources: [{name: "Other News", url: "https://other.example/2"}], quality: "Headline-extracted; verify source"}
];
const filters = {search: "", stage: "", source: "", days: 0};

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
test("date cutoff is rolling 24 hours, not midnight", () => {
  const rows = [{...records[0], published_at: "2026-11-07T15:00:00Z"}, {...records[1], published_at: "2026-11-07T13:00:00Z"}];
  assert.deepEqual(filterRecords(rows, {...filters, days: 1}, now), [rows[0]]);
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
test("untrusted URLs cannot execute scripts or leak credentials", () => {
  for (const value of ["javascript:alert(1)", "data:text/html,test", "https://user:pass@example.test", "/relative"]) assert.equal(safeURL(value), null);
  assert.equal(safeURL("https://news.example/1"), "https://news.example/1");
});
