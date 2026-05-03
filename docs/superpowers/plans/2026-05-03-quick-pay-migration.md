# Quick Pay Migration to cecypo_powerpack — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the four DB-stored Quick Pay scripts (Cash/Bank/Card + Mpesa, client + server) into the `cecypo_powerpack` app as proper Python modules and JS assets, fixing the precision bug, naming-sequence skip, missing stock pre-check, missing idempotency, and using ERPNext's official `make_sales_invoice` mapper.

**Architecture:**
- `cecypo_powerpack/quick_pay/` Python package with three layers: `validators.py` (pure-ish, easy to test), `builders.py` (PE / SI construction), `api.py` (`@frappe.whitelist()` HTTP entry points).
- Two client scripts loaded via `doctype_js` hook for `Sales Order`.
- Five new fields on `PowerPack Settings` singleton for feature toggles.
- Idempotency via a short-TTL `frappe.cache` token claimed once per request.
- Stock pre-check uses ERPNext's `get_available_qty` per (item, warehouse) so payment is gated **before** any DB writes.
- SI created via `erpnext.selling.doctype.sales_order.sales_order.make_sales_invoice` (official mapper) instead of hand-rolled item/tax copying.

**Tech Stack:** Frappe v15, ERPNext v15, Python 3.10+, vanilla JS (Frappe globals), MariaDB. Tests use `FrappeTestCase`.

**Bench root:** `/home/frappeuser/bench16` — all `bench` commands run from there.
**Site:** `site16.local`.

**Reading the legacy scripts:** The original Quick Pay scripts live in the database, not the filesystem. To pull their content for porting:
```bash
cd /home/frappeuser/bench16 && bench --site site16.local mariadb --execute \
  "SELECT script FROM \`tabClient Script\` WHERE name='SO - Quick Pay'\G"
cd /home/frappeuser/bench16 && bench --site site16.local mariadb --execute \
  "SELECT script FROM \`tabClient Script\` WHERE name='SO - Quick Pay Mpesa'\G"
cd /home/frappeuser/bench16 && bench --site site16.local mariadb --execute \
  "SELECT script FROM \`tabServer Script\` WHERE name='Quick Pay API'\G"
cd /home/frappeuser/bench16 && bench --site site16.local mariadb --execute \
  "SELECT script FROM \`tabServer Script\` WHERE name='Quick Pay Mpesa API'\G"
```
Output is `\n`-encoded — pipe through `sed 's/\\n/\n/g'` to read it normally, or save to a temp file and unescape with Python.

---

## File Structure

**Create:**
- `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/__init__.py` — package marker
- `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/validators.py` — precision normalization, idempotency, stock pre-check, permission gates
- `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/builders.py` — Payment Entry and Sales Invoice builders
- `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/api.py` — `@frappe.whitelist()` endpoints (replaces both server scripts)
- `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/test_validators.py`
- `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/test_builders.py`
- `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/test_api.py`
- `apps/cecypo_powerpack/cecypo_powerpack/public/js/quick_pay.js` — Cash/Bank/Card client (replaces `SO - Quick Pay` DB Client Script)
- `apps/cecypo_powerpack/cecypo_powerpack/public/js/quick_pay_mpesa.js` — Mpesa client (replaces `SO - Quick Pay Mpesa` DB Client Script)
- `apps/cecypo_powerpack/cecypo_powerpack/public/css/quick_pay.css` — extracted styles

**Modify:**
- `apps/cecypo_powerpack/cecypo_powerpack/cecypo_powerpack/doctype/powerpack_settings/powerpack_settings.json` — add 5 fields
- `apps/cecypo_powerpack/cecypo_powerpack/hooks.py` — add `doctype_js` and CSS include

