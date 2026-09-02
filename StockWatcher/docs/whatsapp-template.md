# WhatsApp alerts: Meta template + Azure setup

StockWatcher sends alerts through **Azure Communication Services (ACS) Advanced
Messaging**, not Twilio. Meta bills WhatsApp conversations through Azure, so
every alert draws down the existing Azure credit (~**$0.01** per utility
message) instead of a separate vendor bill.

> **Approval takes up to 24h.** Nothing here blocks development: run with
> `--dry-run` and alerts print to the console in the exact format they will be
> sent. Wire the credentials in whenever approval lands.

---

## 1. The template to submit

A business-initiated message (one the user did not ask for in the last 24h)
**must** use a template Meta has approved. Restock alerts are transactional, so
submit it under the **Utility** category — utility templates are cheaper than
marketing ones and are far more likely to be approved on the first try.

In **WhatsApp Manager → Account tools → Message templates → Create template**:

| Field | Value |
| --- | --- |
| Name | `stockwatcher_restock` |
| Category | **Utility** |
| Language | Spanish (`es`) |

**Body** — copy exactly:

```
🔔 {{product}} disponible en talla {{variant}} por {{price}} en {{store}}
```

**Buttons** → *Visit website* → **Dynamic**:

| Field | Value |
| --- | --- |
| Button text | `Ver producto` |
| URL type | Dynamic |
| Website URL | `https://{{1}}` |

Meta requires a sample for every placeholder. Use these — they are real values
produced by a live run, which helps reviewers understand the use case:

| Placeholder | Sample |
| --- | --- |
| `product` | `Nike Mind 002 (Black/Chrome-Hyper Crimson)` |
| `variant` | `9.5, 10` |
| `price` | `$145.00 USD` |
| `store` | `Rock City Kicks` |
| URL suffix (`{{1}}`) | `www.rockcitykicks.com/products/nike-mind-002-black-chrome-hyper-crimson` |

### Why the URL is a suffix

Meta dynamic URL buttons append the parameter to a **fixed base URL**. The base
is registered as `https://` and StockWatcher passes everything after the scheme
(see `_url_suffix` in `notifiers/whatsapp.py`). This is why the sample above has
no `https://` prefix — getting this wrong is the most common cause of a
button that 404s after approval.

### Parameter order matters

ACS binds body parameters positionally. The order in
`notifiers/whatsapp.py::TEMPLATE_PARAMS` is:

```python
TEMPLATE_PARAMS = ("product", "variant", "price", "store")
```

If you reorder the placeholders in the template body, reorder that tuple to
match or alerts will read "disponible en talla $145.00".

### An English variant (optional)

If you would rather receive English alerts, submit a second template with
language `en_US` and body:

```
🔔 {{product}} is available in size {{variant}} for {{price}} at {{store}}
```

then set `WHATSAPP_TEMPLATE_LANG=en_US`.

---

## 2. Azure side

The Terraform in `infra/` provisions the Communication Services resource (set
`create_communication_service = false` if you made it by hand). The WhatsApp
channel itself must be connected by hand — it requires an interactive Meta OAuth
consent that has no ARM equivalent.

1. **Azure Portal → your Communication Services resource → Advanced Messaging →
   Channels → Connect a channel → WhatsApp.**
2. Sign in with the Meta Business account that owns the WhatsApp Business
   Account (WABA) and grant consent.
3. Register the sending phone number. It must **not** be attached to the regular
   WhatsApp or WhatsApp Business app.
4. Copy the resulting **Channel Registration ID** (a GUID) into
   `ACS_CHANNEL_REGISTRATION_ID`.
5. Get the connection string from **Keys** → `ACS_CONNECTION_STRING`.

---

## 3. Configuration

| Variable | Meaning |
| --- | --- |
| `ACS_CONNECTION_STRING` | ACS resource connection string (secret) |
| `ACS_CHANNEL_REGISTRATION_ID` | WhatsApp channel GUID from step 4 |
| `WHATSAPP_TO` | Recipient(s) in E.164, comma-separated — e.g. `+573001234567` |
| `WHATSAPP_TEMPLATE_NAME` | `stockwatcher_restock` |
| `WHATSAPP_TEMPLATE_LANG` | `es` |
| `WHATSAPP_MODE` | `template` (default) or `text` |

`WHATSAPP_MODE=text` sends a free-form message instead of a template. That
**only** works inside the 24-hour window opened by an inbound message from the
recipient, so it is useful for a quick end-to-end test (message the business
number first, then run) but not for scheduled alerts.

---

## 4. Testing without waiting for approval

```bash
# Prints exactly what would be sent, sends nothing:
stockwatcher run --dry-run

# Once the channel exists and you have messaged the business number,
# verify the ACS plumbing with a free-form message:
WHATSAPP_MODE=text stockwatcher run

# After approval:
stockwatcher run
```

---

## 5. Keeping cost and noise down

Two mechanisms, both already implemented:

* **State transitions.** An alert fires only on `unavailable → available`. A
  product that stays in stock for a week costs one message, not 168.
* **Batching.** Hits are grouped by product and packed into as few messages as
  possible (`max_hits_per_message`, default 6), with a hard ceiling of
  `max_messages_per_run` (default 5) so a site-wide restock cannot produce a
  hundred messages. Sizes of the same product are merged into one line
  (`disponible en talla 9.5, 10`).

At hourly cadence with a handful of watches, expect a few cents per month.
