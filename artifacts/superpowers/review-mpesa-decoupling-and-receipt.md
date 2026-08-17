# Review: making the M-Pesa app optional, and the receipt transaction id

Date: 2026-08-17
Merged to `main` as `d840d46` and `86d7f9e`.

## Framing

Two changes shipped together. They are not the same kind of work and the
record should not pretend otherwise.

**The decoupling is hardening, not a bug fix.** Confirmed with the user: no
site runs PowerPack without `frappe_mpsa_payments`. The quotation crash it
prevents is therefore real in the code and hypothetical in practice - nobody
has hit it and, on the current fleet, nobody would. It is worth having for
~50 lines, but it fixed a possibility, not an outage. The commit message
(`d840d46`) reads as a fix and overstates this; it is left as-is rather than
rewriting pushed history on a shared branch.

**The receipt change is a genuine defect fix.** Measured, not inferred: across
every Phone payment row on `dev.localhost`, the lookup resolved **0 times out
of 10**, so customers were handed receipts printing `None` where the M-Pesa
transaction id belongs.

## The dependency

One-way and undeclared. `frappe_mpsa_payments` refers to nothing in PowerPack;
PowerPack named M-Pesa doctypes as strings, so nothing at Python level revealed
the coupling and nothing enforced it at install time.

Guarded at three entry points, because everything else already sat behind one
of them:

| Guard | Without the app |
| --- | --- |
| `payable_gateways()` | `[]` - no Pay button; `_resolve_gateway` throws the existing "M-Pesa is not available for this document" |
| `_settled_by_a_previous_request()` | `False` - this is the quotation crash |
| `_mpesa_shortcode_for_company()` | `None` - availability reports false, pending list empty, reconcile throws the existing "No Mpesa Settings" |

`patches/v1/add_mpesa_c2b_index.py` was already guarded with `table_exists`; a
patch runs outside the Jinja sandbox, so it can use it.

## The receipt

The print format passed `payment.reference_no` as the register's **docname**,
but register records are named `MPC2B-...`. Measured across 10 Phone payment
rows:

| | count |
| --- | --- |
| `reference_no` is a register docname (lookup works today) | **0** |
| `reference_no` matches a register `transid` | 9 |
| no register row at all (taken by STK push) | 1 |

Correcting the lookup to filter on `transid` would have fixed 9 of 10 - the
tenth was an STK push, which leaves no register row. But `reference_no` already
*is* the receipt number in all 10, so the row prints what it is carrying and
makes no query at all.

Rendered against live invoices:

```
POS-00038   before: Mpesa-898102: 3.00 None      after: ... 3.00 UHACV28DPC
POS-00028   before: Mpesa-111222: 5.00 None      after: ... 5.00 UG9030DKSR
POS-00026   before: Mpesa-111222: 600.00 None    after: ... 600.00 W213122AX6
```

That removed the last M-Pesa doctype named in a fixture, so the existence guard
added minutes earlier became dead code and went with it. A test pins the print
format against naming one again.

## Verification

- `test_mpesa_app_optional` - 11 tests. Each guard test stubs the query it
  protects with a raiser, so a pass proves the query was never reached rather
  than that the answer happened to look right. Two tests assert the guards do
  *not* disable the feature where the app is present.
- `test_pay_by_link_status` (19), `quick_pay.test_api` (18),
  `test_validators` (18), `test_builders` (3), `test_email_group_powerup`,
  `test_price_import_api`, `test_item_search` - all green.
- All five live short links re-rendered unchanged, Pay button intact.

## Known gaps

1. **Three PowerPack test modules fail** - `test_min_selling_price`,
   `test_zero_allocate_paste`, `test_powerpack_settings` - all on the same
   `Please select a Tax Template` validation. Verified failing identically at
   `1bac328`, before any of this work, so pre-existing. The suite is not green
   as a whole and this is unresolved.
2. **Verified on `dev.localhost` only** - one site, one company. The
   multi-company and multi-shortcode gateway paths were not exercised.
3. **Deploy step required**: the print format is a fixture, so sites need
   `bench --site <site> migrate` before receipts stop printing `None`.