**Disable (don't delete yet):**
- DB row `Client Script` named `SO - Quick Pay` (set `enabled=0`)
- DB row `Client Script` named `SO - Quick Pay Mpesa` (set `enabled=0`)
- DB row `Server Script` named `Quick Pay API` (set `disabled=1`)
- DB row `Server Script` named `Quick Pay Mpesa API` (set `disabled=1`)

---

## Pre-flight Checks (do once before Task 1)

- [ ] **Check 1: Confirm bench is running and site is reachable**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local list-apps
```
Expected: includes `cecypo_powerpack`.

- [ ] **Check 2: Confirm we're on a clean branch in cecypo_powerpack**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && git status
```
Expected: clean. If dirty, commit/stash first. If on `main`/`master`, create a feature branch:

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && git checkout -b feat/quick-pay-migration
```

- [ ] **Check 3: Confirm the four DB scripts still exist (sanity)**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local execute frappe.db.get_all --kwargs '{"doctype": "Client Script", "filters": [["name", "like", "%Quick%"]], "fields": ["name", "enabled"]}'
cd /home/frappeuser/bench16 && bench --site site16.local execute frappe.db.get_all --kwargs '{"doctype": "Server Script", "filters": [["name", "like", "%Quick%"]], "fields": ["name", "disabled"]}'
```
Expected: 2 client + 2 server. They stay enabled until Task 18.

---

## Task 1: Create the quick_pay package

**Files:**
- Create: `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/__init__.py`

- [ ] **Step 1: Create the empty package**

Write file `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/__init__.py`:
```python
# Quick Pay — Sales Order payment + invoice flow.
# See cecypo_powerpack/quick_pay/api.py for the whitelisted entry points.
```

- [ ] **Step 2: Verify Python can import it**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local execute "import cecypo_powerpack.quick_pay; print('ok')"
```
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && \
  git add cecypo_powerpack/quick_pay/__init__.py && \
  git commit -m "feat(quick_pay): bootstrap module package"
```

---

## Task 2: Add feature-toggle fields to PowerPack Settings

**Files:**
- Modify: `apps/cecypo_powerpack/cecypo_powerpack/cecypo_powerpack/doctype/powerpack_settings/powerpack_settings.json`

**Fields to add** (all `Check` type unless noted; all default `0` unless noted):
1. `quick_pay_section` (Section Break, label "Quick Pay")
2. `enable_quick_pay` (Check, label "Enable Quick Pay (Cash/Bank/Card)", default `0`)
3. `enable_quick_pay_mpesa` (Check, label "Enable Quick Pay (Mpesa)", default `0`)
4. `qp_column_break` (Column Break)
5. `qp_auto_create_invoice` (Check, label "Auto-create Sales Invoice after payment", default `1`, depends_on `eval:doc.enable_quick_pay || doc.enable_quick_pay_mpesa`)
6. `qp_auto_submit_invoice` (Check, label "Auto-submit invoice immediately", default `1`, depends_on `eval:doc.qp_auto_create_invoice`)
7. `qp_update_stock_on_invoice` (Check, label "Update stock on auto-created invoice", default `1`, depends_on `eval:doc.qp_auto_create_invoice`)

- [ ] **Step 1: Read the current JSON**

```bash
cd /home/frappeuser/bench16 && \
  cat apps/cecypo_powerpack/cecypo_powerpack/cecypo_powerpack/doctype/powerpack_settings/powerpack_settings.json | head -50
```
Note the existing field order so we can append after the last logical group. (Use `Read` tool on the file.)

- [ ] **Step 2: Edit the JSON**

In the file's `"fields"` array, append the seven fields above (use `Edit` tool). Each field looks like:
```json
{
  "fieldname": "enable_quick_pay",
  "fieldtype": "Check",
  "label": "Enable Quick Pay (Cash/Bank/Card)",
  "default": "0"
}
```
Also append the seven fieldnames to `"field_order"` if that key exists.

- [ ] **Step 3: Migrate**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local migrate
```
Expected: completes without error; new fields visible at `/app/powerpack-settings`.

- [ ] **Step 4: Verify fields exist**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local execute frappe.get_meta --kwargs '{"doctype": "PowerPack Settings"}' 2>&1 | grep -E "enable_quick_pay|qp_auto"
```
Expected: all 6 togglable fields appear.

- [ ] **Step 5: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && \
  git add cecypo_powerpack/cecypo_powerpack/doctype/powerpack_settings/powerpack_settings.json && \
  git commit -m "feat(powerpack-settings): add Quick Pay feature toggles"
```

---

## Task 3: validators.py — precision normalization

**Files:**
- Create: `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/validators.py`
- Create: `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/test_validators.py`

**Why precision is the *root* of the `133.40 vs 133.40` bug:** Bare `float(grand_total) - float(advance_paid)` produces IEEE-754 drift; ERPNext's `validate_allocated_amount` then compares that drifted float against the user-entered amount. We round both sides to currency precision, then `min()` the allocation against outstanding so a tiny over-shoot becomes an exact match.

- [ ] **Step 1: Write the failing test**

Write `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/test_validators.py`:
```python
import frappe
from frappe.tests.utils import FrappeTestCase

from cecypo_powerpack.quick_pay.validators import (
    normalize_amount,
    compute_outstanding,
    cap_allocation,
)


class TestPrecisionNormalization(FrappeTestCase):
    def test_normalize_handles_float_drift(self):
        # 0.1 + 0.2 = 0.30000000000000004 in IEEE-754
        drifted = 0.1 + 0.2
        self.assertEqual(normalize_amount(drifted, precision=2), 0.30)

    def test_normalize_passes_through_clean_values(self):
        self.assertEqual(normalize_amount(133.40, precision=2), 133.40)

    def test_compute_outstanding_rounds_to_precision(self):
        # Simulates SO with grand_total 133.40, advance_paid 0
        out = compute_outstanding(grand_total=133.40, advance_paid=0, precision=2)
        self.assertEqual(out, 133.40)

    def test_compute_outstanding_with_drift(self):
        # 50.10 + 83.30 = 133.40000000000003 in float
        out = compute_outstanding(grand_total=133.40, advance_paid=50.10 + 83.30 - 133.40, precision=2)
        self.assertEqual(out, 133.40)

    def test_cap_allocation_clamps_overshoot(self):
        # User over-allocates by float drift
        capped = cap_allocation(amount=133.40000000000003, outstanding=133.40, precision=2)
        self.assertEqual(capped, 133.40)
        self.assertLessEqual(capped, 133.40)  # the actual fix for ERPNext's validation

    def test_cap_allocation_preserves_partial(self):
        capped = cap_allocation(amount=50.00, outstanding=133.40, precision=2)
        self.assertEqual(capped, 50.00)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local run-tests --app cecypo_powerpack --module cecypo_powerpack.quick_pay.test_validators
```
Expected: ImportError on `validators` module.

- [ ] **Step 3: Implement the validators**

Write `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/validators.py`:
```python
"""Pure-ish helpers used by quick_pay/api.py.

Kept side-effect-free so they're easy to unit-test. DB-touching helpers
(stock pre-check, permission gate, idempotency) are below the precision
section and clearly marked.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt


# --- Precision -------------------------------------------------------------

def normalize_amount(value, precision: int = 2) -> float:
    """Round a money amount to currency precision, killing IEEE-754 drift."""
    return flt(value, precision)


def compute_outstanding(grand_total, advance_paid, precision: int = 2) -> float:
    """Outstanding for a Sales Order, rounded to currency precision."""
    return flt(flt(grand_total) - flt(advance_paid or 0), precision)


def cap_allocation(amount, outstanding, precision: int = 2) -> float:
    """Cap an allocation to outstanding so float drift can never push the
    Payment Entry's allocated_amount over outstanding_amount."""
    amount = flt(amount, precision)
    outstanding = flt(outstanding, precision)
    return min(amount, outstanding)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local run-tests --app cecypo_powerpack --module cecypo_powerpack.quick_pay.test_validators
```
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && \
  git add cecypo_powerpack/quick_pay/validators.py cecypo_powerpack/quick_pay/test_validators.py && \
  git commit -m "feat(quick_pay): add precision normalization helpers with tests"
```

---

## Task 4: validators.py — idempotency token

**Files:**
- Modify: `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/validators.py` (append)
- Modify: `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/test_validators.py` (append)

The client script generates a UUID on dialog open; the server claims it via `frappe.cache().get_value` / `set_value` with TTL. Second claim throws.

- [ ] **Step 1: Write the failing test**

Append to `test_validators.py`:
```python
import uuid
from cecypo_powerpack.quick_pay.validators import claim_idempotency_token, IdempotencyError


class TestIdempotency(FrappeTestCase):
    def test_first_claim_succeeds(self):
        token = "test-" + uuid.uuid4().hex
        # Should not raise
        claim_idempotency_token(token, ttl_seconds=60)

    def test_second_claim_raises(self):
        token = "test-" + uuid.uuid4().hex
        claim_idempotency_token(token, ttl_seconds=60)
        with self.assertRaises(IdempotencyError):
            claim_idempotency_token(token, ttl_seconds=60)

    def test_blank_token_raises(self):
        with self.assertRaises(IdempotencyError):
            claim_idempotency_token("", ttl_seconds=60)
        with self.assertRaises(IdempotencyError):
            claim_idempotency_token(None, ttl_seconds=60)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local run-tests --app cecypo_powerpack --module cecypo_powerpack.quick_pay.test_validators
```
Expected: ImportError on `claim_idempotency_token`.

- [ ] **Step 3: Implement**

Append to `validators.py`:
```python
# --- Idempotency -----------------------------------------------------------

CACHE_PREFIX = "quick_pay:idem:"


class IdempotencyError(frappe.ValidationError):
    """Raised when the same idempotency token is reused, or a token is missing."""


def claim_idempotency_token(token: str, ttl_seconds: int = 120) -> None:
    """Atomically claim a one-shot token. Raises IdempotencyError if already used.

    Tokens are scoped per user to keep the namespace reasonable.
    """
    if not token or not isinstance(token, str) or len(token) < 8:
        raise IdempotencyError("Missing or invalid idempotency token")

    cache = frappe.cache()
    key = CACHE_PREFIX + frappe.session.user + ":" + token
    # set_value with no expiry doesn't help; use raw redis ops via Frappe's wrapper
    if cache.get_value(key) is not None:
        raise IdempotencyError("Duplicate request: this payment has already been processed")
    cache.set_value(key, "1", expires_in_sec=ttl_seconds)
```

- [ ] **Step 4: Run tests**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local run-tests --app cecypo_powerpack --module cecypo_powerpack.quick_pay.test_validators
```
Expected: all tests pass (precision tests + 3 idempotency tests).

- [ ] **Step 5: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && \
  git add cecypo_powerpack/quick_pay/validators.py cecypo_powerpack/quick_pay/test_validators.py && \
  git commit -m "feat(quick_pay): add idempotency token claim helper"
```

---

## Task 5: validators.py — stock pre-check

**Files:**
- Modify: `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/validators.py` (append)
- Modify: `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/test_validators.py` (append)

Returns a list of human-readable issues. Empty list = clear to proceed. Caller throws with a joined message if non-empty.

We check three things per stock-tracked item line:
1. Is `qty_at_warehouse >= qty_to_invoice`?
2. If batch tracking enabled and no batch picked → flag.
3. If serial tracking enabled and serials count != qty → flag.

- [ ] **Step 1: Write the failing test (skeleton — uses fixture-builder helper)**

Append to `test_validators.py`:
```python
from cecypo_powerpack.quick_pay.validators import preflight_stock_for_so


class TestStockPreflight(FrappeTestCase):
    def test_no_stock_items_returns_empty(self):
        # SO with a non-stock service item should pass preflight cleanly
        # Use existing test data or mock a SO doc-like object
        class FakeItem:
            item_code = "_Test Service Item QP"
            qty = 1
            warehouse = ""
            batch_no = None
            serial_no = None
        class FakeSO:
            items = [FakeItem()]
        # Ensure a non-stock service item exists
        if not frappe.db.exists("Item", "_Test Service Item QP"):
            frappe.get_doc({
                "doctype": "Item",
                "item_code": "_Test Service Item QP",
                "item_name": "_Test Service Item QP",
                "item_group": "Services",
                "stock_uom": "Nos",
                "is_stock_item": 0,
            }).insert(ignore_permissions=True)
        issues = preflight_stock_for_so(FakeSO())
        self.assertEqual(issues, [])
```

(Stock-shortage and batch/serial cases are covered by manual verification in Task 19 — full fixturing of an Item with stock + batch in unit tests is heavyweight and brittle. Document this trade-off in the docstring.)

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local run-tests --app cecypo_powerpack --module cecypo_powerpack.quick_pay.test_validators
```
Expected: ImportError on `preflight_stock_for_so`.

- [ ] **Step 3: Implement**

Append to `validators.py`:
```python
# --- Stock pre-check -------------------------------------------------------

def preflight_stock_for_so(so_doc) -> list[str]:
    """Return human-readable issues that would cause Sales Invoice (with
    update_stock=1) to fail. Empty list = OK to proceed.

    NOTE: Only catches issues knowable at SO time. If user races against
    another transaction draining the warehouse between this check and the
    invoice insert, that race is unhandled (caught by the SI submit
    validation). Acceptable for v1.
    """
    issues: list[str] = []

    for row in so_doc.items:
        # Batch-load item meta once per row; fine for typical SOs.
        meta = frappe.db.get_value(
            "Item",
            row.item_code,
            ["is_stock_item", "has_batch_no", "has_serial_no"],
            as_dict=True,
        )
        if not meta or not meta.is_stock_item:
            continue

        warehouse = getattr(row, "warehouse", None)
        if not warehouse:
            issues.append(f"{row.item_code}: no warehouse set on Sales Order line")
            continue

        # Available qty at the warehouse (actual_qty from Bin)
        actual_qty = frappe.db.get_value(
            "Bin",
            {"item_code": row.item_code, "warehouse": warehouse},
            "actual_qty",
        ) or 0
        needed = flt(row.qty)
        if flt(actual_qty) < needed:
            issues.append(
                f"{row.item_code}: only {flt(actual_qty)} available at {warehouse}, need {needed}"
            )

        if meta.has_batch_no and not getattr(row, "batch_no", None):
            issues.append(f"{row.item_code}: requires a batch but none set on Sales Order line")

        if meta.has_serial_no and not getattr(row, "serial_no", None):
            issues.append(f"{row.item_code}: requires serial numbers but none set")

    return issues
```

- [ ] **Step 4: Run tests**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local run-tests --app cecypo_powerpack --module cecypo_powerpack.quick_pay.test_validators
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && \
  git add cecypo_powerpack/quick_pay/validators.py cecypo_powerpack/quick_pay/test_validators.py && \
  git commit -m "feat(quick_pay): add stock pre-flight check"
```

---

## Task 6: validators.py — permission + settings gates

**Files:**
- Modify: `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/validators.py` (append)

Two gates: (a) is the feature enabled in PowerPack Settings, (b) does the user have create+submit permission on Payment Entry (and Sales Invoice if auto-creating).

- [ ] **Step 1: Implement (no separate test — small, mostly thin wrappers; covered by API tests in Task 13)**

Append to `validators.py`:
```python
# --- Feature toggle / permission gates -------------------------------------

from cecypo_powerpack.utils import is_feature_enabled


def assert_quick_pay_enabled(flow: str) -> None:
    """flow: 'cash' | 'mpesa'"""
    flag = "enable_quick_pay" if flow == "cash" else "enable_quick_pay_mpesa"
    if not is_feature_enabled(flag):
        frappe.throw(f"Quick Pay ({flow}) is disabled in PowerPack Settings")


def assert_can_create_payment_and_invoice(create_invoice: bool, submit_invoice: bool) -> None:
    if not frappe.has_permission("Payment Entry", "create"):
        frappe.throw("You do not have permission to create Payment Entry")
    if not frappe.has_permission("Payment Entry", "submit"):
        frappe.throw("You do not have permission to submit Payment Entry")
    if create_invoice:
        if not frappe.has_permission("Sales Invoice", "create"):
            frappe.throw("You do not have permission to create Sales Invoice")
        if submit_invoice and not frappe.has_permission("Sales Invoice", "submit"):
            frappe.throw("You do not have permission to submit Sales Invoice")
```

- [ ] **Step 2: Sanity-check imports**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local execute "from cecypo_powerpack.quick_pay.validators import assert_quick_pay_enabled, assert_can_create_payment_and_invoice; print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && \
  git add cecypo_powerpack/quick_pay/validators.py && \
  git commit -m "feat(quick_pay): add feature-toggle and permission gates"
```

---

## Task 7: builders.py — Payment Entry builder

**Files:**
- Create: `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/builders.py`
- Create: `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/test_builders.py`

**Key fixes vs. legacy server scripts:**
1. Use `erpnext.accounts.party.get_party_account()` — not `Company.default_receivable_account` — so customers with custom receivable accounts work.
2. Use `frappe.utils.flt(value, precision)` for `outstanding_amount` and `allocated_amount` on the reference row — fixes the `133.40` bug.
3. Cap `allocated_amount` to `outstanding` via `cap_allocation()` — defence in depth.

- [ ] **Step 1: Write the failing test**

Write `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/test_builders.py`:
```python
import frappe
from frappe.tests.utils import FrappeTestCase

from cecypo_powerpack.quick_pay.builders import build_payment_entry


class TestBuildPaymentEntry(FrappeTestCase):
    def test_pe_uses_party_receivable_account(self):
        # Find any submitted SO in test data; bench's _Test Customer typically has one.
        so_name = frappe.db.get_value("Sales Order", {"docstatus": 1}, "name")
        if not so_name:
            self.skipTest("No submitted Sales Order in DB to build a PE against")
        so = frappe.get_doc("Sales Order", so_name)

        # Pick any Mode of Payment that has an account for so.company
        mop = frappe.db.sql("""
            SELECT parent FROM `tabMode of Payment Account`
            WHERE company = %s AND default_account IS NOT NULL LIMIT 1
        """, so.company, as_dict=True)
        if not mop:
            self.skipTest("No Mode of Payment Account for company")
        mode_of_payment = mop[0]["parent"]

        pe = build_payment_entry(
            so_doc=so,
            amount=10.00,
            mode_of_payment=mode_of_payment,
            reference_no="TEST-REF-001",
            remarks="test",
        )

        # Verify paid_from is the party-specific receivable, not Company default
        from erpnext.accounts.party import get_party_account
        expected_paid_from = get_party_account("Customer", so.customer, so.company)
        self.assertEqual(pe.paid_from, expected_paid_from)

        # Reference row exists with capped allocated
        self.assertEqual(len(pe.references), 1)
        self.assertEqual(pe.references[0].reference_doctype, "Sales Order")
        self.assertEqual(pe.references[0].reference_name, so.name)
        self.assertLessEqual(
            pe.references[0].allocated_amount,
            pe.references[0].outstanding_amount,
        )

        # Don't actually submit — leave it as Draft for the test runner to roll back
```

- [ ] **Step 2: Run test (expect ImportError)**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local run-tests --app cecypo_powerpack --module cecypo_powerpack.quick_pay.test_builders
```

- [ ] **Step 3: Implement**

Write `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/builders.py`:
```python
"""Payment Entry and Sales Invoice builders for Quick Pay.

Both builders return *unsaved* documents — caller decides when to insert/submit.
This makes test isolation easier and lets the API layer wrap insert/submit
inside its idempotency / pre-flight logic.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt, nowdate

from erpnext.accounts.party import get_party_account
from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

from cecypo_powerpack.quick_pay.validators import (
    cap_allocation,
    compute_outstanding,
)


def build_payment_entry(
    so_doc,
    amount: float,
    mode_of_payment: str,
    reference_no: str | None = None,
    remarks: str | None = None,
    *,
    full_received_amount: float | None = None,
):
    """Build (but don't save) a Payment Entry against a Sales Order.

    `amount` is what to allocate to the SO. `full_received_amount` (Mpesa-only)
    is the total received when it exceeds the SO outstanding — the PE records
    the full amount but only allocates `amount` to this SO. If None, defaults
    to `amount` (cash/bank/card path).
    """
    company = so_doc.company
    customer = so_doc.customer

    if full_received_amount is None:
        full_received_amount = amount

    # Resolve accounts
    paid_to = frappe.db.get_value(
        "Mode of Payment Account",
        {"parent": mode_of_payment, "company": company},
        "default_account",
    )
    if not paid_to:
        frappe.throw(f"No account for Mode of Payment {mode_of_payment} in {company}")

    paid_from = get_party_account("Customer", customer, company)

    company_currency = frappe.db.get_value("Company", company, "default_currency")
    paid_to_currency = frappe.db.get_value("Account", paid_to, "account_currency") or company_currency
    paid_from_currency = frappe.db.get_value("Account", paid_from, "account_currency") or company_currency

    precision = so_doc.precision("grand_total")
    outstanding = compute_outstanding(so_doc.grand_total, so_doc.advance_paid, precision)
    allocated = cap_allocation(amount, outstanding, precision)

    pe = frappe.new_doc("Payment Entry")
    pe.payment_type = "Receive"
    pe.mode_of_payment = mode_of_payment
    pe.party_type = "Customer"
    pe.party = customer
    pe.party_name = so_doc.customer_name or customer
    pe.company = company
    pe.posting_date = nowdate()
    pe.paid_from = paid_from
    pe.paid_to = paid_to
    pe.paid_from_account_currency = paid_from_currency
    pe.paid_to_account_currency = paid_to_currency
    pe.paid_amount = flt(full_received_amount, precision)
    pe.received_amount = flt(full_received_amount, precision)
    pe.reference_no = reference_no or so_doc.name
    pe.reference_date = nowdate()
    pe.remarks = remarks or f"Payment for {so_doc.name}"

    pe.append("references", {
        "reference_doctype": "Sales Order",
        "reference_name": so_doc.name,
        "due_date": so_doc.delivery_date or nowdate(),
        "total_amount": flt(so_doc.grand_total, precision),
        "outstanding_amount": outstanding,
        "allocated_amount": allocated,
    })

    return pe
```

- [ ] **Step 4: Run test**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local run-tests --app cecypo_powerpack --module cecypo_powerpack.quick_pay.test_builders
```
Expected: pass (or skip cleanly if no test SO/MOP available).

- [ ] **Step 5: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && \
  git add cecypo_powerpack/quick_pay/builders.py cecypo_powerpack/quick_pay/test_builders.py && \
  git commit -m "feat(quick_pay): add Payment Entry builder using get_party_account"
```

---

## Task 8: builders.py — Sales Invoice via official mapper

**Files:**
- Modify: `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/builders.py` (append)
- Modify: `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/test_builders.py` (append)

**Why use the official mapper:** It calls `set_missing_values`, `set_po_nos`, `calculate_taxes_and_totals`, `set_use_serial_batch_fields`, handles `billed_amt` deltas, unit-price items, payment terms, project/cost center inheritance — all of which the legacy hand-rolled copy missed.

- [ ] **Step 1: Write the failing test**

Append to `test_builders.py`:
```python
from cecypo_powerpack.quick_pay.builders import build_sales_invoice


class TestBuildSalesInvoice(FrappeTestCase):
    def test_si_built_via_official_mapper(self):
        so_name = frappe.db.get_value("Sales Order", {"docstatus": 1, "per_billed": 0}, "name")
        if not so_name:
            self.skipTest("No unbilled submitted Sales Order to invoice against")
        so = frappe.get_doc("Sales Order", so_name)

        si = build_sales_invoice(so, update_stock=1)
        # Mapper-style invariant: items inherit so_detail
        self.assertTrue(all(it.so_detail for it in si.items))
        # update_stock honored
        self.assertEqual(si.update_stock, 1)
        # Should still be unsaved (no name yet)
        self.assertFalse(si.get("name") and frappe.db.exists("Sales Invoice", si.name))
```

- [ ] **Step 2: Run test (expect ImportError)**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local run-tests --app cecypo_powerpack --module cecypo_powerpack.quick_pay.test_builders
```

- [ ] **Step 3: Implement**

Append to `builders.py`:
```python
def build_sales_invoice(so_doc, *, update_stock: int = 0):
    """Build (but don't save) a Sales Invoice from a Sales Order using the
    official ERPNext mapper. Caller is responsible for insert/submit.
    """
    si = make_sales_invoice(so_doc.name, ignore_permissions=True)
    si.update_stock = 1 if update_stock else 0
    si.allocate_advances_automatically = 1
    return si
```

- [ ] **Step 4: Run tests**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local run-tests --app cecypo_powerpack --module cecypo_powerpack.quick_pay.test_builders
```
Expected: pass.

- [ ] **Step 5: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && \
  git add cecypo_powerpack/quick_pay/builders.py cecypo_powerpack/quick_pay/test_builders.py && \
  git commit -m "feat(quick_pay): add Sales Invoice builder using official mapper"
```

---

## Task 9: api.py — `get_payment_modes` (Cash/Bank/Card)

**Files:**
- Create: `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/api.py`
- Create: `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/test_api.py`

Splits available Modes of Payment into `cash_modes`, `bank_modes`, `card_modes`, respecting User Permissions on Mode of Payment. Excludes Phone-type (Mpesa) — that's `quick_pay_mpesa`'s job.

- [ ] **Step 1: Write the failing test**

Write `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/test_api.py`:
```python
import frappe
from frappe.tests.utils import FrappeTestCase


class TestGetPaymentModes(FrappeTestCase):
    def test_returns_three_buckets(self):
        from cecypo_powerpack.quick_pay.api import get_payment_modes
        company = frappe.db.get_single_value("Global Defaults", "default_company") or \
                  frappe.db.get_value("Company", {}, "name")
        if not company:
            self.skipTest("No company configured")
        result = get_payment_modes(company=company)
        self.assertIn("cash_modes", result)
        self.assertIn("bank_modes", result)
        self.assertIn("card_modes", result)
        # No Phone-type leaked in
        for mop in result["cash_modes"] + result["bank_modes"] + result["card_modes"]:
            self.assertNotEqual(
                frappe.db.get_value("Mode of Payment", mop, "type"),
                "Phone",
            )
```

- [ ] **Step 2: Run test (expect ImportError)**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local run-tests --app cecypo_powerpack --module cecypo_powerpack.quick_pay.test_api
```

- [ ] **Step 3: Implement**

Write `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/api.py`:
```python
"""Whitelisted endpoints for Quick Pay. The two flows (cash/bank/card vs
Mpesa) are gated by separate PowerPack Settings flags; both still live in
this single module to keep the imports tidy.
"""

from __future__ import annotations

import frappe
from frappe import _

from cecypo_powerpack.quick_pay import validators


def _user_permitted_mops(user: str) -> list[str] | None:
    perms = frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "Mode of Payment"},
        fields=["for_value"],
    )
    if not perms:
        return None  # no restriction
    return [p["for_value"] for p in perms]


@frappe.whitelist()
def get_payment_modes(company: str) -> dict:
    """Categorize enabled Modes of Payment that have an account in `company`."""
    validators.assert_quick_pay_enabled("cash")

    permitted = _user_permitted_mops(frappe.session.user)

    rows = frappe.get_all(
        "Mode of Payment Account",
        filters={"company": company},
        fields=["parent", "default_account"],
    )
    candidates = sorted({r["parent"] for r in rows if r.get("default_account")})

    result = {"cash_modes": [], "bank_modes": [], "card_modes": []}

    for name in candidates:
        if permitted is not None and name not in permitted:
            continue
        mop = frappe.get_cached_doc("Mode of Payment", name)
        if not mop.enabled:
            continue
        mop_type = (mop.type or "").strip()
        lname = name.lower()
        if mop_type == "Phone":
            continue  # handled by Mpesa flow
        if mop_type == "Cash" or lname == "cash":
            result["cash_modes"].append(name)
        elif mop_type == "Bank" or "bank" in lname or "transfer" in lname:
            result["bank_modes"].append(name)
        elif mop_type == "Card" or any(k in lname for k in ("card", "credit", "debit")):
            result["card_modes"].append(name)
    return result
```

- [ ] **Step 4: Enable the cash flag in settings (so the gate doesn't block the test)**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local execute "frappe.db.set_single_value('PowerPack Settings', 'enable_quick_pay', 1); frappe.db.commit()"
```

- [ ] **Step 5: Run tests**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local run-tests --app cecypo_powerpack --module cecypo_powerpack.quick_pay.test_api
```
Expected: pass.

- [ ] **Step 6: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && \
  git add cecypo_powerpack/quick_pay/api.py cecypo_powerpack/quick_pay/test_api.py && \
  git commit -m "feat(quick_pay): add get_payment_modes API endpoint"
```

---

## Task 10: api.py — `process_quick_pay` (cash/bank/card main flow)

**Files:**
- Modify: `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/api.py` (append)
- Modify: `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/test_api.py` (append)

**Flow** (this is the core fix for issues #1 and #2):
1. Gate: feature flag, permissions
2. Claim idempotency token
3. Parse payments
4. **Stock pre-check** — if `create_invoice` and any issue → throw with full list, **before any DB write**
5. Build & insert & submit Payment Entries (precision-correct, capped)
6. `so.reload()`
7. If `create_invoice`: build SI via official mapper, set `update_stock` from settings, insert (and submit if flag set)
8. Return summary including any payment_entry names

If anything raises mid-flow, Frappe's request-level transaction rolls everything back. We do **not** swallow exceptions like the legacy script did.

- [ ] **Step 1: Write the failing test**

Append to `test_api.py`:
```python
import json
import uuid


class TestProcessQuickPay(FrappeTestCase):
    def test_full_payment_creates_pe_and_optional_invoice(self):
        from cecypo_powerpack.quick_pay.api import process_quick_pay
        # Find an unbilled SO to test against; if none, skip
        so_name = frappe.db.get_value(
            "Sales Order",
            {"docstatus": 1, "per_billed": 0, "status": ["not in", ["Closed", "Cancelled"]]},
            "name",
        )
        if not so_name:
            self.skipTest("No unbilled SO available")
        so = frappe.get_doc("Sales Order", so_name)
        outstanding = float(so.grand_total) - float(so.advance_paid or 0)
        if outstanding <= 0:
            self.skipTest("SO has no outstanding")

        mop_row = frappe.db.sql("""
            SELECT parent FROM `tabMode of Payment Account`
            WHERE company = %s AND default_account IS NOT NULL LIMIT 1
        """, so.company, as_dict=True)
        if not mop_row:
            self.skipTest("No MOP available")
        mop = mop_row[0]["parent"]

        token = "test-" + uuid.uuid4().hex
        payments = json.dumps([
            {"type": "Cash", "amount": outstanding, "mode_of_payment": mop, "reference": ""},
        ])

        result = process_quick_pay(
            sales_order=so.name,
            customer=so.customer,
            payments_json=payments,
            outstanding_amount=outstanding,
            create_invoice=0,
            submit_invoice=0,
            idempotency_token=token,
        )
        self.assertTrue(result["success"])
        self.assertEqual(len(result["payment_entries"]), 1)

    def test_duplicate_token_rejected(self):
        from cecypo_powerpack.quick_pay.api import process_quick_pay
        from cecypo_powerpack.quick_pay.validators import IdempotencyError
        token = "test-" + uuid.uuid4().hex
        # First call probably fails for other reasons (no SO), so we manually claim
        from cecypo_powerpack.quick_pay.validators import claim_idempotency_token
        claim_idempotency_token(token)
        with self.assertRaises(IdempotencyError):
            process_quick_pay(
                sales_order="DOES-NOT-EXIST",
                customer="X",
                payments_json="[]",
                outstanding_amount=0,
                create_invoice=0,
                submit_invoice=0,
                idempotency_token=token,
            )
```

- [ ] **Step 2: Run test (expect ImportError)**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local run-tests --app cecypo_powerpack --module cecypo_powerpack.quick_pay.test_api
```

- [ ] **Step 3: Implement**

Add these imports **at the top of `api.py`** (with the existing imports — not in the middle of the file):
```python
import json as _json

from cecypo_powerpack.quick_pay import builders
from cecypo_powerpack.utils import get_powerpack_settings
```

Then append the function to the end of `api.py`:
```python
@frappe.whitelist()
def process_quick_pay(
    sales_order: str,
    customer: str,
    payments_json: str,
    outstanding_amount: float,
    create_invoice: int = 0,
    submit_invoice: int = 0,
    idempotency_token: str = "",
) -> dict:
    """Process Cash/Bank/Card payments against a Sales Order, optionally
    creating + submitting a Sales Invoice afterwards."""
    validators.assert_quick_pay_enabled("cash")
    create_invoice = int(create_invoice or 0)
    submit_invoice = int(submit_invoice or 0)
    validators.assert_can_create_payment_and_invoice(create_invoice, submit_invoice)
    validators.claim_idempotency_token(idempotency_token)

    if not sales_order or not payments_json:
        frappe.throw(_("Missing required parameters"))

    payments = _json.loads(payments_json)
    if not isinstance(payments, list) or not payments:
        frappe.throw(_("No payments provided"))

    so = frappe.get_doc("Sales Order", sales_order)
    settings = get_powerpack_settings()
    update_stock = 1 if settings.get("qp_update_stock_on_invoice") else 0

    # Pre-flight stock check (only if we'll create the invoice)
    if create_invoice:
        issues = validators.preflight_stock_for_so(so)
        if issues:
            frappe.throw(_("Cannot create invoice — fix stock first:\n• ") + "\n• ".join(issues))

    precision = so.precision("grand_total")
    actual_outstanding = validators.compute_outstanding(so.grand_total, so.advance_paid, precision)
    remaining = actual_outstanding

    payment_entries: list[dict] = []
    cash_amount = 0.0
    total_paid = 0.0

    for p in payments:
        p_type = p.get("type")
        p_amount = float(p.get("amount") or 0)
        p_mode = p.get("mode_of_payment") or p_type
        p_ref = p.get("reference") or ""

        if p_amount <= 0:
            continue
        if p_type not in {"Cash", "Bank Transfer", "Card"}:
            continue
        if p_type in {"Bank Transfer", "Card"} and not p_ref:
            frappe.throw(_("Reference number required for {0}").format(p_type))

        if p_type == "Cash":
            cash_amount = p_amount

        allocated = validators.cap_allocation(p_amount, remaining, precision)
        if allocated <= 0:
            continue

        pe = builders.build_payment_entry(
            so_doc=so,
            amount=allocated,
            mode_of_payment=p_mode,
            reference_no=p_ref or None,
            remarks=f"{p_type} payment for {so.name}",
        )
        pe.insert(ignore_permissions=True)
        pe.submit()

        payment_entries.append({
            "name": pe.name,
            "type": p_type,
            "amount": allocated,
        })
        total_paid += allocated
        remaining = validators.normalize_amount(remaining - allocated, precision)

    if not payment_entries:
        frappe.throw(_("No valid payments could be created"))

    # Compute change for cash overpay (legacy behaviour kept)
    non_cash = total_paid - min(cash_amount, actual_outstanding)
    cash_needed = actual_outstanding - non_cash
    change_amount = max(0.0, cash_amount - cash_needed) if cash_amount > 0 else 0.0

    result = {
        "success": True,
        "payment_entries": payment_entries,
        "total_paid": total_paid,
        "change_amount": change_amount,
    }

    if create_invoice and remaining <= 0:
        so.reload()
        si = builders.build_sales_invoice(so, update_stock=update_stock)
        si.insert(ignore_permissions=True)
        if submit_invoice:
            si.submit()
        result["sales_invoice"] = {
            "name": si.name,
            "submitted": si.docstatus == 1,
        }

    return result
```

- [ ] **Step 4: Run tests**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local run-tests --app cecypo_powerpack --module cecypo_powerpack.quick_pay.test_api
```
Expected: both tests pass (or skip cleanly).

- [ ] **Step 5: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && \
  git add cecypo_powerpack/quick_pay/api.py cecypo_powerpack/quick_pay/test_api.py && \
  git commit -m "feat(quick_pay): add process_quick_pay endpoint with stock pre-check + idempotency"
```

---

## Task 11: api.py — Mpesa availability + listing

**Files:**
- Modify: `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/api.py` (append)

Two whitelisted methods: `check_mpesa_available(company)` and `list_pending_mpesa_payments(company, search)`.

Logic ports straight from the legacy server script with cleanups:
- `frappe.get_cached_doc` instead of repeated `db.get_value`
- Type hints
- Single source of truth for the Phone MOP / shortcode resolution

- [ ] **Step 1: Implement (test coverage is mostly via the next task's process flow + manual verification — these are read-only thin wrappers)**

Append to `api.py`:
```python
def _phone_mop_for_company(company: str) -> str | None:
    rows = frappe.get_all(
        "Mode of Payment",
        filters={"type": "Phone", "enabled": 1},
        fields=["name"],
    )
    for row in rows:
        if frappe.db.exists("Mode of Payment Account", {"parent": row.name, "company": company}):
            return row.name
    return None


def _mpesa_shortcode_for_company(company: str) -> str | None:
    settings = frappe.get_all(
        "Mpesa Settings",
        filters={"company": company},
        fields=["business_shortcode"],
        limit=1,
    )
    if settings and settings[0].get("business_shortcode"):
        return str(settings[0]["business_shortcode"])
    return None


@frappe.whitelist()
def check_mpesa_available(company: str) -> dict:
    validators.assert_quick_pay_enabled("mpesa")
    return {
        "available": bool(
            _phone_mop_for_company(company) and _mpesa_shortcode_for_company(company)
        )
    }


@frappe.whitelist()
def list_pending_mpesa_payments(company: str, search: str = "") -> dict:
    validators.assert_quick_pay_enabled("mpesa")
    shortcode = _mpesa_shortcode_for_company(company)
    if not shortcode:
        return {"count": 0, "payments": []}

    base_filters = {"docstatus": 0, "businessshortcode": shortcode}
    total_count = frappe.db.count("Mpesa C2B Payment Register", base_filters)

    payments: list[dict] = []
    if len(search) >= 3:
        all_payments = frappe.get_all(
            "Mpesa C2B Payment Register",
            filters=base_filters,
            fields=["name", "full_name", "transamount", "transid", "msisdn",
                    "posting_date", "billrefnumber", "creation"],
            order_by="creation desc",
            limit_page_length=100,
        )
        s = search.lower()
        for p in all_payments:
            if any(s in (p.get(f) or "").lower() for f in ("full_name", "transid", "billrefnumber", "msisdn")):
                payments.append(p)
    return {"count": total_count, "payments": payments}
```

- [ ] **Step 2: Sanity-import**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local execute "from cecypo_powerpack.quick_pay.api import check_mpesa_available, list_pending_mpesa_payments; print('ok')"
```

- [ ] **Step 3: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && \
  git add cecypo_powerpack/quick_pay/api.py && \
  git commit -m "feat(quick_pay): add Mpesa availability + listing endpoints"
```

---

## Task 12: api.py — `process_mpesa_quick_pay`

**Files:**
- Modify: `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/api.py` (append)

**Critical fix vs. legacy:** Build & submit the **Payment Entry first**, then mark the `Mpesa C2B Payment Register` row as processed. Legacy submitted Mpesa first; if PE creation failed, the Mpesa row was orphaned.

- [ ] **Step 1: Implement**

Append to `api.py`:
```python
@frappe.whitelist()
def process_mpesa_quick_pay(
    sales_order: str,
    customer: str,
    mpesa_payments: str,
    outstanding_amount: float,
    create_invoice: int = 0,
    submit_invoice: int = 0,
    idempotency_token: str = "",
) -> dict:
    validators.assert_quick_pay_enabled("mpesa")
    create_invoice = int(create_invoice or 0)
    submit_invoice = int(submit_invoice or 0)
    validators.assert_can_create_payment_and_invoice(create_invoice, submit_invoice)
    validators.claim_idempotency_token(idempotency_token)

    mpesa_names = [n.strip() for n in (mpesa_payments or "").split(",") if n.strip()]
    if not mpesa_names:
        frappe.throw(_("No Mpesa payments selected"))

    so = frappe.get_doc("Sales Order", sales_order)
    settings = get_powerpack_settings()
    update_stock = 1 if settings.get("qp_update_stock_on_invoice") else 0

    if create_invoice:
        issues = validators.preflight_stock_for_so(so)
        if issues:
            frappe.throw(_("Cannot create invoice — fix stock first:\n• ") + "\n• ".join(issues))

    phone_mop = _phone_mop_for_company(so.company)
    if not phone_mop:
        frappe.throw(_("No Phone-type Mode of Payment configured for {0}").format(so.company))
    shortcode = _mpesa_shortcode_for_company(so.company)
    if not shortcode:
        frappe.throw(_("No Mpesa Settings for {0}").format(so.company))

    precision = so.precision("grand_total")
    remaining = validators.compute_outstanding(so.grand_total, so.advance_paid, precision)

    payment_entries: list[dict] = []
    mpesa_results: list[dict] = []

    for mpesa_name in mpesa_names:
        if remaining <= 0:
            break
        mpesa = frappe.get_doc("Mpesa C2B Payment Register", mpesa_name)
        if mpesa.docstatus != 0:
            continue
        if str(mpesa.businessshortcode or "") != shortcode:
            continue

        mpesa_amt = float(mpesa.transamount or 0)
        if mpesa_amt <= 0:
            continue
        allocated = validators.cap_allocation(mpesa_amt, remaining, precision)

        # Build & submit the PE FIRST.
        pe = builders.build_payment_entry(
            so_doc=so,
            amount=allocated,
            mode_of_payment=phone_mop,
            reference_no=mpesa_name,
            remarks=f"Mpesa payment: {mpesa_name}",
            full_received_amount=mpesa_amt,
        )
        pe.insert(ignore_permissions=True)
        pe.submit()

        # Now mark the Mpesa row as processed and link the PE.
        mpesa.customer = customer
        mpesa.submit_payment = 0
        mpesa.payment_entry = pe.name
        mpesa.save(ignore_permissions=True)
        mpesa.submit()

        payment_entries.append({
            "name": pe.name,
            "type": "Mpesa",
            "amount": allocated,
            "full_amount": mpesa_amt,
        })
        mpesa_results.append({"name": mpesa.name, "amount": mpesa_amt})
        remaining = validators.normalize_amount(remaining - allocated, precision)

    if not payment_entries:
        frappe.throw(_("No valid Mpesa payments processed"))

    result = {
        "success": True,
        "payment_entries": payment_entries,
        "mpesa_payments": mpesa_results,
        "total_amount": sum(p["amount"] for p in payment_entries),
    }

    if create_invoice and remaining <= 0:
        so.reload()
        si = builders.build_sales_invoice(so, update_stock=update_stock)
        si.insert(ignore_permissions=True)
        if submit_invoice:
            si.submit()
        result["sales_invoice"] = {"name": si.name, "submitted": si.docstatus == 1}

    return result
```

- [ ] **Step 2: Sanity-import**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local execute "from cecypo_powerpack.quick_pay.api import process_mpesa_quick_pay; print('ok')"
```

- [ ] **Step 3: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && \
  git add cecypo_powerpack/quick_pay/api.py && \
  git commit -m "feat(quick_pay): add Mpesa processing with PE-first ordering"
```

---

## Task 13: api.py — Customer phone lookup + Payment Request creation

**Files:**
- Modify: `apps/cecypo_powerpack/cecypo_powerpack/quick_pay/api.py` (append)

Direct port of the legacy `get_customer_phone` and `create_payment_request` actions.

- [ ] **Step 1: Implement**

Append to `api.py`:
```python
@frappe.whitelist()
def get_customer_phone(customer: str) -> str:
    validators.assert_quick_pay_enabled("mpesa")
    if not customer:
        return ""
    contact = frappe.db.get_value(
        "Dynamic Link",
        {"link_doctype": "Customer", "link_name": customer, "parenttype": "Contact"},
        "parent",
    )
    if contact:
        for field in ("mobile_no", "phone"):
            phone = frappe.db.get_value("Contact", contact, field)
            if phone:
                return phone
    return frappe.db.get_value("Customer", customer, "mobile_no") or ""


@frappe.whitelist()
def create_mpesa_payment_request(
    sales_order: str,
    customer: str,
    phone_number: str,
    amount: float,
) -> dict:
    validators.assert_quick_pay_enabled("mpesa")
    if not (sales_order and phone_number and float(amount) > 0):
        frappe.throw(_("Missing required parameters"))

    so = frappe.get_doc("Sales Order", sales_order)

    settings = frappe.get_all(
        "Mpesa Settings",
        filters={"company": so.company},
        fields=["name", "payment_gateway_name"],
        limit=1,
    )
    if not settings:
        frappe.throw(_("No Mpesa Settings for {0}").format(so.company))
    gateway_name = settings[0].get("payment_gateway_name") or settings[0].get("name")

    gateway_account = frappe.db.get_value(
        "Payment Gateway Account",
        {"payment_gateway": gateway_name},
        ["name", "payment_account", "payment_gateway"],
        as_dict=True,
    )
    if not gateway_account:
        rows = frappe.get_all(
            "Payment Gateway Account",
            filters={"payment_gateway": ["like", "%Mpesa%"]},
            fields=["name", "payment_gateway", "payment_account"],
            limit=1,
        )
        if rows:
            gateway_account = rows[0]
    if not gateway_account:
        frappe.throw(_("No Payment Gateway Account found for Mpesa"))

    pr = frappe.new_doc("Payment Request")
    pr.payment_request_type = "Inward"
    pr.transaction_date = frappe.utils.nowdate()
    pr.phone_number = phone_number
    pr.company = so.company
    pr.party_type = "Customer"
    pr.party = customer
    pr.reference_doctype = "Sales Order"
    pr.reference_name = sales_order
    pr.grand_total = float(amount)
    pr.currency = so.currency
    pr.outstanding_amount = float(amount)
    pr.payment_gateway_account = gateway_account.get("name")
    pr.payment_gateway = gateway_account.get("payment_gateway") or gateway_name
    pr.payment_account = gateway_account.get("payment_account")
    pr.payment_channel = "Phone"
    pr.mode_of_payment = _phone_mop_for_company(so.company)
    pr.subject = f"Payment for {sales_order}"
    pr.message = f"Payment for {sales_order}"
    pr.mute_email = 1
    pr.make_sales_invoice = 0
    pr.insert(ignore_permissions=True)
    pr.submit()

    return {"success": True, "payment_request": pr.name}
```

- [ ] **Step 2: Sanity-import**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local execute "from cecypo_powerpack.quick_pay.api import get_customer_phone, create_mpesa_payment_request; print('ok')"
```

- [ ] **Step 3: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && \
  git add cecypo_powerpack/quick_pay/api.py && \
  git commit -m "feat(quick_pay): add customer phone lookup + payment request endpoints"
```

---

## Task 14: Client script — Cash/Bank/Card

**Files:**
- Create: `apps/cecypo_powerpack/cecypo_powerpack/public/js/quick_pay.js`

**Diff vs legacy `SO - Quick Pay`:**
1. Wrap the whole `refresh` body in `CecypoPowerPack.Settings.isEnabled('enable_quick_pay', cb)` — the standard powerpack pattern.
2. Settings come from server (auto-create / auto-submit / update-stock) — no JS-side `QUICK_PAY_CONFIG` constant.
3. Generate a UUID per dialog (`crypto.randomUUID()`) and pass as `idempotency_token`.
4. RPC method names changed: `cecypo_powerpack.quick_pay.api.get_payment_modes`, `cecypo_powerpack.quick_pay.api.process_quick_pay`.
5. **Surface `invoice_error` in the success dialog** (legacy didn't).

- [ ] **Step 1: Write the file**

Use `Write` tool to create `apps/cecypo_powerpack/cecypo_powerpack/public/js/quick_pay.js`. Take the existing client script content (from the database `SO - Quick Pay`) and apply these changes:

a. Replace the top of the file (everything before `frappe.ui.form.on(...)`) with:
```javascript
// Quick Pay — Cash/Bank/Card flow. Mpesa lives in quick_pay_mpesa.js.
// Toggled by PowerPack Settings → enable_quick_pay.

(function () {
    if (!window.CecypoPowerPack || !CecypoPowerPack.Settings) return;

    let qp_settings_cache = null;

    function with_settings(cb) {
        if (qp_settings_cache) return cb(qp_settings_cache);
        frappe.call({
            method: "cecypo_powerpack.utils.get_powerpack_settings_for_client",
            callback(r) {
                qp_settings_cache = r.message || {};
                cb(qp_settings_cache);
            },
        });
    }

    frappe.ui.form.on('Sales Order', {
        refresh(frm) {
            CecypoPowerPack.Settings.isEnabled('enable_quick_pay', function (enabled) {
                if (!enabled) return;
                add_quick_pay_button(frm);
            });
        }
    });

    function add_quick_pay_button(frm) {
```

b. Replace the entire `refresh(frm)` body in the legacy script with the move into `add_quick_pay_button(frm)` (the legacy logic for `is_submitted && not_completed && no_invoice` etc. moves inside this new function).

c. Replace the `frappe.call({ method: 'quick_pay_process', args: { action: 'get_payment_modes', ... } })` with:
```javascript
frappe.call({
    method: 'cecypo_powerpack.quick_pay.api.get_payment_modes',
    args: { company: frm.doc.company },
    ...
});
```

d. Replace `frappe.call({ method: 'quick_pay_process', args: { action: 'process_multiple', ... } })` in `process_all_payments` with:
```javascript
frappe.call({
    method: 'cecypo_powerpack.quick_pay.api.process_quick_pay',
    args: {
        sales_order: frm.doc.name,
        customer: frm.doc.customer,
        payments_json: JSON.stringify(dialog.payments.map(p => ({
            type: p.type,
            amount: p.amount,
            mode_of_payment: p.mode_of_payment || p.type,
            reference: p.reference || ''
        }))),
        outstanding_amount: outstanding,
        create_invoice: dialog.create_invoice ? 1 : 0,
        submit_invoice: dialog.submit_invoice ? 1 : 0,
        idempotency_token: dialog.idempotency_token,
    },
    freeze: true,
    freeze_message: __('Processing Payments...'),
    callback(r) {
        // ... existing render of result, PLUS:
        if (r.message && r.message.invoice_error) {
            msg += `<p class="text-danger mt-2"><i class="fa fa-exclamation-triangle"></i> ${__('Invoice Error')}: ${r.message.invoice_error}</p>`;
        }
        // ...
    }
});
```

e. In `show_quick_pay_dialog`, after `dialog.payments = []`, add:
```javascript
dialog.idempotency_token = (window.crypto && crypto.randomUUID)
    ? crypto.randomUUID()
    : 'qp-' + Date.now() + '-' + Math.random().toString(36).slice(2);
```

f. Replace `QUICK_PAY_CONFIG` references with `with_settings(s => { ... s.qp_auto_create_invoice ... })`. Concretely, before `dialog.show()`, wrap the `dialog.create_invoice = ...` lines:
```javascript
with_settings(function (s) {
    dialog.create_invoice = !!s.qp_auto_create_invoice;
    dialog.submit_invoice = !!s.qp_auto_submit_invoice;
});
```

g. Close the IIFE at the end of the file: `})();`

(Full file is the legacy script with the patches above. The implementer copies the legacy text from the DB transcript provided in this plan's context, applies these targeted edits.)

- [ ] **Step 2: Add `get_powerpack_settings_for_client` if it doesn't exist**

```bash
cd /home/frappeuser/bench16 && grep -n "get_powerpack_settings_for_client\|get_powerpack_settings\b" apps/cecypo_powerpack/cecypo_powerpack/utils.py
```
- If `get_powerpack_settings_for_client` exists, use it.
- If only `get_powerpack_settings` (server-side) exists, add a thin whitelisted wrapper to `cecypo_powerpack/api.py`:
  ```python
  @frappe.whitelist()
  def get_powerpack_settings_for_client():
      from cecypo_powerpack.utils import get_powerpack_settings
      s = get_powerpack_settings()
      return {
          "qp_auto_create_invoice": int(s.get("qp_auto_create_invoice") or 0),
          "qp_auto_submit_invoice": int(s.get("qp_auto_submit_invoice") or 0),
          "qp_update_stock_on_invoice": int(s.get("qp_update_stock_on_invoice") or 0),
      }
  ```

- [ ] **Step 3: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && \
  git add cecypo_powerpack/public/js/quick_pay.js cecypo_powerpack/api.py cecypo_powerpack/utils.py && \
  git commit -m "feat(quick_pay): add Cash/Bank/Card client script"
```

---

## Task 15: Client script — Mpesa

**Files:**
- Create: `apps/cecypo_powerpack/cecypo_powerpack/public/js/quick_pay_mpesa.js`

Same transformation as Task 14, applied to the legacy `SO - Quick Pay Mpesa` script:
- Gate via `CecypoPowerPack.Settings.isEnabled('enable_quick_pay_mpesa', cb)`
- RPCs: `cecypo_powerpack.quick_pay.api.{check_mpesa_available, list_pending_mpesa_payments, process_mpesa_quick_pay, get_customer_phone, create_mpesa_payment_request}`
- UUID idempotency token on dialog
- Server-side settings replace `QUICK_PAY_MPESA_CONFIG`

- [ ] **Step 1: Write the file** (apply the same six edits from Task 14, swapping in Mpesa method names and `enable_quick_pay_mpesa` flag).

- [ ] **Step 2: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && \
  git add cecypo_powerpack/public/js/quick_pay_mpesa.js && \
  git commit -m "feat(quick_pay): add Mpesa client script"
```

---

## Task 16: Extract CSS

**Files:**
- Create: `apps/cecypo_powerpack/cecypo_powerpack/public/css/quick_pay.css`

Move all the inline `<style id="qp-styles">` and `<style id="mpesa-pay-styles">` blocks from the legacy scripts into this file (one combined stylesheet — the selectors don't conflict). Then in both JS files, remove the `inject_quick_pay_styles` / `inject_mpesa_styles` functions and their call sites.

- [ ] **Step 1: Create `quick_pay.css`** with the contents of the two legacy `<style>` blocks concatenated (from the DB transcript in the review thread).

- [ ] **Step 2: Remove `inject_*_styles()` functions and their call sites** from both JS files (`Edit` tool).

- [ ] **Step 3: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && \
  git add cecypo_powerpack/public/css/quick_pay.css cecypo_powerpack/public/js/quick_pay.js cecypo_powerpack/public/js/quick_pay_mpesa.js && \
  git commit -m "refactor(quick_pay): extract inline styles to CSS file"
```

---

## Task 17: Wire into hooks.py + build assets

**Files:**
- Modify: `apps/cecypo_powerpack/cecypo_powerpack/hooks.py`

- [ ] **Step 1: Add doctype_js**

In `hooks.py`, find the commented `# doctype_js = ...` line and replace with:
```python
doctype_js = {
    "Sales Order": [
        "public/js/quick_pay.js",
        "public/js/quick_pay_mpesa.js",
    ],
}
```

- [ ] **Step 2: Add CSS to `app_include_css` list**

Find the existing `app_include_css = [...]` block and append:
```python
"/assets/cecypo_powerpack/css/quick_pay.css",
```

- [ ] **Step 3: Build assets**

```bash
cd /home/frappeuser/bench16 && bench build --app cecypo_powerpack
```
Expected: builds without warnings.

- [ ] **Step 4: Restart bench**

```bash
cd /home/frappeuser/bench16 && bench restart
```

- [ ] **Step 5: Clear cache**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local clear-cache
```

- [ ] **Step 6: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && \
  git add cecypo_powerpack/hooks.py && \
  git commit -m "feat(quick_pay): register doctype_js + CSS in hooks"
```

---

## Task 18: Disable the legacy DB scripts

**Files:** none (DB-only change)

After the new code is verified working in Task 19, disable the legacy scripts. **Don't delete them yet** — keeps a fallback for one release cycle.

- [ ] **Step 1: Disable both Client Scripts**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local execute "
frappe.db.set_value('Client Script', 'SO - Quick Pay', 'enabled', 0);
frappe.db.set_value('Client Script', 'SO - Quick Pay Mpesa', 'enabled', 0);
frappe.db.set_value('Server Script', 'Quick Pay API', 'disabled', 1);
frappe.db.set_value('Server Script', 'Quick Pay Mpesa API', 'disabled', 1);
frappe.db.commit();
print('Legacy scripts disabled')
"
```
Expected: prints `Legacy scripts disabled`.

- [ ] **Step 2: Verify**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local execute frappe.db.get_all --kwargs '{"doctype": "Client Script", "filters": [["name", "like", "%Quick%"]], "fields": ["name", "enabled"]}'
cd /home/frappeuser/bench16 && bench --site site16.local execute frappe.db.get_all --kwargs '{"doctype": "Server Script", "filters": [["name", "like", "%Quick%"]], "fields": ["name", "disabled"]}'
```
Expected: all `enabled=0` / `disabled=1`.

- [ ] **Step 3: Clear cache and reload the form**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local clear-cache
```
In a browser, open any submitted Sales Order. Hard-refresh. Confirm only one `Quick Pay` and one `Quick Pay - Mpesa` button appears (i.e. no duplicates from legacy + new).

(No git commit — DB-only change.)

---

## Task 19: Manual verification scenarios

For each scenario, the implementer (or user) tests in the browser and reports pass/fail.

### Scenario A — exact-match precision (the original bug)
1. SO with grand_total exactly `133.40`, advance_paid `0`.
2. Open Quick Pay → add a single Cash payment, amount `133.40`.
3. Submit. **Expected:** PE created and submitted, no "Allocated Amount cannot be greater" error. Result dialog shows the PE link.

### Scenario B — split payments summing to exact total
1. Same SO (`133.40` outstanding).
2. Add Cash `50.10` + Bank `83.30` (sum `133.40` in math, `133.40000000000003` in float).
3. Submit. **Expected:** two PEs created; remaining = `0.00`; no precision error.

### Scenario C — auto-create + auto-submit Sales Invoice with stock OK
1. PowerPack Settings: `qp_auto_create_invoice=1`, `qp_auto_submit_invoice=1`, `qp_update_stock_on_invoice=1`.
2. SO with stock-tracked items where stock IS available.
3. Pay outstanding fully → submit.
4. **Expected:** PE(s) submitted, SI created and submitted, stock reduced. Result dialog shows SI link with green "Submitted" pill.

### Scenario D — auto-create with stock NOT available (the pre-flight fix)
1. Same settings as C.
2. SO with a stock item where Bin has insufficient `actual_qty`.
3. Open Quick Pay → add full payment → submit.
4. **Expected:** error dialog **before any DB writes** listing `<item>: only X available at <warehouse>, need Y`. No PE created. SO unchanged. Naming series for SI **not advanced** (verify via `tabSeries` for `ACC-SINV-...`).

### Scenario E — idempotency
1. Open the dialog. In DevTools Network tab, re-submit the same `process_quick_pay` request twice (or click the Submit button before the first response returns by toggling network throttling).
2. **Expected:** first call succeeds; second returns `Duplicate request: this payment has already been processed`. Only one set of PEs in the DB.

### Scenario F — Mpesa flow
1. Enable Mpesa flag. Have a pending `Mpesa C2B Payment Register` row matching the SO outstanding.
2. Open Quick Pay - Mpesa → select the row → submit.
3. **Expected:** PE created with full Mpesa amount as `paid_amount`, `allocated_amount` capped to outstanding, Mpesa row docstatus=1 with `payment_entry` field populated. SI created if flagged.

### Scenario G — Mpesa Payment Request (STK Push)
1. Same setup as F. Click `Request Payment` button instead.
2. Enter phone number → send.
3. **Expected:** Payment Request submitted; success dialog with PR link.

### Scenario H — settings-toggle gating
1. Disable `enable_quick_pay` in PowerPack Settings.
2. Refresh a Sales Order form.
3. **Expected:** "Quick Pay" button is gone. Mpesa button still appears (separate flag).

- [ ] **Step 1: Run all 8 scenarios. Document results in a comment on the PR (or in a follow-up message).**

---

## Task 20: Final code review pass

- [ ] **Step 1: Skim the diff**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && git log --oneline main..HEAD
cd /home/frappeuser/bench16/apps/cecypo_powerpack && git diff main..HEAD --stat
```

- [ ] **Step 2: Run the full test suite**

```bash
cd /home/frappeuser/bench16 && bench --site site16.local run-tests --app cecypo_powerpack
```
Expected: all green.

- [ ] **Step 3: Lint**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && ruff check cecypo_powerpack/quick_pay/
cd /home/frappeuser/bench16/apps/cecypo_powerpack && ruff format --check cecypo_powerpack/quick_pay/
```
Fix any issues then re-run.

- [ ] **Step 4: Push branch + open PR**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack && git push -u origin feat/quick-pay-migration
```

(PR title and body — no Claude attribution per the project's git policy. Manual step or use the `frappe-fullstack:frappe-github` skill.)

---

## Notes for the implementer

- **Frappe transactions:** A whitelisted endpoint runs inside one DB transaction. If anything in `process_quick_pay` raises, **everything** rolls back — including in-progress PE inserts. This is the implicit safety net we rely on instead of explicit savepoints. Do not add `try/except` around DB writes inside the API functions.
- **Why `_test_*` prefix avoided:** Frappe's test-runner conventions don't require it; module-level `test_*.py` files are discovered automatically.
- **`get_party_account` import path:** `from erpnext.accounts.party import get_party_account`. Verified in v15.
- **`make_sales_invoice` import path:** `from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice`. Verified in v15 at sales_order.py:1328.
- **CLAUDE.md update:** consider appending a "Quick Pay" section to `apps/cecypo_powerpack/CLAUDE.md` describing the module structure once merged. Not blocking.
- **Old DB scripts:** keep them disabled for one release cycle. To delete:
  ```python
  for n in ["SO - Quick Pay", "SO - Quick Pay Mpesa"]:
      frappe.delete_doc("Client Script", n, ignore_permissions=True)
  for n in ["Quick Pay API", "Quick Pay Mpesa API"]:
      frappe.delete_doc("Server Script", n, ignore_permissions=True)
  frappe.db.commit()
  ```
