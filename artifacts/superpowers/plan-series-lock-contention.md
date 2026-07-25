# Plan — `tabSeries` ACC-PAY lock contention in Quick Pay

Status: **implemented** on branch `perf/release-series-lock-before-invoice` (see Outcome at end)
Date: 2026-07-25
Trigger: Frappe Cloud slow-query report — `SELECT current FROM tabSeries WHERE name='ACC-PAY-2026-' FOR UPDATE`
top by frequency; `cecypo_powerpack.quick_pay.api.process_mpesa_quick_pay` slowest endpoint.

## Phase 1 — Root cause (completed)

### The lock mechanism

`frappe/model/naming.py::getseries()` (frappe 16.27.1, verified on disk):

```python
current = (frappe.qb.from_(series).where(series.name == key).for_update().select("current")).run()
frappe.db.sql("UPDATE `tabSeries` SET `current` = `current` + 1 WHERE `name`=%s", (key,))
```

InnoDB holds a `FOR UPDATE` row lock **until the transaction commits**. Frappe commits once,
at the end of the HTTP request. Therefore:

> **lock hold time = (time of first `Payment Entry` insert) → (end of request)**

Not the duration of the SELECT itself. The query shows up "slow" because callers *wait* on it.

### What runs inside that window in `process_mpesa_quick_pay`

`quick_pay/api.py:396` — first `pe.insert()` acquires the `ACC-PAY-2026-` lock. Still held through:

1. `pe.submit()` — GL entries, SO advance_paid update (per selected payment)
2. `mpesa.submit()` — C2B `on_submit` → duplicate check + `_reconcile_payment()`
3. remaining loop iterations (N-1)
4. `so.reload()` + `build_sales_invoice()` (ERPNext `make_sales_invoice` mapper)
5. `si.insert()`
6. **`si.submit()`** ← the problem

### The smoking gun

`cecypo_etims_compliance/hooks.py:29` registers `Sales Invoice → before_submit`.
`events/sales_invoice.py::before_submit` →

- `api/sales_invoice.py:21` `get_next_invoice_number(company)` — takes a **second** `FOR UPDATE`
  lock on `tabeTIMS Settings`
- `api/client.py:128` `requests.post(url, json=payload, headers=headers, timeout=30)` — **synchronous
  HTTPS call to KRA eTIMS**
- then `insert_stock_io(doc, response)` — a **second** 30s-timeout KRA call

So when `create_invoice=1` and `submit_invoice=1` (driven by PowerPack Settings
`qp_auto_create_invoice` / `qp_auto_submit_invoice`, read in `quick_pay_mpesa.js:100`), the
`ACC-PAY-2026-` series row is locked across **up to two 30-second KRA network round-trips**.

Every other concurrent writer that creates a Payment Entry anywhere on the site — other cashiers'
Quick Pay, POS, C2B reconciliation on `Mpesa C2B Payment Register.on_submit`, Payment
Reconciliation — blocks in `SELECT ... FOR UPDATE` for that whole window. That is simultaneously
why the query tops the frequency/wait chart *and* why `process_mpesa_quick_pay` is the slowest
endpoint: they are the same incident seen from both ends.

### Secondary finding (different app, flagged not fixed here)

`cecypo_etims_compliance/etims_compliance/utils.py:51-64` — `get_next_invoice_number()` takes the
`tabeTIMS Settings` row lock and then the KRA call happens *before commit*. This serializes **all**
Sales Invoice submissions company-wide behind one 30s-timeout network call. Same class of bug,
larger blast radius, but it lives in a different repo.

### Scope note

`process_quick_pay` (cash/bank/card, `api.py:240-250`) has the identical
`create_invoice` → `si.submit()` → eTIMS shape. Fix must cover both endpoints.

### Not verified

I do not have the Frappe Cloud report itself. The mechanism above is verified from source; the
attribution of the specific chart row to this endpoint is inference consistent with the reported
symptom. Confirmation step is in Phase 2.

