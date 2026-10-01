# Review: Rate Price Picker (feat/rate-price-picker)

Independent code-review subagent verdict: "With fixes". Every finding was checked against
frappe/erpnext source before acting.

## Fixed
- Important 1 - Custom Price entered with the mouse, then Enter, applied line 0: Enter in
  the Custom box now picks it; focusing the box moves the highlight. e2e R1.
- Important 2 - a dropdown opening late (slow fetch) over a typed rate, and Backspace /
  paste not closing it: open aborts if the field's value changed during the fetch; the
  field's `input` event closes the dropdown. e2e R2 (fetch delayed 1 s), R3.
- Important 3 - Custom Price under `#.###,##` read 600.5 as 6005; empty box set 0: seeded
  with format_number at rate precision; empty / non-numeric is ignored. e2e R4, R5.
- Important 4 - partly: lines become reference-only when the user lacks write permission at
  the rate's permlevel (frappe would reset the rate on save). Kept: a merely read-only Rate
  (fixed price) still allows list picks - that is the requested behaviour ("not a fixed
  price (only choice of pricelist)"). e2e R6, and the read-only step of the main e2e.
- Important 5 - with Stock Settings auto-insert + update on the "Price List Rate" basis,
  saving after a pick would rewrite the document's own price list: the server returns
  `set_list_price: false` there and the pick sets the rate only. Unit tests + e2e R7.
- Important 6 - Item read permission (User Permissions on Item / Item Group) now enforced,
  as ERPNext's get_item_details does. Unit test.
- Important 7 - variants fall back to the template's price, as ERPNext. Unit test.
- Important 8 - the popup closed on any scroll / resize: it now follows its cell and closes
  only when the cell leaves the viewport. e2e R8. Real-phone keyboard behaviour not tested.
- Minor: row_floor honours "skip if Pricing Rule" (has_pricing_rule from the row); setting
  off returns [] instead of an error dialog; cell clicks return early on grids the picker
  does not own; skip_focus cleared if focus does not land; same-rate pick refocuses;
  rate_with_margin set on a pick; max-height + scroll for many lists; stale design doc.

## Not fixed (Minor, noted)
- Pricing Rule on the row is re-applied on save (ERPNext, as for a typed rate) - README.
- below-min flag ignores free items / returns / internal customers and uses Bin valuation
  for a stock-updating Sales Invoice: advisory only; save runs the real check.
- The floor can be bisected via net_factor - already disclosed by a failed save's message.
- Esc after a cell-click open during a grid redraw leaves focus on the page body.
- No aria-activedescendant; JS has no automated unit test (e2e scripts are throwaway).

## Verification
- `run-tests --module cecypo_powerpack.tests.test_rate_price_picker`: 20/20.
- `test_min_selling_price` 46/46, `test_price_approval` 39/39 after a one-off deadlock in a
  full run (no assertion failures).
- e2e (headless Chromium, dev, throwaway QT + prices + user, all removed): main flow at
  1400 / 375 px and R1-R8 above; no page errors.
