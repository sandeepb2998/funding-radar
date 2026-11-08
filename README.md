# Funding Radar

A startup funding-news dashboard refreshed hourly: searchable signals, source
links, region/country/stage/source/date filters, CSV export and transparent source health.
Python standard library + vanilla HTML/CSS/JavaScript; no browser API keys,
database or paid AI model required.

## Live service

- Website: https://sandeepb2998.github.io/funding-radar/
- Scheduled collection: **every hour at :17 UTC**, including weekends.
- Manual refresh: Actions > Funding Radar - hourly collection and Pages > Run workflow.
- Initial activation is complete only after the collection and deployment jobs
  have succeeded; check the Actions run, not just the presence of this README.

GitHub schedules may be delayed. Public-repository schedules can be disabled
after 60 days without repository activity. Enable failed-workflow notifications.

## Data and coverage

The collector combines seven publisher feeds (FinSMEs, TechCrunch Startups,
EU-Startups, Crunchbase News, Tech.eu, Tech Funding News and Silicon Canals)
with six Google News discovery searches: startup funding, seed rounds,
Series A/B, growth rounds, primary press releases and India funding.
The press-release search covers Business Wire, PR Newswire and GlobeNewswire
through Google's index, not by bypassing their websites.

This expands discovery across publishers instead of being limited to the last
10-20 stories on a few homepages. Each news search looks back seven days and
returns at most 100 results; it is not an exhaustive news API. Publishers may
block individual feeds, and errors remain visible. Publication, indexing and
GitHub scheduling delays mean **hourly checks are not instant coverage**.
This is a research starting point, not a verified worldwide company database.

- Company label, amount, original currency and stage are extracted
  conservatively from headlines. Article bodies are not republished.
- Only explicit completed-raise language and a numeric amount qualify. Common
  investment-fund announcements, plans, contracts, grants, uncertain amounts
  and non-funding stories are excluded. Some real raises will be missed.
- `Mn`/`mln` are parsed as millions; INR crore/lakh amounts retain INR rather
  than being mislabeled as dollars. Bare `$` remains **dollar currency
  unspecified**, not automatically USD.
  Different currencies are never added together.
- Article publication, first discovery, reviewed announcement date and earliest
  matching report are distinct. A later repost is not a new funding round.
- News-index records retain the named publisher and are explicitly labeled
  "via Google News". Those URLs open Google's article redirects; they are not
  misrepresented as direct publisher URLs. Government-domain results, grants,
  government funding and unsupported non-funding announcements are excluded.
- Identical source URLs are deduplicated. Cross-source reports merge only when
  normalized company, amount and currency match within seven days, and stages
  match or one is undisclosed. Explicit conflicting stages remain separate.
- Dividends, combined multi-round totals and headlines that do not name a
  company are rejected. Archived headlines are revalidated when a collection
  succeeds, so parser corrections repair prior amounts and remove old false
  positives without resetting discovery dates.
- The archive retains previously discovered records for 180 days. RSS feeds
  normally expose a much shorter window; missing periods cannot always be
  backfilled.
- Websites, founder identities, geography, investors and emails are not guessed.
- Partial feed failures publish a warning. If all feeds fail, old records are
  preserved, the site shows an error and the workflow fails visibly.

## Dates and geographic filters

The default **Funding timeline** filters and sorts by a reviewed announcement
date or an explicitly labeled **First reported** date, never by an undated
record's current article timestamp. **Reviewed dates only** excludes automatic
historical matches; **Article coverage** includes unverified/disputed dates and
uses article publication instead. Windows use UTC calendar days. All modes
retain the original article and discovery timestamps in CSV exports.

Each successful hourly collection checks up to 12 unreviewed signals against
historical Google News searches, without the discovery feed's seven-day limit.
Exact normalized company, amount, currency and stage must match. These
searches may find reports older than the 180-day archive. A first-report date
is the earliest matching indexed result **found**, not proof of the original
announcement or closing date. Search caps, missing sources, company aliases
and repeated similar rounds limit this heuristic. Undated signals are excluded
from the default timeline, but remain accessible in Article coverage.
Unchecked signals are prioritized, successful checks are cached for seven
days, and failures are explicit and retryable after one hour. First-run
historical backfill can therefore take several hourly runs.

