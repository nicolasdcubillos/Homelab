# StockWatcher

A generic product availability watcher. It scans retailers on a schedule, and
sends a **WhatsApp** alert the moment a watched product becomes available in the
size / variant / colour you actually want.

It was built to catch Nike Mind restocks in US men's 9.5–10 at retail, but
nothing in the engine is shoe-specific: a watch matches text and asks for
*variants*, so the same code watches storage capacities, ticket tiers, or
anything else a store lists per-variant.

```
┌──────────┐   ┌───────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│ watches  │──▶│ providers │──▶│ matching │──▶│  state   │──▶│ WhatsApp │
│  .yaml   │   │ shopify   │   │ size +   │   │ suppress │   │  alert   │
│          │   │ footlocker│   │ colour + │   │ repeats  │   │          │
│          │   │ nike      │   │ price    │   │          │   │          │
└──────────┘   └───────────┘   └──────────┘   └──────────┘   └──────────┘
```

You are only alerted on the transition **unavailable → available**, so an item
that stays in stock never messages you twice.

---

## Quick start

```bash
python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev,browser]"

# scan every configured store and print what it finds — no credentials needed
.venv/bin/stockwatcher --state-path /tmp/sw.db run --dry-run --no-discovery
```

Extras: `browser` pulls in Playwright (needed for the `nike` provider — also run
`.venv/bin/playwright install chromium`), `azure` pulls in the WhatsApp and Table
Storage SDKs, `dev` pulls in pytest and ruff. Plain `pip install -e .` is enough
for the Shopify and Foot Locker providers.

A full pass over the seeded stores takes ~36s. Real output:

```
🔔 Nike Mind 002 (Black/Chrome-Hyper Crimson) disponible en talla 10, 9.5
   por $145.00 USD en Rock City Kicks  (color fuera de preferencia)
https://www.rockcitykicks.com/products/nike-mind-002-black-chrome-hyper-crimson

🔔 Nike Mind 001 Mule - Men's disponible en talla 10.0 por $95.00 USD en Foot Locker
https://www.footlocker.com/product/nike-mind-001-mule-mens/Q4307200.html

run summary: {'duration_s': 35.87, 'stores_scanned': 33, 'stores_failed': 0,
              'products_seen': 56, 'variants_seen': 947, 'hits': 10,
              'new_hits': 10, 'hits_notified': 9, 'messages_sent': 6}
```

`hits_notified` is restocks after de-duplication; `messages_sent` is what
WhatsApp actually bills for, since sizes sharing a price collapse into one
message.

Run it a second time and `new_hits` drops to 0 — that is the state store doing
its job.

With `uv`: `uv sync` then `uv run stockwatcher run --dry-run`.

### Other commands

```bash
stockwatcher stores                        # list configured + discovered stores
stockwatcher probe kith.com "mind 002"     # debug one store's search + variants
stockwatcher discover                      # force a discovery pass now
stockwatcher run --watch "Nike Mind 002"   # limit to one watch
stockwatcher run --store kith.com          # limit to one store
stockwatcher -v run --dry-run              # per-request logging
```

Global flags (`--state-path`, `--watches`, `--concurrency`, …) must come
**before** the subcommand.

---

## Configuring a watch

`config/watches.yaml`:

```yaml
watches:
  - name: Nike Mind 002 Flyknit
    match: ["mind 002 flyknit", "ir2176"]   # ALL words of ANY group must appear
    exclude: ["wmns", "women"]              # hard veto
    variants: ["9.5", "10"]                 # the axis you care about
    gender: mens                            # women's sizes never match
    colors: ["white", "platinum", "sail"]   # SOFT preference — see below
    max_price: 160
    currency: USD
    countries: [US]
    notify: [whatsapp]
```

`defaults:` at the top of the file applies to every watch.

- **`match`** is a list of term *groups*. A product matches when every word of
  any one group appears in its title, vendor, colourway or URL. `"mind 002"`
  matches "Nike Mind 002 Flyknit"; it does not match "Nike Mind 001".
- **`colors` is a soft preference.** A colour miss still alerts, flagged
  `(color fuera de preferencia)`. Silently dropping a restock because the
  colour name was spelled differently is a much worse failure than one extra
  message.
- **`max_price` is evaluated per variant, after availability.** See the pricing
  trap below.
- A product with **no listed price passes** `max_price`. Noisy beats missed.

`config/stores.yaml` holds the store registry. Add one with:

```yaml
- host: newstore.com
  provider: shopify     # shopify | footlocker | nike | playwright
  country: US
```