## Phase 2 — Confirm before changing code

1. On the production site, read the two flags:
   `bench --site <site> execute frappe.db.get_single_value --args "['PowerPack Settings','qp_auto_submit_invoice']"`
   If `qp_auto_submit_invoice` is 0, the eTIMS call is *not* in the transaction and the
   remaining lock window is the PE/mpesa loop only — that changes which fix matters.
2. Confirm eTIMS is live for the company: `eTIMS Settings.initialized == 1`.
3. Sample real KRA latency from `Integration Request` / `eTIMS Sales Invoice.creation` deltas.

Acceptance criterion for the whole change: p95 lock hold on `ACC-PAY-<year>-` drops from
seconds-to-tens-of-seconds to the DB-only PE/mpesa loop time (target < 500 ms).

## Phase 3 — Proposed fix

**Release the naming-series lock before the eTIMS network call, by committing the payment
transaction before invoice creation.**

In both `process_mpesa_quick_pay` and `process_quick_pay`, after the payment loop and before
`build_sales_invoice`:

```python
# The Payment Entries are complete and correct at this point. Commit them so the
# `ACC-PAY-<year>-` naming-series row lock (held since the first pe.insert()) is released
# before Sales Invoice submission, which fires a synchronous KRA eTIMS HTTPS call via
# cecypo_etims_compliance's Sales Invoice before_submit hook. Holding a global series lock
# across a third-party network round-trip serialises every other Payment Entry on the site.
frappe.db.commit()
```

then wrap SI creation so a failure cannot present as "nothing happened":

```python
try:
    so.reload()
    si = builders.build_sales_invoice(...)
    si.insert()
    builders.sync_so_party_fields(si, so)
    if submit_invoice:
        si.submit()
    result["sales_invoice"] = {"name": si.name, "submitted": si.docstatus == 1}
except Exception:
    frappe.db.rollback()
    frappe.log_error(frappe.get_traceback(), f"Quick Pay: invoice creation failed for {so.name}")
    result["sales_invoice"] = None
    result["invoice_error"] = _("Payments recorded, but the invoice could not be created. Create it from the Sales Order.")
```

### Trade-off, stated explicitly

This deliberately gives up all-or-nothing atomicity between payments and invoice. That is the
correct semantic: the money *was* received and the Payment Entries are the record of it; a KRA
timeout must not silently discard a recorded receipt. Today a late failure rolls back everything
including the submitted PEs, which is arguably worse. The client must surface `invoice_error`.

### Rejected alternatives

- **Enqueue the SI as a background job** — fully removes eTIMS latency from the web request, but
  the dialog can no longer show the invoice name, and the eTIMS lock contention just moves to the
  worker pool. Larger UX change; revisit if Fix 3 is not enough.
- **Consolidate N M-Pesa payments into one PE** — does not help. The series row is locked once per
  transaction, not once per insert; N PEs in the same transaction cost one lock acquisition.
- **Change Payment Entry naming to hash** — breaks accounting numbering conventions. No.
- **Retry on lock wait timeout** — treats the symptom, adds load.

## Phase 4 — Implementation steps

1. Write a failing test first (`quick_pay/test_api.py`): assert `frappe.db.commit` is called
   between the last `pe.submit()` and `build_sales_invoice` — mock-order assertion, no real commit.
2. Write a test asserting an SI failure returns `success: True` with `invoice_error` set and the
   Payment Entries still present.
3. Apply the change to `process_mpesa_quick_pay`.
4. Apply the same change to `process_quick_pay`.
5. Surface `invoice_error` in `quick_pay_mpesa.js` and `quick_pay.js` (warning toast, not a
   red error — the payment succeeded).
6. Full suite: `bench run-tests --app cecypo_powerpack --module cecypo_powerpack.quick_pay.test_api`

## Verification

