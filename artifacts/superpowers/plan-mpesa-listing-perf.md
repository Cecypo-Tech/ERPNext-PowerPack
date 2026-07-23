# Plan: Fix slow Mpesa Quick Pay listing (index + count caching)

## Goal
Make `list_pending_mpesa_payments` fast for companies with large unsubmitted
`Mpesa C2B Payment Register` tables.

## Root cause (verified)
- No DB index on `businessshortcode` / `docstatus` → `frappe.db.count` (api.py:293)
  is a full-table scan, run on **every** call including the empty-search open.
- Search uses `LIKE '%term%'` across 4 columns → leading-wildcard full scan (capped 100).
- Pagination alone does NOT fix this (chosen approach: index + count caching).

## Scope confirmed
- `list_pending_mpesa_payments` + `process_mpesa_quick_pay` are called ONLY from
  `quick_pay_mpesa.js` (Quick Pay - Mpesa). No other callers.

## Changes

1. **Index patch** — `cecypo_powerpack/patches/v1/add_mpesa_c2b_index.py`
   - Guard: return if doctype `Mpesa C2B Payment Register` doesn't exist.
   - `frappe.db.add_index("Mpesa C2B Payment Register", ["businessshortcode", "docstatus"])`
     (idempotent; checks existence).
   - Register under `[post_model_sync]` in `patches.txt`.

2. **Server** — `cecypo_powerpack/quick_pay/api.py::list_pending_mpesa_payments`
   - Add `with_count: int = 1`. Compute `total_count` only when truthy; else 0.

3. **Client** — `cecypo_powerpack/public/js/quick_pay_mpesa.js`
   - On initial open callback: keep `dialog.total_count = r.message.count`.
   - `load_mpesa_payments`: pass `with_count: 0`; rebuild
     `dialog.mpesa_data = {count: dialog.total_count, payments: r.message.payments || []}`
     so the "N pending" badge keeps the total (unchanged UX), search only filters the list.

4. **Regression test** — `cecypo_powerpack/quick_pay/test_api.py`
   - `with_count=0` skips count; `with_count=1` returns count.
   - 3-char gate still enforced (search < 3 → no payments).

## Verification
- `bench --site <site> migrate` → patch runs.
  `SHOW INDEX FROM \`tabMpesa C2B Payment Register\`` shows the composite index.
- `bench run-tests --app cecypo_powerpack --module cecypo_powerpack.quick_pay.test_api`
- `bench build --app cecypo_powerpack`
- Manual: open Quick Pay - Mpesa on a large-register company; open is fast;
  typing a search does not recompute the count.

## Risks
- Additive index on another app's table — safe, idempotent, guarded.
- Count semantics unchanged (badge = total pending).