Test it before trusting it: `stockwatcher probe newstore.com "mind 002"`.

---

## How each provider works

| Provider | Technique | Notes |
|---|---|---|
| `shopify` | `/search/suggest.json` + `/{handle}.js` | 32 seeded hosts. Exact per-variant stock, no auth. |
| `footlocker` | plain HTTPS + Chrome UA, regex over embedded JSON | Needs `Accept-Language: en-US`; 2.5s between requests. |
| `nike` | headless Chromium + the PDP's own GTIN endpoint | See below. |
| `playwright` | generic, config-driven selectors | For hibbett / jdsports / finishline / snipes / dicks / scheels, which all 403 plain HTTP. |

### Four traps found the hard way

These are load-bearing. Removing any of them silently breaks the watcher rather
than making it fail loudly.

**1. Never use the product-level Shopify `price`.** It is the *minimum* across
variants. On consignment stores every size is priced separately — Stadium Goods
listed a Yeezy at a headline $216 while the only available sizes were $314 and
$358; $216 was a sold-out size. Prices are always read from `variants[].price`
(integer cents), and `max_price` is checked per matched variant.
`tests/test_matching.py` guards this with that exact fixture.

**2. `Accept-Language: en-US` breaks Shopify pricing.** It activates Shopify
Markets geo-localization: from a Colombian IP, kith.com then returns `48200000`
(COP) instead of `14500` (USD), and every `max_price` check silently fails.
The base headers deliberately omit it; `country=US` is pinned instead. Foot
Locker *requires* the header and opts in explicitly.

**3. Shopify rate-limits per client IP, across all storefronts.** Bursting three dozen
hosts made *every* host return a "Verifying your connection" challenge —
sometimes with HTTP 200, so it looks like an empty result rather than an error.
A single **global** token bucket (`runtime.rate`, default 5 req/s) fixes it;
per-host throttling alone does nothing. When any host throttles, `penalize()`
slows the whole fleet.

**4. Nike's size grid never hydrates headless.** `#size-selector` stays an empty
`<div>` under headless Chromium, so scraping size buttons yields nothing. The
`__NEXT_DATA__` blob *is* server-rendered — but `status: "ACTIVE"` only means the
SKU exists in the catalogue, **not that it is in stock**, so trusting it would
alert on everything forever. The PDP itself calls
`api.nike.com/deliver/available_gtins/v3` with no auth; issuing that same fetch
from inside the page and joining on GTIN gives true per-size stock. Nike also
needs `NIKE_COMMERCE_COUNTRY` cookies or a non-US IP gets a country interstitial
and local currency.

### Sizing

