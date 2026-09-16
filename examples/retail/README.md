# ACME (retail)

The retail example runs both agents over one catalog with the built-in components only:
the storefront searches, compares, plans, fills the cart, stages checkout, and keeps
memory across restarts; the portal shows the morning digest, stages restocks, listing
fixes, and promotions, and applies them from the preview card. It is also the backend the
SDK consoles and the reference MCP servers load by default.

## Run

```bash
python scripts/run_demo.py retail               # API :8000 + storefront :3000
python scripts/run_demo.py retail --merchant     # API :8000 + portal :3100
python scripts/run_demo.py retail --all          # both web apps over one API
```

Or start the pieces yourself, after `npm ci` in `examples/`:

```bash
uvicorn retail.api.main:app --app-dir examples --reload --port 8000
(cd examples/retail/storefront-web && npm run dev)     # :3000
(cd examples/retail/merchant-web && npm run dev)       # :3100
```

The portal needs the API as well as the Next.js server. If the session cannot connect,
it shows the configured service address and a **Try again** button; session requests time
out after 10 seconds. Start the API at that address, then retry. When using a custom API
port, set `NEXT_PUBLIC_API_URL` before starting or building the web app, or let
`scripts/run_demo.py retail --merchant --api-port <port>` configure both processes.

Chat needs `ANTHROPIC_API_KEY` in the repo-root `.env` or the environment; browsing the
catalog and the portal's widgets do not. `MERCHANT_REQUIRE_HOST_APPROVAL=0` lets a chat
approval apply a change; by default the preview card's button applies it.

## 中文与 English

The storefront, merchant portal, and both `/showcase` pages support Simplified Chinese
and English. Use the `中文 / EN` control in the app chrome. The first visit follows the
browser's language; the choice persists in a cookie and local storage. The cookie is
shared across the localhost frontend ports. Switching languages keeps the current
session and conversation, refreshes catalog/order/cart reads, and affects new replies.

The UI dictionary is `examples/web-shared/locales/zh-CN.ts`; the retail fixture-content
dictionary is `data/locales/zh-CN.json`. English fixtures remain the source of truth.
Product descriptions, specs, reviews, policies, orders, merchant fixtures, and showcase
content have Chinese display translations. Brands, people, ids, statuses used by code,
and variant option values remain canonical; their display labels are localized separately.
Locale formatting does not convert USD prices into CNY. User-authored content and existing
conversation text remain in the language in which they were written.

`POST /api/chat` and `POST /api/merchant/chat` accept `locale: "en" | "zh-CN"` (default
`"en"`). The host supplies the corresponding response language in each turn's context,
including the merchant analysis delegate. No additional model calls translate fixture data.

Check fixture coverage and localization invariants with:

```bash
(cd examples && npm run check:i18n)
COMMERCE_DEMO_AUTH=sdk pytest       # isolate tests from local .env gateway settings
python scripts/smoke_retail_i18n.py # live Chinese shopping, language switching, merchant analysis
```

## Try

Storefront (`scripts/smoke_chat.py --vertical retail` runs the same three turns):

1. I'm taking my partner and our 6-year-old camping for the first time next month. We need a tent — nothing too heavy to deal with, ideally under $250.
2. Compare the top two options for me — mostly care about space and ease of setup.
3. The family one sounds right. Add it to my cart, and remind me what returns look like just in case.

Portal (`scripts/smoke_chat.py --vertical retail --merchant`; the third turn is refused
until the change is approved on its card, and the last two follow the approval):

1. What needs my attention this morning?
2. Restock the ocean wall decals with enough to cover the next month at the current pace, and fix that listing's description so it covers what's been missing. Show me both before anything goes live.
3. Looks right — approve the restock.
4. Kids-room decor feels like it's having a moment. Pull the numbers — is the under-the-sea line really outperforming the rest of the store this month?
5. Why did sales move over the last two weeks — which category or listings drove it, and by how much?

Single prompts, each in a fresh session:

| Surface | Prompt | A good answer |
|---|---|---|
| Storefront | Order me the same resistance band set I bought from you before. | Finds the set in order history, adds one to the cart, and says the price today differs from the price paid then. |
| Storefront | Can I still return the yoga mat I ordered from you a while back? It's unused. | Reads the order and the returns policy, counts 30 days from the delivery date, and says the window has closed. It does not open a return. |
| Storefront | I need a universal travel adapter that can charge a laptop. | Runs one search and shows one product card, the 65 W adapter, without a clarifying question. |
| Storefront | Two couples, first weekend of car camping, and no gear between us. Put together what we need and keep the whole list under $600. | Sizes the plan to four (one family tent, four sleeping bags, one stove, one cooler), totals it, says the sum is over $600, and names what to drop or share to get there. |
| Portal | Which category drove last week's change in sales, and by how much? | Reads the snapshot and the daily series: kids-room, the only category the data breaks out, gained more than the whole store, so the rest slipped; says the data has no full category split. |
| Portal | The ocean wall decals listing is missing wall coverage and material. Fill those in for me. | Reads the listing, finds neither value in the record, and asks for them instead of writing a material or a coverage figure into the page. |

## What is specific to this example

- `api/mock_retail.py`: `MockRetail`, the `StorefrontBackend` over the fixtures, plus
  the price and review summaries the product page shows.
- `api/mock_merchant.py`: `MockRetailMerchant`, the `MerchantBackend` over the same
  catalog; applied changes write back to it, and `execute_analysis_query` serves the
  analysis delegate from a read-only SQLite view of the same state.
- `api/agent_config.py`: the two configs. Analysis is on; `MERCHANT_ANALYSIS_CODE_EXECUTION=1`
  adds the hosted sandbox and `MERCHANT_ANALYSIS_MODEL` overrides the delegate's model.
- `api/main.py`: the storefront's file-backed memory store (`data/.memory-store.json`),
  the product-detail enrichment, and the add-to-cart button route.
- `api/merchant.py`: the overview's KPI trends and insight cards.
- `storefront-web/`, `merchant-web/`: this example's cards, views, and tokens, over `../web-shared/`.

## Data

`data/catalog.json`, `users.json`, `orders.json`, `policies.json`, and `memory-seed.json` feed
the storefront; `merchant_metrics.json`, `merchant_inventory.json`, `merchant_campaigns.json`,
and `merchant_messages.json` feed the portal. Four products come with options (a mattress by
size, a pillowcase set by size and color, a tinted moisturizer by shade, a weighted blanket by
weight): the catalog authors their variants compactly and `demo_common` derives the rest, as
[`docs/backends.md`](../../docs/backends.md) describes.
Product photos in `storefront-web/public/products/` are CC0 category images listed in the
`IMAGE-CREDITS.md` beside them; products without one render as tiles.

Sessions and identity are the shared host code in [`../demo_common/`](../demo_common/): a
session id stands for a demo profile or the one merchant.

## Reasoning inspector

The merchant portal includes a read-only Reasoning view in English and Simplified Chinese. Restock proposals require an explicit listing and coverage days, a full listing read, and a complete pending queue. The Approve button binds to the displayed change digest. [Configuration and evaluation](../../docs/ontology-pg/README.md) describe the optional PG and the always-on retail execution checks.
