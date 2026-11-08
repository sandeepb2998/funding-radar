# Fundable: what can be traced publicly

Research date: 2026-11-08. The user named "Fundable" without a URL. The closest
match to daily funded-company discovery plus founder contacts is
**tryfundable.ai**, not the similarly named Fundable crowdfunding platform.
This identification remains an assumption.

## Evidence and limits

Direct access to the vendor site/docs was unavailable from this environment.
The following findings use search-indexed official pages, not an authenticated
account, observed backend traffic or a source-code audit. Verify current
endpoint contracts, plans, limits and pricing with the vendor before purchase.

| Question | Public evidence | What it does not prove |
|---|---|---|
| How are newly funded companies retrieved? | The [official tracking guide](https://www.tryfundable.ai/blog/track-newly-funded-startups-api) describes `POST /companies`, `latest_deal.date_start`, round filters, sorting by recent raise and pagination. | It does not reveal the vendor's complete ingestion pipeline or guarantee all raises are captured. |
| Where is evidence attached? | The [company search API](https://docs.tryfundable.ai/api-reference/companies/list) and [MCP guide](https://docs.tryfundable.ai/fundable-mcp) describe company/deal research and source material. | This is not a disclosed inventory of upstream licensing or every news source. |
| How are founder emails accessed? | The [person-email endpoint](https://docs.tryfundable.ai/api-reference/people/email), [API introduction](https://docs.tryfundable.ai/api-reference/introduction) and [credits guide](https://docs.tryfundable.ai/usage) describe credit-based unlocking of a person's verified email, using identifiers such as UUID or social-profile identifiers. | A LinkedIn/Crunchbase/Twitter identifier is a lookup key, **not proof** that the email was scraped from that platform. |
| Who supplies/verifies the emails? | No verifiable supplier disclosure was found in the accessible evidence. | Do not assert Fundable uses Hunter, Apollo, a specific verifier, or a particular scraping mechanism. |

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

The no-key version replicates the **public discovery layer**: daily checks,
source-linked candidate records, limited deduplication, searchable UI and CSV.
It is not a replacement for a comprehensive licensed startup database.

An optional Hunter adapter demonstrates the **separate private enrichment
layer**. No secrets were supplied and no live contact lookups were made.
Founder contact coverage stays incomplete until domains are reviewed and a
provider is configured; provider results may still return no verified founder.