Sizes normalize to `Size(value: float, gender)`, handling `9.5`, `09.0`,
`9.5W` (Stadium Goods' women's suffix), `W 9.5`, `M 9 / W 10.5` (dual label →
men's), `US 10`, `9 1/2`, and compound titles like
`"PINK SMOKE/METALLIC SILVER / 9.5"` (split on `/`, take the last segment).

Kids (`10.5Y`, GS/PS/TD) and EU/UK/CM scales return `None`, in which case
matching falls back to normalized string comparison — that is what keeps the
engine generic for non-shoe categories. `unisex` is a wildcard in both
directions.

---

## Store auto-discovery

Every N runs (default 3), StockWatcher tries to find retailers you have not
configured:

1. Web-search each watch's `match` terms for candidate domains.
2. Probe each for `/search/suggest.json`. Promote it only if it returns valid
   Shopify JSON **and** carries a product matching the watch — being on Shopify
   is not enough.
3. Persist it to the registry with `first_seen` / `last_ok` / `fail_count`.
4. Auto-retire after `retire_after_failures` consecutive failures.

The search backend is pluggable via `STOCKWATCHER_SEARCH_BACKEND`
(`brave` | `bing` | `serpapi`). **With no API key it degrades to a no-op** and
the availability pass is unaffected. Discovery runs after notifications and is
fully exception-guarded, so it can never block or slow a scan.

This is what generalizes the system: point it at a new category and it finds
that category's retailers itself.

---

## WhatsApp setup

Alerts go through **Azure Communication Services Advanced Messaging**, so Meta
bills through Azure (~$0.01/alert, drawn from your Azure credit).

Business-initiated WhatsApp messages require an **approved Meta template**.
**Approval can take up to 24h — everything works under `--dry-run` meanwhile**,
so this never blocks development.

1. Create a Communication Services resource and connect a WhatsApp Business
   Account (Azure portal → Communication Services → Advanced Messaging).
2. Submit the template in **WhatsApp Manager → Message templates**, category
   **Utility**. The exact body and parameters are in
   [`docs/whatsapp-template.md`](docs/whatsapp-template.md).
3. Copy `.env.example` to `.env` and fill in:

   ```bash
   ACS_CONNECTION_STRING=endpoint=https://...;accesskey=...
   ACS_CHANNEL_REGISTRATION_ID=<channel GUID>
   WHATSAPP_TO=+57...
   WHATSAPP_TEMPLATE_NAME=stockwatcher_restock
   WHATSAPP_TEMPLATE_LANG=es
   ```

4. Drop `--dry-run` to send for real.

Multiple hits are batched into as few messages as sensible
(`notify_options.max_hits_per_message`, `max_messages_per_run`) to cap cost and
noise. Sizes at the *same* price share one message; different prices never
merge, because a message must state the price of the size it is announcing.

---

## Deployment

Scale-to-zero **Container Apps Job** on a cron schedule — no VM, so you pay only
for the ~40s per run. Infrastructure is **Terraform** (azurerm provider).

```bash
az login
cp infra/terraform.tfvars.example infra/terraform.tfvars
$EDITOR infra/terraform.tfvars          # set name, location, whatsapp_to, ...
./scripts/deploy.sh
```

`scripts/deploy.sh` runs `terraform init`, applies once with
`-target=azurerm_container_registry.this` to bootstrap the registry, builds the
image with `az acr build` (server-side, so no local Docker and no
Apple-Silicon/amd64 mismatch), then applies the rest with the new `image_tag`.

`infra/` provisions:

- Container Apps Environment + **Job** (cron, default hourly — `cron_expression`)
- Azure Container Registry (Basic)
- Storage Account + Table (the production state store)
- Log Analytics workspace
- Communication Services (optional — see below)
- A user-assigned managed identity with `AcrPull` + Table Data Contributor, so
  only the ACS connection string is stored as a secret

Terraform **owns the resource group**, so do not pre-create it with
`az group create`. If it already exists, adopt it instead:

```bash
terraform -chdir=infra import azurerm_resource_group.this \
  /subscriptions/<sub-id>/resourceGroups/stockwatcher-rg
```

Change the schedule by editing `cron_expression` in `terraform.tfvars` and
re-running the script.

**Secrets never go in `terraform.tfvars`** (it is gitignored, but state is not
encrypted by default). Pass them as environment variables:

```bash
export TF_VAR_acs_connection_string='endpoint=https://...;accesskey=...'
export TF_VAR_search_api_key='...'
```

If you created the Communication Services resource by hand, set
`create_communication_service = false` and supply
`TF_VAR_acs_connection_string`; otherwise Terraform creates it and wires its
connection string in automatically.

The image includes Playwright's Chromium and its system dependencies, and sets
`STOCKWATCHER_ENABLE_BROWSER_STORES=1`, so the Nike provider is active in the
job. Locally those stores stay disabled until you run
`playwright install chromium` and set that variable yourself.

---

## Development

```bash
.venv/bin/python -m pytest -q      # 206 tests, no network
.venv/bin/ruff check src tests
.venv/bin/ruff format src tests
```

Tests cover the pure logic — size/variant normalization, colour matching,
per-variant price filtering, state transitions, provider parsing, notification
batching, discovery promotion, and store-failure isolation. **All HTTP is mocked
with `respx`; no test touches the network.**

Layout:

```
src/stockwatcher/
  models.py      Product, Variant, Watch, Hit, Alert, Store, RunSummary
  config.py      YAML loading + env overrides
  sizes.py       size/gender normalization
  matching.py    watch → product matching, per-variant price filtering
  http.py        async client, global rate limiter, retries
  runner.py      orchestration, concurrency, run summary
  providers/     shopify, footlocker, nike, playwright
  notifiers/     whatsapp, console
  state/         sqlite, azure_table
  discovery/     candidate harvesting + Shopify probing
```

To add a provider, implement `search(query) -> list[ProductRef]` and
`fetch(ref) -> Product` and register it in `providers/__init__.py`. To add a
notifier (email, Telegram), implement `send(alert) -> None`.

---

## Operational notes

- A single failing store never aborts a run; failures are logged, counted, and
  reported in the run summary.
- Run time is bimodal: ~40s normally, but a rate-limit cascade pushes it toward
  ~270s because the penalty is global by design. Both are well within an hourly
  schedule.
- `--state-backend none` disables suppression entirely — useful when testing
  alert formatting, since every hit then looks new.

<!-- CI/CD test: trivial change 2026-09-03T04:42:35Z -->
