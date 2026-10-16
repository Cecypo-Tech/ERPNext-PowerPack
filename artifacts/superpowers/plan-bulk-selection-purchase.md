# Plan: bulk selection — Purchase Order reads buying prices

User said "implement it straight away" 2026-10-04 (execute-plan gate waived).

Root cause: `get_bulk_item_details` (api.py) accepts `doctype` but never branches on
it. For Purchase Order it filters Item Price by `selling: 1` (buying prices are
`selling 0 / buying 1` → dialog shows "—"), filters Item by `is_sales_item: 1`
(drops purchase-only items), and reads the tax template as a Sales Taxes and
Charges Template. The PO's own `buying_price_list` is already passed correctly.

## Steps

1. **Tests first** (`tests/test_bulk_selection_purchase.py`): PO returns the
   buying price; PO lists a purchase-only item; Sales Order still ignores buying
   prices; PO tax rate reads Purchase Taxes and Charges Template; both optimized
   and standard paths. Verify: run module → red.
2. **Fix** (`api.py` only): `buying = doctype == 'Purchase Order'`, passed to
   `_get_included_tax_rate`, `_get_bulk_items_optimized`, `_get_bulk_items_standard`,
   `_get_item_price`; pick `buying`/`selling`, `is_purchase_item`/`is_sales_item`,
   and the template doctype from it. Verify: module green, full app suite green.
3. **E2E**: new PO (Supplier A, Standard Buying KES), bulk dialog shows F049 KES 400.
4. **Review + land**: merge --no-ff to main, push upstream/main.
