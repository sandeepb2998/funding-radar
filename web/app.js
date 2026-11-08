export function recordDate(record, basis = "coverage") {
  if (basis === "coverage") return Date.parse(record.published_at);
  const info = record.announcement || {};
  const allowed = basis === "reviewed" ? ["reviewed"] : ["reviewed", "first_reported", "filed_first_sale", "reported_first_sale"];
  return allowed.includes(info.status) && /^\d{4}-\d{2}-\d{2}$/.test(info.date || "")
    ? Date.parse(`${info.date}T00:00:00Z`) : NaN;
}

export function filterRecords(records, filters, now = new Date()) {
  const search = filters.search.trim().toLocaleLowerCase();
  const day = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  const cutoff = filters.days ? day - (filters.days - 1) * 86400000 : -Infinity;
  return records.filter(record =>
    (!search || `${record.company} ${record.headline}`.toLocaleLowerCase().includes(search)) &&
    (!filters.stage || record.stage === filters.stage) &&
    (!filters.source || record.sources.some(source => source.name === filters.source)) &&
    (!filters.region || (record.location?.region || "Unknown") === filters.region) &&
    (!filters.country || (record.location?.country || "Unknown") === filters.country) &&
    recordDate(record, filters.dateBasis) >= cutoff &&
    recordDate(record, filters.dateBasis) < day + 86400000
  ).toSorted((a, b) => recordDate(b, filters.dateBasis) - recordDate(a, filters.dateBasis) || a.company.localeCompare(b.company));
}

