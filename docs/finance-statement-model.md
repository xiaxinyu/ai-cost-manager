# Finance statement model (OpEx)

Azure OpenAI / cloud AI billing is **operating expense (OpEx)** in accounting terms. This app uses a single OpEx narrative with a separate **reference tariff** layer for benchmarks — not a second spend category.

## Layers

| Layer | UI label | Meaning | Primary data |
|-------|----------|---------|--------------|
| **OpEx · Total** | OpEx Total | Period invoice actuals | `transactions.cost_usd` |
| **OpEx · Meter** | OpEx · Meter | Token meter variable spend (inp/out) | `total_meter_cost_usd` |
| **OpEx · Platform** | OpEx · Platform | Non-token services on the invoice | `billing_other_usd` |
| **OpEx · Drivers** | Consumption | Token volume (no $ or implied $/1M) | Imported token CSVs |
| **Ref. Arch · Tariff** | Ref. Arch · Tariff | List-price benchmark (not spend) | `model_prices`, `catalog_cost_usd` |

**OpEx Total remains the invoice truth.** Tariff is reference-only for variance and unit economics.

## Page narratives

- **Cost** — OpEx Summary → Run Rate → Reference architecture → Allocation
- **Reports** — consolidated OpEx with meter/platform split per project
- **Tokens** — consumption drivers + unit economics vs reference tariff; subproject IN/OUT segment cards when nested `token/<subproject>/` data exists
- **Pricing** — Tariff schedule and source registry (configuration, not P&L)
- **Import** — data lineage: billing → OpEx, tokens → Volume, price sync → Ref. Arch. tariff schedule

## Visual semantics

- **Teal** — OpEx actual / meter
- **Amber** — OpEx platform (non-token)
- **Purple dashed** — Reference tariff (not invoice $)
