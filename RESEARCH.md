# Fundable: what can be traced publicly

Research date: 2026-11-08. The user named "Fundable" without a URL. The closest
match to daily funded-company discovery plus founder contacts is
**tryfundable.ai**, not the similarly named Fundable crowdfunding platform.
This identification remains an assumption.

## Evidence and limits

The vendor homepage, data page, API index and OpenAPI specification were
retrieved directly from a GitHub Actions runner on 2026-11-08. Direct local
browser access is blocked in the coding environment. Earlier research used
search-indexed pages; the API paths below are now also verified against the
vendor's published specification. This is not an authenticated account,
private-backend traffic inspection or a vendor source-code audit.

| Question | Public evidence | What it does not prove |
|---|---|---|
| How are newly funded companies retrieved? | The [official tracking guide](https://www.tryfundable.ai/blog/track-newly-funded-startups-api) describes `POST /companies`, `latest_deal.date_start`, round filters, sorting by recent raise and pagination. | It does not reveal the vendor's complete ingestion pipeline or guarantee all raises are captured. |
| Where is evidence attached? | The [company search API](https://docs.tryfundable.ai/api-reference/companies/list) and [MCP guide](https://docs.tryfundable.ai/fundable-mcp) describe company/deal research and source material. | This is not a disclosed inventory of upstream licensing or every news source. |
| How are founder emails accessed? | The [person-email endpoint](https://docs.tryfundable.ai/api-reference/people/email), [API introduction](https://docs.tryfundable.ai/api-reference/introduction) and [credits guide](https://docs.tryfundable.ai/usage) describe credit-based unlocking of a person's verified email, using identifiers such as UUID or social-profile identifiers. | A LinkedIn/Crunchbase/Twitter identifier is a lookup key, **not proof** that the email was scraped from that platform. |
| Who supplies/verifies the emails? | No verifiable supplier disclosure was found in the accessible evidence. | Do not assert Fundable uses Hunter, Apollo, a specific verifier, or a particular scraping mechanism. |

## What was directly verified during the source upgrade

The official [OpenAPI specification](https://docs.tryfundable.ai/openapi.json)
declares the production API base `https://www.tryfundable.ai/api/v1`.
It exposes `POST /companies`, `POST /deals`, `GET /alerts`,
`GET /alerts/configurations`, and company funding history. The documented
models include `DealArticle`, `Financing`, `Alert` and `SimplifiedDeal`.
The alerts documentation describes saved matches with deals, reasoning and
source articles; it is not an anonymous public stream of every new deal.

The homepage markets real-time data, verified contacts and tailored alerts.
That is a vendor claim, not a measured zero-delay delivery guarantee.
No authenticated API query was made, and no Fundable credentials were supplied.
Using its licensed dataset, especially redistributing it on a public website,
requires an authorized account and appropriate export/publication rights.

## What was added without a paid data-provider key

The initial five-feed implementation was too narrow: three feeds responded
and only six qualifying signals were discovered. The upgrade adds Tech Funding
News and Silicon Canals, plus six Google News RSS searches spanning startups,
seed, Series A/B, growth, India and primary press releases from Business Wire,
PR Newswire and GlobeNewswire. The source audit confirmed Google News returned
100 articles from multiple named publishers, rather than a single site's
latest 10-20 entries. This is independent public-news discovery, **not access
to Fundable's private database or a claim that Fundable uses Google News**.

Checks now run hourly. Every indexed article retains its publisher attribution
and a clearly labeled Google News redirect link. Publication/indexing delays,
100-result search windows, English-language queries, extraction rules and
blocked publisher feeds still limit coverage. The app does not claim instant
or exhaustive funding detection.

## Likely architecture, not a claim about Fundable's private implementation

1. Detect funding announcements from licensed databases, permitted news feeds,
   press releases and/or filings.
2. Extract structured company, amount, stage, date and source.
3. Resolve company identities/domains and deduplicate reports of the same deal.
4. Resolve founders separately from company identity.
5. Purchase/use permitted business-contact enrichment; retain evidence,
   verification status and date. Some providers derive address candidates from
   company patterns, but a guess is not a verified contact.
6. Publish fresh signals and alerts on a schedule.

The news is often publicly accessible. Reliable identity resolution, coverage,
licensing and contact verification are the harder, commonly paid parts. SEC
Form D can add signals, but an offering/filing is not necessarily a completed
raise or a complete view of startup funding.

## Similar products

Vendor claims below are not independently validated deliverability guarantees.
Prices are deliberately omitted because plans change.

| Product | Relevant use | Tradeoff |
|---|---|---|
| [GrowthList](https://growthlist.co/funded-startups/) | Curated funded-company lists with decision-maker contacts. | Its advertised weekly updates are not the same as a daily complete feed. |
| [VCBacked](https://www.vcbacked.co/startup-database) | Funded-company and founder/contact database. | Confirm refresh cadence, export rights, coverage and current pricing. |
| [Origami](https://origami.chat/blog/recently-funded-startups-leads) | Live-web prospect research and enrichment for recently funded companies. | Requires checking individual results and paid usage/coverage limits. |
| [Hunter](https://hunter.io/api/domain-search) | Separate professional contact lookup after company/domain resolution. | Not a funding feed; requires an API key, licensing and identity checks. |

## What this implementation replicates

The no-key version replicates the **public discovery layer**: hourly checks,
source-linked candidate records, limited deduplication, searchable UI and CSV.
It is not a replacement for a comprehensive licensed startup database.

An optional Hunter adapter demonstrates the **separate private enrichment
layer**. No secrets were supplied and no live contact lookups were made.
Founder contact coverage stays incomplete until domains are reviewed and a
provider is configured; provider results may still return no verified founder.
