# Spike: price-list popup on the items grid Rate field (QT / SO / SI)

Question: can a klik_pos-style price popup (one row per selling price list, then an editable
"Custom Price") attach to the Rate field in the items grid of Quotation / Sales Order /
Sales Invoice?

Answer: yes. Throwaway script injected into the desk (headless Chromium, dev.localhost,
unsaved draft SAL-QTN-2026-00003 + a `Consulting` row; nothing saved, nothing committed).

## Worked
- Focus on the row's Rate opens a popup under the cell: Retail 600, Standard Selling KES
  10,000 (document-currency lists only), Custom Price. Fetch ~20-40 ms.
- Enter / mouse pick sets `rate`; amount, taxes and grand total recalculate.
- Up/Down move, Custom Price focuses with its value selected so typing replaces it (777).
- Typing straight into the Rate field closes the popup and keeps the typed rate.
- Read-only Rate (docfield read_only): popup opens on click with price lists only, no Custom.
- No page errors.

## Pitfalls found (all solved in the spike)
1. Item Price is not readable by a Sales User -> needs a whitelisted server method (spike
   reused Lens's `get_lens_data`; the real thing wants a lean one).
2. Frappe's grid keyboard navigation (Up/Down change rows, Enter) runs alongside the popup's;
   it stole focus and once opened a stray Lens dialog. Fix: capture-phase keydown that
   swallows keys while the popup is open.
3. A read-only Rate is a *disabled* input, which swallows clicks -> capture-phase mousedown
   on the cell.
4. Click-then-focus fired two fetches -> in-flight guard.
5. After a pick the field stays focused, so focus never re-fires -> reopen on click of the
   focused field (and Alt+Down).
6. Custom Price must select its seeded value after focus settles (setTimeout), or digits
   are prepended.

## Design questions for the real feature
- Picking a list price sets `rate` only; `price_list_rate` stays at the document's list
  (10,000 vs 600), so the row reads as a discount. Set `price_list_rate` too, or only `rate`?
- Which lists: all enabled selling lists in the document currency, or a configured subset /
  order? UOM: price per row UOM vs stock UOM (convert by conversion_factor)?
- Interaction with Minimum Selling Price (a pick below the floor) - warn in the popup?
- When does Custom Price appear: rate editable on the row (spike) - any extra role gate?
- Setting: one PowerPack checkbox, or per doctype like Sales Powerup?