export function csvCell(value) {
  let text = String(value ?? "");
  if (/^[\s]*[=+\-@\t\r]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

export function toCSV(records) {
  const fields = ["Company", "Amount", "Currency", "Stage", "Event date (UTC)", "Date status", "Date evidence", "Date note", "Article published (UTC)", "First seen (UTC)", "Region", "Country", "Location status", "Location evidence", "Headline", "Sources", "Quality", "Record type", "Filing date", "First sale date", "Amount basis", "Industry", "Accession"];
  return [fields, ...records.map(r => [r.company, r.amount, r.currency, r.stage, r.announcement?.date, r.announcement?.status || "unverified", r.announcement?.source_url, r.announcement?.note, r.kind === "sec_form_d" ? "" : r.published_at, r.first_seen_at, r.location?.region || "Unknown", r.location?.country || "Unknown", r.location?.status || "unknown", r.location?.source_url, r.headline, r.sources.map(s => s.url).join(" | "), r.quality, r.kind || "news", r.filing?.filed_on, r.filing?.first_sale_on, r.filing?.amount_basis || "headline_reported_round", r.filing?.industry, r.filing?.accession])]
    .map(row => row.map(csvCell).join(",")).join("\r\n");
}

export function safeURL(value) {
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch {
    return null;
  }
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function dateLabel(value) {
  return new Intl.DateTimeFormat("en", {month: "short", day: "numeric", year: "numeric", timeZone: "UTC"}).format(new Date(value));
}

function compactAmount(record) {
  const value = new Intl.NumberFormat("en", {notation: "compact", maximumFractionDigits: 2}).format(record.amount);
  const symbol = {USD: "$", EUR: "\u20ac", GBP: "\u00a3", INR: "\u20b9", CAD: "CA$", AUD: "A$", SGD: "S$", "$": "$"}[record.currency] || `${record.currency} `;
  return `${symbol}${value}`;
}

function renderCard(record) {
  const filing = record.kind === "sec_form_d";
  const card = node("article", "funding-card");
  card.append(node("div", "company-icon", record.company.slice(0, 2)));
  const body = node("div", "card-body");
  const title = node("div", "company-title");
  title.append(node("h3", "", record.company), node("span", "badge", record.stage));
  if (Date.parse(record.published_at) - recordDate(record, "timeline") > 7 * 86400000) {
    title.append(node("span", "badge", filing ? "FILING LAGS FIRST SALE" : "OLDER ROUND / LATER COVERAGE"));
  }
  body.append(title, node("p", "headline", record.headline));
  const location = record.location || {};
  body.append(node("p", "location", `Location: ${location.country || "Unknown"}${location.region ? ` \u00b7 ${location.region}` : ""}${location.status === "conflicting" ? " \u00b7 conflicting reports" : ""}`));
  const links = node("div", "source-links");
  const info = record.announcement || {};
  const evidence = [
    {name: "Date evidence", url: info.source_url},
    {name: "Location evidence", url: location.source_url}
  ].filter(source => source.url);
  for (const source of [...record.sources, ...evidence]) {
    const href = safeURL(source.url);
    if (!href) continue;
    const link = node("a", "", `${source.name} \u2197`);
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.setAttribute("aria-label", `Read funding report about ${record.company} at ${source.name}`);
    links.append(link);
  }
  body.append(links);
  const amount = node("div", "card-amount", compactAmount(record));
  amount.append(node("div", "card-currency", filing ? "USD \u00b7 cumulative amount sold" : record.currency === "$" ? "Dollar currency unspecified" : record.currency));
  const date = Number.isFinite(recordDate(record, "timeline"))
    ? `${filing ? "First sale" : info.status === "reviewed" ? "Announced" : "First reported"} ${dateLabel(`${info.date}T00:00:00Z`)}`
    : `${filing ? "First-sale date" : "Funding date"} ${info.status === "disputed" ? "disputed" : "unverified"}`;
  const dateNode = node("div", "card-date round-date", date);
  dateNode.title = info.note || "No announcement date has been established.";
  amount.append(dateNode);
  if (info.status === "first_reported") amount.append(node("div", "card-quality", "Earliest match found; not a verified announcement"));
  amount.append(node("div", "card-date", `${filing ? "Filed" : "Article"}: ${dateLabel(record.published_at)}`));
  amount.append(node("div", "card-quality", filing ? "Private offering; not necessarily a startup or VC round" : "Headline signal \u00b7 verify source"));
  card.append(body, amount);
  return card;
}

async function init() {
  const get = id => document.getElementById(id);
  const banner = get("status-banner");
  let data;
  try {
    const response = await fetch("./data.json", {cache: "no-store"});
    if (!response.ok) throw new Error(`Data request failed (HTTP ${response.status})`);
    data = await response.json();
    if (data.schema_version !== 1 || !Array.isArray(data.records) || !Array.isArray(data.sources)) {
      throw new Error("Unsupported funding data format");
    }
  } catch (error) {
    banner.className = "notice error";
    banner.textContent = `Unable to load funding data: ${error.message}. Reload after checking the deployment.`;
    get("results-count").textContent = "Feed unavailable";
    return;
  }
  const now = new Date();
  const today = now.toISOString().slice(0, 10);
  const records = data.records;
  get("total-count").textContent = records.length;
  const reviewed = records.filter(r => r.announcement?.status === "reviewed").length;
  const firstReported = records.filter(r => r.announcement?.status === "first_reported").length;
  const firstSale = records.filter(r => ["filed_first_sale", "reported_first_sale"].includes(r.announcement?.status)).length;
  get("dated-count").textContent = reviewed + firstReported + firstSale;
  const failedChecks = records.filter(r => r.announcement?.check_status === "error").length;
  get("date-coverage").textContent = `Coverage: ${reviewed} reviewed news dates, ${firstReported} earliest-report estimates, ${firstSale} reported first-sale dates, ${records.length - reviewed - firstReported - firstSale} undated or disputed. These are collected signals, not a count of all companies funded. Direct SEC access and the independent FormDs tracker have separate source-health entries.${failedChecks ? ` Historical lookup failed for ${failedChecks} signals; prior evidence is retained where available.` : ""}`;
  const healthy = data.sources.filter(s => s.status === "ok").length;
  get("source-count").textContent = `${healthy}/${data.sources.length}`;
  if (data.last_success_at) get("last-check").textContent = dateLabel(data.last_success_at);
  const stale = data.last_success_at && now.getTime() - Date.parse(data.last_success_at) > 3 * 3600000;
  if (data.status === "not_started") {
    banner.className = "notice warning";
    banner.textContent = "Awaiting the first collection. No sample companies or invented funding rounds are shown.";
  } else if (data.status === "error") {
    banner.className = "notice error";
    banner.textContent = "The latest collection failed for every source. Previous records are preserved; check the Actions run before relying on freshness.";
  } else if (data.status === "partial" || stale) {
    banner.className = "notice warning";
    banner.textContent = `${healthy}/${data.sources.length} feeds responded on the latest attempt.${stale ? " Data is over three hours old." : ""} Coverage is incomplete; see source health below.`;
  } else {
    banner.textContent = "Hourly collection is healthy. Publisher and index delays still apply. These are headline-extracted signals, not a comprehensive or independently verified funding database.";
  }
  if (data.last_attempt_at) get("freshness").textContent = `Last attempt: ${new Date(data.last_attempt_at).toLocaleTimeString("en", {timeZone: "UTC", hour: "2-digit", minute: "2-digit", hour12: false})} UTC`;
  for (const [id, values] of [
    ["stage", [...new Set(records.map(r => r.stage))].sort()],
    ["source", [...new Set(records.flatMap(r => r.sources.map(s => s.name)))].sort()],
    ["region", [...new Set(records.map(r => r.location?.region || "Unknown"))].sort()],
    ["country", [...new Set(records.map(r => r.location?.country || "Unknown"))].sort()]
  ]) {
    for (const value of values) {
      const option = node("option", "", value);
      option.value = value;
      get(id).append(option);
    }
  }
  const health = get("source-health");
  health.replaceChildren();
  if (!data.sources.length) health.textContent = "No collection has run yet.";
  for (const source of data.sources) {
    const row = node("div", "source-health-row");
    row.append(node("span", "", source.name), node("span", "", source.status !== "error" ? `${source.items_read} inputs / ${source.accepted} signals / ${source.invalid} invalid${source.pending ? ` / ${source.pending} pending` : ""}${source.status === "partial" ? " / partial" : ""}` : "Unavailable - see Actions logs; existing records are not fresh coverage"));
    health.append(row);
  }
  let visible = [];
  let limit = 50;
  function render() {
    const dateBasis = get("date-basis").value;
    visible = filterRecords(records, {search: get("search").value, stage: get("stage").value, source: get("source").value, days: Number(get("window").value), dateBasis, region: get("region").value, country: get("country").value}, now);
    get("sort-label").textContent = dateBasis === "coverage" ? "NEWEST REPORTS / FILINGS FIRST" : dateBasis === "reviewed" ? "REVIEWED NEWS ANNOUNCEMENTS FIRST" : "ANNOUNCEMENT / FIRST SALE / FIRST REPORT";
    get("feed").replaceChildren(...visible.slice(0, limit).map(r => renderCard(r)));
    get("results-count").textContent = `${visible.length} ${visible.length === 1 ? "signal" : "signals"} in this tracker${visible.length > limit ? ` \u00b7 showing ${limit}` : ""}`;
    get("empty").hidden = visible.length > 0;
    get("empty-title").textContent = "No matching signals";
    get("empty-text").textContent = dateBasis === "coverage" ? "Try a wider date range or clear your filters. This is incomplete source coverage, not proof that no companies raised funding. Unknown locations are not guessed." : "Try a wider range or Recent reports & filings to include undated signals. No matches does not mean no funding occurred.";
    if (!records.length) {
      get("empty-title").textContent = data.status === "not_started" ? "Your radar is ready. Awaiting data." : "No qualifying funding headlines collected";
      get("empty-text").textContent = data.status === "not_started" ? "Run the collection workflow after deploying this app to its own repository." : "This is not proof that no companies raised funding. Check source health and feed coverage.";
    }
    get("load-more").hidden = visible.length <= limit;
    get("export").disabled = visible.length === 0;
  }
  for (const id of ["search", "stage", "source", "window", "date-basis", "region", "country"]) {
    get(id).addEventListener(id === "search" ? "input" : "change", () => {limit = 50; render();});
  }
  get("load-more").addEventListener("click", () => {limit += 50; render();});
  get("export").addEventListener("click", () => {
    const url = URL.createObjectURL(new Blob(["\ufeff", toCSV(visible)], {type: "text/csv;charset=utf-8"}));
    const anchor = node("a");
    anchor.href = url;
    anchor.download = `funding-radar-${today}.csv`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  render();
}

if (typeof document !== "undefined") init();
