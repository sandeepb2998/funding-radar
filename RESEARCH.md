# Fundable: what can be traced publicly

Research date: 2026-11-08. This investigation concerns the user-supplied
**https://www.tryfundable.ai/home**, not the similarly named Fundable
crowdfunding platform.

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

The [homepage](https://www.tryfundable.ai/home) and
[data page](https://www.tryfundable.ai/data) explicitly say the automated pipeline processes
**10,000+ news sources** and refreshes **multiple times per day**, with
source-linked data. That explains the breadth gap versus five publisher feeds.
The homepage also markets real-time data, verified contacts and tailored alerts.
Those are vendor claims, not a measured zero-delay delivery guarantee or a
disclosure of the full source inventory or private implementation.
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

## Date correction: Go.AI and republished funding

The original dashboard conflated article publication with funding recency.
Its Go.AI record came from an openPR result published November 7, 2026.
Historical search and direct publisher retrieval established earlier evidence:

- [Finovate's funding report](https://finovate.com/go-ai-secures-85-million-in-series-a-funding/)
  was published September 22, 2026 (page metadata:
  `2026-09-22T20:54:54+00:00`). It reports the $85 million Series A,
  identifies headquarters in Chicago, Illinois, and links the
  [original Business Wire announcement](https://www.businesswire.com/news/home/20260922352774/en/Go.AI-Raises-%2485-Million-Series-A-to-Accelerate-On-Prem-AI-Infrastructure-for-Regulated-Industries).
- [FinTech Global's report](https://fintech.global/2026/09/22/go-ai-raises-85m-series-a-for-on-prem-ai-push/)
  independently has September 22 publication metadata and identifies the
  Chicago-based company. These pages were retrieved on November 8.
- November 7 is therefore later coverage, **not a new November Series A**.
  September 22 is the reviewed announcement date; the legal closing date
  has not been independently established.

For comparison, Harbinger's [issuer press release](https://www.prnewswire.com/news-releases/harbinger-raises-240-million-series-d-funding-round-led-by-tiger-global-302930560.html)
was retrieved directly and explicitly announces its $240 million Series D
on November 5, 2026, consistent with the page's timestamp.

The app now separates reviewed announcements, earliest matching historical
reports, article publication and discovery. Bounded hourly historical checks
can surface older rounds, but are labeled estimates, not verified dates.
Region/country filters use explicit reported company locations or reviewed
evidence; they never derive company geography from the news source or currency.
This correction demonstrates why broader news coverage alone does not recreate
a curated deal database.

## SEC-derived funding disclosures

On November 8, 2026, the official SEC November 6 daily master index returned
HTTP 403 from the GitHub runner. This does not establish zero filings; it
establishes an access gap. The collector does not retry around this block.
The independently published [FormDs newest-filings page](https://www.formds.com/filings/newest)
was accessible, including pagination and current November 6 disclosures.
Its public crawl policy permits the list and issuer pages for this collector;
the policy is checked again each run.

A directly retrieved example is [Luminoah](https://www.formds.com/issuers/luminoah-inc):
the tracker reports an initial filing on November 6, 2026, with exactly
$25,413,863 cumulatively sold, an October 22 first sale, and Charlottesville,
Virginia as issuer location. The filing links to SEC accession
`0001982235-26-000003`. It is **not** evidence that this entire amount was
newly raised during November 2-8. Another retrieved issuer, Instant Hydration,
had a new November 6 filing with zero sold; it is correctly excluded.

This source upgrade adds private-offering disclosures, not a verified list of
venture-backed startups. Pooled funds, amendments and zero-sale offerings are
filtered. Country uses issuer-location evidence, never the fact that a company
files with the US regulator. The original one-result US view was a tiny manual
review subset, not a market count; source activity is now the default, with
explicit date semantics and coverage limitations.

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
