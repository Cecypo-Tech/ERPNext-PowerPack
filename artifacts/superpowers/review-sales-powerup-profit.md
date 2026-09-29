# Review: Sales Powerup profit/margin calculation + UI

Files: `public/js/profit_calculator.js`, `public/js/sales_powerup.js`,
`api.py:get_item_info_for_quotation`, `client_scripts/copy_as_message_*.js`.
Date: 2026-09-29. Review only — no code changed.

## Two "Powerup" buttons
- `sales_powerup.js:179` adds a standalone `PowerUp` toggle (turns item info + margin on/off).
- `client_scripts/copy_as_message_*.js:21` (shipped Sep 23) adds a `Powerup ▾` group
  on Quotation / Sales Order / Sales Invoice.
Both appear side by side. Fix: move the toggle into the `Powerup ▾` group.

## Findings

### Blocker
1. **Cost data leaks to any desk user.** `get_item_info_for_quotation` is whitelisted
   with no server-side role check; `sales_visible_to_role` is enforced only in the
   browser. Any logged-in user can call it and read `valuation_rate` and
   `last_purchase_rate` for any item.

### Major (wrong numbers)
2. **Margin understated on tax-inclusive documents.** `calculate_item_profit` divides a
   net-of-tax profit by the tax-inclusive `rate`; `calculate_doc_profit` divides by
   `grand_total`. Verified on dev (16% VAT, POS-01217, F049): shows **20.6%**, true
   gross margin **23.9%**. The same sale on a tax-exclusive doc shows 23.9%, so the
   colour bands (10/20/30%) flip depending only on the tax setting.
3. **UOM ignored.** Bin `valuation_rate` is per *stock* UOM; `rate` is per *selling*
   UOM. Item: `rate - valuation_rate` (needs `× conversion_factor`). Doc:
   `valuation_rate × qty` (needs `stock_qty`). Selling a Box of 12 shows a huge
   fake margin. Latent on dev (no conversion_factor ≠ 1 rows).
4. **Currency mixed.** Valuation is company currency; item compares against
   transaction-currency `rate`/`net_rate` (should be `base_net_rate`). Doc level mixes
   `base_net_total` with transaction `total_taxes_and_charges` / `grand_total`.
   Latent on dev (no conversion_rate ≠ 1 docs).
5. **Uncosted items inflate profit.** Items with no valuation (no warehouse, no Bin,
   service items, or fetch still in flight) add revenue with zero cost. The code
   counts `items_with_cost` but never shows it.
6. **Item-level uses `rate` not `net_rate` when tax is exclusive**, so a document-level
   discount (`additional_discount_percentage`) is ignored per row but included in the
   summary — rows and summary disagree.

### Major (efficiency)
7. **N+1 requests.** One `frappe.call` per item row, 4 SQL queries each. 40 lines =
   40 requests / 160 queries. On form open this runs **twice** (`onload` and
   `refresh` both call `check_and_setup` → `setup_all_items`), and again after every save.
8. **Summary re-rendered N times.** Every item response schedules
   `add_profit_metrics` (200ms), plus `rate`/`qty`/`grand_total`/
   `total_taxes_and_charges` each schedule their own → 3–4 re-renders per edit. Needs
   one debounced render.

### Minor
9. Toggle hard-codes `System Manager`, while info visibility uses
   `sales_visible_to_role` — a role that may see the data cannot toggle it. The button
   is also added before settings load, so it shows even when the doctype's powerup is off.
10. Row info requires a customer (`sales_powerup.js:91`); stock/cost don't need one.
11. `render_item_info` uses `cur_frm`, and the hide path does global
    `$('.sales-item-info').remove()` — hits other open forms.
12. Last Purchase / Last Sale use `rate` (doc currency, doc UOM) — not comparable
    across UOM/currency; should be `base_rate / conversion_factor`, then converted
    into the current row's UOM/currency for display.
13. `item_rate` captured when the request is sent; a rate edit before the response
    lands renders a stale margin.

### Nit
14. Four copy-pasted handler blocks (~450 lines) — one loop over the doctypes.
15. `get_profit_indicator` logic duplicated; `profit_label` computed and unused.
16. Server no-warehouse branch uses unweighted `AVG(valuation_rate)` — dead from this
    caller today, wrong if reused.

## UI suggestions
- `Powerup ▾` → **Show Item Insights / Hide Item Insights** (label reflects state).
- Summary bar: add coverage — `Costed 4/5` in amber when incomplete, with the
  uncosted item codes in a tooltip; add **Markup** next to Margin (sales staff
  often think in markup).
- Row chip tooltip: `Net 525.86 − Cost 400.00 = 125.86/unit (23.9%)` so the number is
  auditable. Show a grey `No cost` chip instead of nothing.
- `Phy / Res / Avl` → `In stock / Reserved / Available` in the tooltip, keep short
  labels inline.
- Replace per-row "Loading item info…" flicker with one load for all rows (falls out of #7).
- Optional: make the 10/20/30 margin bands configurable in PowerPack Settings.

## Proposed fix order
1. #1 server role check (tiny, security).
2. Button merge + #9 (fixes the reported issue).
3. Calculation fixes #2–#6 in `profit_calculator.js` with a JS-free Python mirror
   test or a node unit test of the pure functions.
4. Batch endpoint + single debounced render (#7, #8), dedupe handlers (#14).
5. UI items above.
