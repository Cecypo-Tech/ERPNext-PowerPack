# Review: move PowerPack buttons out of "Actions" into "Powerup"

Branch: fix/price-import-powerup-button

## Bug
Item Price list: the Actions dropdown flashed for ~30 ms on load and disappeared.
`price_import_powerup.js` registered "Import Prices (PowerPack)" with
`page.add_action_item`, i.e. inside frappe's list Actions dropdown. That group is
shown only while list rows are ticked (`list_view.js:620` →
`toggle_actions_menu_button(checked > 0)`), so every list refresh with nothing ticked
hides it. The import needs no row selection, so it was unreachable without a
pointless tick. Introduced by c5e8110.

## Change
- `price_import_powerup.js`: `add_inner_button("Import Prices", …, "Powerup")`.
- ~~`quick_pay.js`, `quick_pay_mpesa.js`: Sales Order form group `Actions` → `Powerup`~~
  Reverted at the user's request — Quick Pay stays under `Actions`.
- README: Import Prices instructions updated.

Audited and left alone: Permission Manager's own page "Actions" menu (intentional),
the "Actions" table column in payment reconciliation, site Client Script
"Salary Slip Download" (correct: acts on ticked rows). Site-only Client Script
"SI - Copy to Clipboard" also uses a form group named "Actions" — DB data, not in
this repo; not changed.

## Verification (Playwright against dev.localhost after `bench build --app cecypo_powerpack`)
- /app/item-price: Powerup ▾ Import Prices visible on load, after ticking a row, and
  after unticking; clicking opens the "Import Prices" dialog; no Import entry left
  in the Actions dropdown.
- /app/sales-order/SAL-ORD-2026-00031 (enable_quick_pay stubbed true in-page):
  Quick Pay appears under Powerup. Mpesa button not exercised (needs an Mpesa
  setup); the change there is the identical group-label token.

## Findings
- Blocker: none
- Major: none
- Nit: label shortened to "Import Prices" since the Powerup group already says whose it is.