```bash
cd /home/kushal/frappe-bench
bench run-tests --app cecypo_powerpack --module cecypo_powerpack.quick_pay.test_api
bench run-tests --app cecypo_powerpack
bench build --app cecypo_powerpack   # JS changes
```

Post-deploy: re-check the Frappe Cloud slow-query panel for `tabSeries ... ACC-PAY` wait time,
and `process_mpesa_quick_pay` p95, over the following 24h.

## Outcome

Implemented as `_finalize_with_invoice()` in `quick_pay/api.py`, called by both
`process_quick_pay` and `process_mpesa_quick_pay`.

Two deviations from the plan as written, both deliberate:

1. **Commit placed inside the `if create_invoice` branch, not unconditionally after the payment
   loop.** An unconditional commit would make the pre-existing
   `test_full_payment_creates_pe_and_optional_invoice` (`test_api.py:96`, runs `create_invoice=0`
   against real dev-site data) perform a real commit, breaking Frappe's test-transaction
   isolation and permanently writing a Payment Entry to the site. With no invoice to create
   there is no expensive post-PE work to protect against anyway.
2. **Extracted a shared helper** rather than duplicating the commit + try/except in two
   endpoints. Also makes the behaviour unit-testable with mocks instead of depending on
   `skipTest("No unbilled SO available")`.

### Verification results

| Check | Result |
|---|---|
| `bench --site dev.localhost run-tests --app cecypo_powerpack --module ...quick_pay.test_api` | 18 passed, 1 pre-existing skip |
| `bench --site dev.localhost run-tests --app cecypo_powerpack` | **47 passed**, 1 skip, `OK` (was 42 before) |
| `node --check` on both JS files | pass |
| `ruff check cecypo_powerpack/quick_pay/` | All checks passed |
| `ruff format --check` | drift only in pre-existing lines (76, 346) and untouched `builders.py`; new code clean |
| `bench build --app cecypo_powerpack` | Done, 231ms |

TDD was followed: the 5 new tests were written first and confirmed red
(`AttributeError: module ... has no attribute '_finalize_with_invoice'`) before implementing.

A `ValidationError: Please select a Tax Template` appears in the full-suite output. **Confirmed
pre-existing** by stashing all changes and re-running — it reproduces identically on the baseline
with both suites reporting `OK`. Source is `erpnext_express/overrides/purchase_invoice.py:23`
firing during Frappe's global test-record teardown. Unrelated to this change; not introduced here.

### Review pass

- **Blocker:** none.
- **Major:** none.
- **Minor** — `except Exception` is deliberately broad, so a genuine programming error in invoice
  creation degrades to a soft warning rather than surfacing loudly. Mitigated by `frappe.log_error`
  writing a full traceback to Error Log. Accepted: the alternative (letting it propagate) is the
  behaviour we are specifically removing.
- **Minor** — retrying Quick Pay after an `invoice_error` will not recreate the invoice: the SO's
  `advance_paid` now covers the total, so `remaining <= 0`, the payment loop is a no-op, and the
  endpoint throws "No valid payments". This is consistent with the error message ("Create it from
  the Sales Order") but means the only recovery path is manual. Verified, not a defect.
- **Nit** — `frappe.log_error()` is called *after* `frappe.db.rollback()` so the Error Log row
  isn't discarded by the rollback. Ordering is load-bearing; comment added at the call site.

### Still unverified

`qp_auto_submit_invoice` on production was not checked (the flag question from Phase 2 went
unanswered). The change is correct either way; that flag only determines how much latency this
removes from the lock window. If it is `0`, the eTIMS call was never in the transaction and the
remaining win is limited to the DB-only PE/mpesa loop.

## Follow-up (separate, needs its own approval)

Raise against `cecypo_etims_compliance`: move the `tabeTIMS Settings` counter increment into its
own committed transaction so the eTIMS invoice-number lock is not held across the KRA call, and
drop the 30s `requests` timeout to ~10s.