`config/reviews.json` contains manually checked announcement/location facts,
bound to a source URL's stable SHA-256 ID plus exact round fields. Each fact
requires evidence. Reviews override historical estimates and are reapplied
after archive revalidation; malformed or contradictory reviews fail visibly.
This is not automatic verification of the funding transaction. Go.AI's $85M
Series A is dated **September 22, 2026**, not its November 7 syndicated article.

Region and country refer to **company location**, not investor location,
publisher origin, currency or search locale. Only explicit company-location
headline prefixes or reviewed source evidence populate them. Reported
locations are not necessarily verified headquarters. Geography is partial;
unrecognized, absent or conflicting locations remain **Unknown**, which is
itself filterable. Current region buckets are North America, Latin America &
Caribbean, Europe, Middle East & Africa, and Asia-Pacific. Date and location
evidence links are displayed and exported; contacts remain excluded.

## Founder emails

The public site **does not collect, display or publish founder email addresses**.
No contact provider is configured in this public repository.

An optional Hunter adapter is included for a separate **private** deployment.
The workflow explicitly disables it for public repositories. It requires a
licensed `HUNTER_API_KEY` Actions secret and reviewed company/domain mappings
in `config/companies.json`, for example:

```json
[
  {
    "company": "Example Labs",
    "domain": "example.com",
    "evidence_url": "https://example.com/team"
  }
]
```

In a private deployment, the adapter still runs on the original daily
13:17 UTC schedule (and manual/code-triggered runs), not on the other 23
hourly scheduled runs. Hourly news checks do not multiply contact-provider
charges. The adapter looks up at most 20 unique approved
domains for companies first seen in the last 24 hours. Unknown domains are
reported as needing review. Only named current founders with an exact-domain
professional email and provider verification status `valid` are included.
CEO-only titles, former founders, generic inboxes, catch-all and unknown
verification results are excluded.

Results and per-company coverage reasons are stored in the private Actions
artifact `private-founder-contacts`, never in the website or Git history.
Artifacts expire after seven days and are visible to repository readers.
There is no automatic outreach. Provider validation does not establish
consent, current employment or guaranteed delivery. Follow applicable privacy
and anti-spam laws and provider licensing.

No live provider lookup has been validated without a user-supplied key.
Search is limited to the first 100 provider results per domain. Manual reruns
may repeat billable queries. Later domain review needs a deliberate historical
backfill; old companies are not automatically re-queried.

See [RESEARCH.md](RESEARCH.md) for what can and cannot be established about
Fundable's data pipeline, contact lookup APIs and competing products.

## Development

Requires Python 3.12+ and Node 22+ (Node is used only for tests).

```bash
python -m unittest discover -s tests -v
node --test tests/web.test.mjs
python scripts/collect.py
python scripts/build.py
python -m http.server 8000 --directory site
```

Open http://localhost:8000. `collect.py` writes source-level status and exits
nonzero if every source fails. Tests use synthetic fixtures, never fabricated
production leads.

## Deployment

Pages must be configured under Settings > Pages > Source > **GitHub Actions**.
Actions must be enabled and the default branch must be `main`. The collection
workflow needs `contents: write` to persist its archive directly to `main`;
branch protection requiring pull requests needs a different persistence setup.
The deploy job uses `pages: write` and `id-token: write`.

The builder copies only five allowlisted public files and removes fields
outside the public schema:
`site/{index.html,styles.css,app.js,data.json,.nojekyll}`.
Private contact output is gitignored under `private/`. The public build never
copies the whole repository.

To package the standalone app for another repository:

```bash
python scripts/package_app.py ../funding-radar.zip
```

Honor feed terms and rate limits. Do not bypass blocked publishers or paywalls.
This project is independently built and not affiliated with Fundable.
