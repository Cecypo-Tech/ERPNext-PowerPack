# Finish: bulk selection fetch_from backfill

## Summary of changes
- `cecypo_powerpack/public/js/bulk_selection.js` (`add_items_to_doc`): after
  ERPNext's own `item_code` trigger settles, fill the child row's
  `fetch_from: item_code.*` fields the trigger left empty, from one batched
  Item lookup. Fields come from client meta, so custom fetch_from fields are
  covered with no hardcoded list. Trigger output is never overwritten.
- Fixes the reported bug: Stock Reconciliation rows lacked item_name (also
  item_group / stock_uom) until save. Also backfills image (sales/purchase),
  grant_commission / is_stock_item (SO/SI), is_fixed_asset (PO),
  retain_sample / item_group (Stock Entry).

## Review (Blocker/Major/Minor/Nit)
- Major (fixed): non-settling lookup promise would have blocked all adds on a
  server error -> xcall + catch.
- Minor (accepted): updated existing rows are not re-backfilled (they already
  carry their fetched values).
- No Blocker / Nit.

## Verification
- `bench build --app cecypo_powerpack` -> clean (twice).
- Browser e2e, dev.localhost:
  - Stock Reconciliation: 3 items + 1 item runs -> item_name, item_group,
    stock_uom, qty as entered, valuation from trigger. PASS.
  - Sales Invoice: uom/conversion/tax template/income account unchanged, image
    backfilled; rate 0 correct (no price in doc's price list). PASS.
  - Forced lookup failure: row still added. PASS.
- No Python change; no unit-test harness for this file (e2e is the check).

## Follow-ups
- None needed. Deploy: asset build only (no migrate).
