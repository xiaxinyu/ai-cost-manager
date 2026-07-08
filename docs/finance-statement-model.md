# Finance statement model (CapEx / OpEx)

This app uses **CapEx / OpEx as a management-report layering**, not strict GAAP classification. Azure OpenAI billing is almost entirely operating expense in accounting terms.

## Layers

| Layer | UI label | Meaning | Primary data |
|-------|----------|---------|--------------|
| **OpEx · Actual** | OpEx Total | Period invoice actuals | `transactions.cost_usd` |
| **OpEx · Meter** | OpEx · Meter | Token meter variable spend (inp/out) | `catalog_market.summary.total_meter_cost_usd` |
| **OpEx · Drivers** | Consumption | Token volume (no $ or implied $/1M) | Imported token CSVs |
| **CapEx · Tariff** | CapEx · Tariff | Reference list-price benchmark | `model_prices`, `catalog_cost_usd` |
| **CapEx · Platform** | CapEx · Platform | Non-token services residual | `billing_other_usd` |

**Actual (OpEx Total) remains the invoice truth.** CapEx layers are for attribution and variance only.

## Page narratives

- **Cost** — single-project OpEx statement: OpEx Summary → Run Rate → CapEx Reference → Allocation
- **Reports** — consolidated OpEx across projects with By project meter/platform columns
- **Tokens** — consumption drivers + unit economics (OpEx implied $/1M vs tariff)
- **Pricing** — CapEx tariff schedule and source registry
- **Import** — data lineage only (no CapEx/OpEx KPIs)

## Subtitles (avoid finance misread)

CapEx sections include subtitles: *reference / platform — not capital assets*.
