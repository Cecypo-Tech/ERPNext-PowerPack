# Design: Rate Price Picker (QT / SO / SI items grid)

Status: proposed, awaiting approval. Follows the spike in `spike-rate-price-popup.md`.
Decisions taken from the spike's recommendations (approved 2026-10-01).

## What the user gets
Focus (or click) the Rate cell of an items row on a Quotation, Sales Order or Sales Invoice
and a dropdown opens under it, as in klik_pos:
- one line per enabled selling price list in the document's currency that has a price for
  the item, showing that price for the row's UOM;
- a trailing editable **Custom Price** line, only when the row's Rate is editable for that
  user (draft document, rate not read-only);
- a line below the Minimum Selling Price floor is marked (red "below min" tag). It is still
  selectable; saving runs the normal floor check as today.

Keys: Up/Down move, Enter picks, Esc closes, typing in the Rate field closes the dropdown and
keeps the typed rate. Alt+Down or a click on an already-focused Rate reopens it. Mouse works.

## What a pick does
- Price list line: clear the row's `discount_percentage`, `discount_amount` and
  `margin_rate_or_amount`, then set `price_list_rate` to the picked price. ERPNext's own
  `price_list_rate` handler then sets `rate` = that price and recalculates. The row reads
  "Retail 600, no discount" instead of "10,000 less 94%".
- Custom Price: set `rate` only, exactly as if typed in the field (ERPNext derives the
  discount against the list price, as today).
- Known, unchanged ERPNext behaviour: changing the row's Qty afterwards re-applies the
  document's price list (ERPNext does this to a hand-typed rate too). Pick after Qty.

## Server: `cecypo_powerpack/rate_price_picker.py`
`get_rate_options(doctype, item_code, uom, stock_uom, conversion_factor, currency, customer,
company, transaction_date, conversion_rate, net_factor)` - whitelisted:
- gate: `enable_rate_price_picker`; doctype in QT/SO/SI; `frappe.has_permission(doctype, "read")`
  (the document may be unsaved, so a doctype-level check). Item Price itself is read on the
  user's behalf - a Sales User cannot read it (spike finding).
- price lists: enabled, `selling = 1`, `currency = currency`; per list, the price comes from
  ERPNext's `get_price_list_rate_for` (customer-specific first, validity dates, row UOM or
  stock UOM x conversion factor, honouring the list's `price_list_uom_dependant`). Lists
  without a price are left out. Ordered by price list name.
- floor flag: only when Minimum Selling Price is enabled and a rule applies to the item's
  group. Floor from the existing `min_selling_price` helpers (`pick_rule`, `_basis_rate`,
  `compute_floor`) on a synthetic row. Price compared on the validator's basis: price x
  `conversion_rate` x `net_factor` (the row's current net_rate / rate, which carries
  inclusive taxes and document discount; 1 when the row has no rate yet). Returns only a
  boolean per line - never the floor or cost, so it leaks nothing to users without
  `sales_visible_to_role`.
- returns `[{price_list, rate, below_floor}]`.

## Client: `public/js/rate_price_picker.js` (bundle import)
Gated by `CecypoPowerPack.Settings.isEnabled('enable_rate_price_picker')`, bound on form
refresh of the three doctypes. Carries the spike's fixes:
- capture-phase keydown that swallows Up/Down/Enter/Esc while open (frappe's grid
  navigation otherwise moves rows and stole focus);
- capture-phase mousedown on the cell for a read-only Rate (its disabled input swallows
  clicks) -> price lists only;
- in-flight guard per row (click + the focus that follows asked twice);
- Custom Price selects its seeded value after focus settles;
- per-row cache of options for the form session, cleared when item, UOM, customer,
  currency or date change on the row/doc;
- fixed-position popup flipped above when there is no room below, themed with frappe CSS
  variables (dark mode), styles in `public/css/rate_price_picker.scss` via the bundle.

## Setting
PowerPack Settings > Sales & POS: **Enable Rate Price Picker** (Check, default 0 - opt-in,
since it changes how the Rate cell behaves for every user).

## Tests
- Python (`tests/test_rate_price_picker.py`): options per currency (other-currency lists
  excluded), disabled / buying lists excluded, customer-specific price wins, UOM conversion
  (stock-UOM price x factor; exact-UOM price as is), expired price excluded, below_floor
  true/false around the floor and absent when MSP is off, gate / doctype / permission refusals.
- Browser e2e (python playwright, throwaway user, unsaved draft): open on focus; keyboard and
  mouse pick set price_list_rate + rate with zero discount; Custom Price; typing closes;
  read-only -> no Custom Price; no grid row jump; below-min tag shown; 375px viewport.
  Then one saved throwaway Quotation (deleted after) to prove the picked price persists on
  save.
- Full app suite on a quiet site.

## Out of scope
POS Invoice / Delivery Note / purchase documents; changing the document's price list;
making a pick survive a later Qty change.
