# Zero Allocate with Paste — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Zero Allocate with Paste" button to Payment Reconciliation that accepts a pasted `bill_no<TAB>amount` list, resolves bills to Purchase Invoices for the selected supplier/company, lets the user review/adjust amounts, then populates the `allocation` child table with correctly-shaped rows for the user to commit via the existing Zero Reconcile button.

**Architecture:** One new whitelisted endpoint `resolve_bill_numbers_for_credit` in `api.py` performs a single batched PI lookup and partitions results into matched / ambiguous / not_found. All UI lives in `payment_reconciliation_powerup.js` as IIFE-scoped helpers; the dialog builds inputs for the existing `zero_allocate_entries` endpoint and overlays user-edited amounts onto the returned allocation dicts before calling `frm.add_child('allocation', …)`. Existing Zero Allocate, Zero Reconcile, and `CustomPaymentReconciliation.zero_reconcile` paths are untouched.

**Tech Stack:** Frappe (Python 3.10, MariaDB, `frappe.qb`/`frappe.db`, `frappe.tests.utils.FrappeTestCase`), vanilla ES2017 JS with `frappe.ui.Dialog` / `frappe.call`, jQuery for DOM wiring.

**Reference spec:** `docs/superpowers/specs/2026-04-16-zero-allocate-with-paste-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `cecypo_powerpack/api.py` | Modify (append) | Add `resolve_bill_numbers_for_credit` whitelisted endpoint (matching logic + gates) |
| `cecypo_powerpack/custom_payment_reconciliation.py` | Modify | Add one-line comment above `_reconcile_without_validation` re: preforked-Gunicorn vs gevent monkey-patch |
| `cecypo_powerpack/public/js/payment_reconciliation_powerup.js` | Modify (append) | Add new section: `setup_zero_allocate_paste_button`, `zero_allocate_with_paste`, `parse_paste`, `render_review_section`, `run_auto_distribute`, `proceed_zero_allocate_paste`, plus wiring into `refresh` / `party_type` event chain |
| `cecypo_powerpack/tests/__init__.py` | Create | Empty package marker |
| `cecypo_powerpack/tests/test_zero_allocate_paste.py` | Create | Unit tests for `resolve_bill_numbers_for_credit` (10 cases from spec) |

No new DocTypes. No `hooks.py` changes. No fixtures. Feature is gated by existing `enable_payment_reconciliation_powerup`.

---

## Task 1: Server endpoint — scaffold + feature gate

**Files:**
- Create: `cecypo_powerpack/tests/__init__.py`
- Create: `cecypo_powerpack/tests/test_zero_allocate_paste.py`
- Modify: `cecypo_powerpack/api.py` (append at end)

- [ ] **Step 1.1: Create the tests package marker**

Create `cecypo_powerpack/tests/__init__.py` as an empty file:

```python
```

- [ ] **Step 1.2: Write the failing "feature disabled throws" test**

Create `cecypo_powerpack/tests/test_zero_allocate_paste.py`:

```python
# Copyright (c) 2026, Cecypo.Tech and Contributors
# See license.txt

import json

import frappe
from frappe.tests.utils import FrappeTestCase


class TestResolveBillNumbersForCredit(FrappeTestCase):
	"""Tests for cecypo_powerpack.api.resolve_bill_numbers_for_credit."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_value("Company", {}, "name") or frappe.get_all("Company", limit=1)[0].name
		cls.supplier_name = _ensure_supplier("_Test ZAP Supplier")

	def setUp(self):
		# Ensure feature on before each test; individual tests may toggle it
		settings = frappe.get_single("PowerPack Settings")
		settings.enable_payment_reconciliation_powerup = 1
		settings.save()

	def tearDown(self):
		frappe.db.rollback()

	def test_feature_disabled_throws(self):
		from cecypo_powerpack.api import resolve_bill_numbers_for_credit

		settings = frappe.get_single("PowerPack Settings")
		settings.enable_payment_reconciliation_powerup = 0
		settings.save()

		with self.assertRaises(frappe.ValidationError):
			resolve_bill_numbers_for_credit(
				company=self.company,
				supplier=self.supplier_name,
				bill_numbers=json.dumps(["BILL/ANY"]),
			)


def _ensure_supplier(name: str) -> str:
	if frappe.db.exists("Supplier", name):
		return name
	supplier = frappe.get_doc({
		"doctype": "Supplier",
		"supplier_name": name,
		"supplier_group": frappe.db.get_value("Supplier Group", {}, "name"),
	}).insert(ignore_permissions=True)
	return supplier.name
```

- [ ] **Step 1.3: Run the test — expect ImportError**

Run from `/home/frappeuser/bench16`:

```bash
bench --site site16.local run-tests --app cecypo_powerpack \
  --module cecypo_powerpack.tests.test_zero_allocate_paste
```

Expected: FAIL — `ImportError: cannot import name 'resolve_bill_numbers_for_credit' from 'cecypo_powerpack.api'`.

- [ ] **Step 1.4: Add the endpoint stub with the feature gate**

Append to `cecypo_powerpack/api.py` (below `get_invoice_exchange_map_for_zero_allocate`):

```python
@frappe.whitelist()
def resolve_bill_numbers_for_credit(company: str, supplier: str, bill_numbers: str) -> dict:
	"""
	Resolve pasted bill_no strings to open Purchase Invoices for a given supplier/company.

	Used by the "Zero Allocate with Paste" PowerUp in Payment Reconciliation.

	Args:
		company: Company to scope the query to.
		supplier: Supplier to scope the query to.
		bill_numbers: JSON-encoded list of bill_no strings.

	Returns:
		dict with keys:
			matched:   list of {bill_no, pi_name, outstanding_amount, currency,
			                    conversion_rate, posting_date}
			ambiguous: list of {bill_no, candidates: [{pi_name, posting_date,
			                    outstanding_amount}, ...]}
			not_found: list of bill_no strings
		Input order is preserved in all three partitions.
	"""
	import json as _json

	from cecypo_powerpack.utils import is_feature_enabled

	if not is_feature_enabled("enable_payment_reconciliation_powerup"):
		frappe.throw(_("Payment Reconciliation PowerUp is not enabled in PowerPack Settings"))

	if not frappe.has_permission("Purchase Invoice", "read"):
		frappe.throw(_("Not permitted to read Purchase Invoice"), frappe.PermissionError)

	# Input sanitation
	try:
		parsed = _json.loads(bill_numbers) if isinstance(bill_numbers, str) else bill_numbers
	except ValueError:
		frappe.throw(_("bill_numbers must be a JSON-encoded list of strings"))
	if not isinstance(parsed, list):
		frappe.throw(_("bill_numbers must be a JSON-encoded list of strings"))

	# Strip, drop blanks, uniquify preserving first-seen order
	seen = set()
	cleaned: list[str] = []
	for raw in parsed:
		if not isinstance(raw, str):
			continue
		s = raw.strip()
		if not s or s in seen:
			continue
		seen.add(s)
		cleaned.append(s)

	if len(cleaned) > 200:
		frappe.throw(_("Too many bill numbers in one paste (max 200)"))

	if not cleaned:
		return {"matched": [], "ambiguous": [], "not_found": []}

	rows = frappe.db.get_all(
		"Purchase Invoice",
		filters={
			"supplier": supplier,
			"company": company,
			"docstatus": 1,
			"outstanding_amount": [">", 0],
			"bill_no": ["in", cleaned],
		},
		fields=[
			"name", "bill_no", "outstanding_amount", "currency",
			"conversion_rate", "posting_date", "grand_total",
		],
	)

	# Group rows by bill_no
	by_bill: dict[str, list] = {}
	for r in rows:
		by_bill.setdefault(r["bill_no"], []).append(r)

	matched: list[dict] = []
	ambiguous: list[dict] = []
	not_found: list[str] = []

	for bill_no in cleaned:
		candidates = by_bill.get(bill_no, [])
		if len(candidates) == 1:
			c = candidates[0]
			matched.append({
				"bill_no": bill_no,
				"pi_name": c["name"],
				"outstanding_amount": c["outstanding_amount"],
				"currency": c["currency"],
				"conversion_rate": c["conversion_rate"],
				"posting_date": c["posting_date"],
			})
		elif len(candidates) > 1:
			ambiguous.append({
				"bill_no": bill_no,
				"candidates": [
					{
						"pi_name": c["name"],
						"posting_date": c["posting_date"],
						"outstanding_amount": c["outstanding_amount"],
					}
					for c in candidates
				],
			})
		else:
			not_found.append(bill_no)

	return {"matched": matched, "ambiguous": ambiguous, "not_found": not_found}
```

- [ ] **Step 1.5: Run the test — verify it passes**

```bash
bench --site site16.local run-tests --app cecypo_powerpack \
  --module cecypo_powerpack.tests.test_zero_allocate_paste
```

Expected: 1 test, PASS.

- [ ] **Step 1.6: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack
git add cecypo_powerpack/api.py cecypo_powerpack/tests/__init__.py cecypo_powerpack/tests/test_zero_allocate_paste.py
git commit -m "feat(payment-recon): scaffold resolve_bill_numbers_for_credit endpoint"
```

---

## Task 2: Server endpoint — matching, partitioning, and edge cases

**Files:**
- Modify: `cecypo_powerpack/tests/test_zero_allocate_paste.py`

All tests in this task exercise the endpoint added in Task 1. Use one shared fixture block via `setUpClass` that creates three Purchase Invoices with known `bill_no`s.

- [ ] **Step 2.1: Add PI fixture helpers and the clean-match test**

Replace the body of `test_zero_allocate_paste.py` with:

```python
# Copyright (c) 2026, Cecypo.Tech and Contributors
# See license.txt

import json

import frappe
from erpnext.stock.doctype.item.test_item import make_item
from frappe.tests.utils import FrappeTestCase


TEST_SUPPLIER = "_Test ZAP Supplier"
TEST_SUPPLIER_OTHER = "_Test ZAP Supplier Other"
TEST_ITEM = "_Test ZAP Item"


class TestResolveBillNumbersForCredit(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_value("Company", {"is_group": 0}, "name") \
			or frappe.get_all("Company", filters={"is_group": 0}, limit=1)[0].name
		cls.supplier = _ensure_supplier(TEST_SUPPLIER)
		cls.supplier_other = _ensure_supplier(TEST_SUPPLIER_OTHER)
		cls.item_code = make_item(TEST_ITEM, {"is_stock_item": 0}).name

	def setUp(self):
		settings = frappe.get_single("PowerPack Settings")
		settings.enable_payment_reconciliation_powerup = 1
		settings.save()

	def tearDown(self):
		frappe.db.rollback()

	# ── Feature gate ──────────────────────────────────────────────────────
	def test_feature_disabled_throws(self):
		from cecypo_powerpack.api import resolve_bill_numbers_for_credit

		settings = frappe.get_single("PowerPack Settings")
		settings.enable_payment_reconciliation_powerup = 0
		settings.save()

		with self.assertRaises(frappe.ValidationError):
			resolve_bill_numbers_for_credit(
				company=self.company,
				supplier=self.supplier,
				bill_numbers=json.dumps(["BILL/ANY"]),
			)

	# ── Clean single match ────────────────────────────────────────────────
	def test_single_clean_match(self):
		from cecypo_powerpack.api import resolve_bill_numbers_for_credit

		pi = _make_pi(self.company, self.supplier, self.item_code, "BILL/CLEAN/1", 1000)

		result = resolve_bill_numbers_for_credit(
			company=self.company,
			supplier=self.supplier,
			bill_numbers=json.dumps(["BILL/CLEAN/1"]),
		)

		self.assertEqual(len(result["matched"]), 1)
		self.assertEqual(result["ambiguous"], [])
		self.assertEqual(result["not_found"], [])
		m = result["matched"][0]
		self.assertEqual(m["bill_no"], "BILL/CLEAN/1")
		self.assertEqual(m["pi_name"], pi.name)
		self.assertAlmostEqual(float(m["outstanding_amount"]), 1000.0, places=2)
		for key in ("currency", "conversion_rate", "posting_date"):
			self.assertIn(key, m)


# ── helpers ───────────────────────────────────────────────────────────────

def _ensure_supplier(name: str) -> str:
	if frappe.db.exists("Supplier", name):
		return name
	sg = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name") \
		or frappe.get_all("Supplier Group", filters={"is_group": 0}, limit=1)[0].name
	doc = frappe.get_doc({
		"doctype": "Supplier",
		"supplier_name": name,
		"supplier_group": sg,
	}).insert(ignore_permissions=True)
	return doc.name


def _make_pi(company, supplier, item_code, bill_no, amount, docstatus=1):
	"""Create and submit a minimal Purchase Invoice."""
	warehouse = frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")
	pi = frappe.get_doc({
		"doctype": "Purchase Invoice",
		"company": company,
		"supplier": supplier,
		"bill_no": bill_no,
		"bill_date": frappe.utils.nowdate(),
		"posting_date": frappe.utils.nowdate(),
		"due_date": frappe.utils.add_days(frappe.utils.nowdate(), 30),
		"currency": frappe.get_cached_value("Company", company, "default_currency"),
		"items": [{
			"item_code": item_code,
			"qty": 1,
			"rate": amount,
			"warehouse": warehouse,
		}],
	})
	pi.insert(ignore_permissions=True)
	if docstatus == 1:
		pi.submit()
	return pi
```

- [ ] **Step 2.2: Run the two tests — expect PASS**

```bash
bench --site site16.local run-tests --app cecypo_powerpack \
  --module cecypo_powerpack.tests.test_zero_allocate_paste
```

Expected: 2 tests, PASS. If PI creation trips on missing accounts (expense/cost center), resolve by letting ERPNext auto-pick via `frappe.get_doc(...)`. If tests still fail due to company-level missing defaults on this bench, pick a different company via `frappe.db.get_value("Company", {"default_currency": "KES"}, "name")`.

- [ ] **Step 2.3: Add remaining matching tests**

Append into the `TestResolveBillNumbersForCredit` class (before the `_ensure_supplier` module-level helper):

```python
	# ── Ambiguous: two PIs same bill_no ───────────────────────────────────
	def test_ambiguous_two_pis_same_bill_no(self):
		from cecypo_powerpack.api import resolve_bill_numbers_for_credit

		_make_pi(self.company, self.supplier, self.item_code, "BILL/AMB/1", 100)
		_make_pi(self.company, self.supplier, self.item_code, "BILL/AMB/1", 200)

		result = resolve_bill_numbers_for_credit(
			company=self.company,
			supplier=self.supplier,
			bill_numbers=json.dumps(["BILL/AMB/1"]),
		)

		self.assertEqual(result["matched"], [])
		self.assertEqual(len(result["ambiguous"]), 1)
		self.assertEqual(result["ambiguous"][0]["bill_no"], "BILL/AMB/1")
		self.assertEqual(len(result["ambiguous"][0]["candidates"]), 2)
		self.assertEqual(result["not_found"], [])

	# ── Not found: unknown bill_no ────────────────────────────────────────
	def test_unknown_bill_no_is_not_found(self):
		from cecypo_powerpack.api import resolve_bill_numbers_for_credit

		result = resolve_bill_numbers_for_credit(
			company=self.company,
			supplier=self.supplier,
			bill_numbers=json.dumps(["BILL/NOPE/XYZ"]),
		)
		self.assertEqual(result["matched"], [])
		self.assertEqual(result["ambiguous"], [])
		self.assertEqual(result["not_found"], ["BILL/NOPE/XYZ"])

	# ── Wrong supplier → not_found ────────────────────────────────────────
	def test_wrong_supplier_is_not_found(self):
		from cecypo_powerpack.api import resolve_bill_numbers_for_credit

		_make_pi(self.company, self.supplier_other, self.item_code, "BILL/WRONG-SUP/1", 100)

		result = resolve_bill_numbers_for_credit(
			company=self.company,
			supplier=self.supplier,
			bill_numbers=json.dumps(["BILL/WRONG-SUP/1"]),
		)
		self.assertEqual(result["matched"], [])
		self.assertEqual(result["not_found"], ["BILL/WRONG-SUP/1"])

	# ── Draft (docstatus=0) → not_found ───────────────────────────────────
	def test_draft_pi_is_not_found(self):
		from cecypo_powerpack.api import resolve_bill_numbers_for_credit

		_make_pi(self.company, self.supplier, self.item_code, "BILL/DRAFT/1", 100, docstatus=0)

		result = resolve_bill_numbers_for_credit(
			company=self.company,
			supplier=self.supplier,
			bill_numbers=json.dumps(["BILL/DRAFT/1"]),
		)
		self.assertEqual(result["not_found"], ["BILL/DRAFT/1"])

	# ── Fully paid (outstanding_amount=0) → not_found ─────────────────────
	def test_zero_outstanding_is_not_found(self):
		from cecypo_powerpack.api import resolve_bill_numbers_for_credit

		pi = _make_pi(self.company, self.supplier, self.item_code, "BILL/PAID/1", 100)
		# Force outstanding to zero without running a real payment entry
		frappe.db.set_value("Purchase Invoice", pi.name, "outstanding_amount", 0)

		result = resolve_bill_numbers_for_credit(
			company=self.company,
			supplier=self.supplier,
			bill_numbers=json.dumps(["BILL/PAID/1"]),
		)
		self.assertEqual(result["not_found"], ["BILL/PAID/1"])

	# ── >200 bill numbers → throws ────────────────────────────────────────
	def test_too_many_bill_numbers_throws(self):
		from cecypo_powerpack.api import resolve_bill_numbers_for_credit

		bills = [f"BILL/BULK/{i}" for i in range(201)]
		with self.assertRaises(frappe.ValidationError):
			resolve_bill_numbers_for_credit(
				company=self.company,
				supplier=self.supplier,
				bill_numbers=json.dumps(bills),
			)

	# ── Blank / whitespace inputs dropped silently ────────────────────────
	def test_blank_inputs_dropped(self):
		from cecypo_powerpack.api import resolve_bill_numbers_for_credit

		result = resolve_bill_numbers_for_credit(
			company=self.company,
			supplier=self.supplier,
			bill_numbers=json.dumps(["", "   ", "\t"]),
		)
		self.assertEqual(result, {"matched": [], "ambiguous": [], "not_found": []})

	# ── Input order preserved across partitions ───────────────────────────
	def test_input_order_preserved(self):
		from cecypo_powerpack.api import resolve_bill_numbers_for_credit

		_make_pi(self.company, self.supplier, self.item_code, "BILL/ORDER/A", 100)
		_make_pi(self.company, self.supplier, self.item_code, "BILL/ORDER/C", 100)
		# Ambiguous B
		_make_pi(self.company, self.supplier, self.item_code, "BILL/ORDER/B", 100)
		_make_pi(self.company, self.supplier, self.item_code, "BILL/ORDER/B", 200)

		inputs = ["BILL/ORDER/C", "BILL/ORDER/MISSING", "BILL/ORDER/A", "BILL/ORDER/B"]
		result = resolve_bill_numbers_for_credit(
			company=self.company,
			supplier=self.supplier,
			bill_numbers=json.dumps(inputs),
		)

		self.assertEqual([m["bill_no"] for m in result["matched"]], ["BILL/ORDER/C", "BILL/ORDER/A"])
		self.assertEqual([a["bill_no"] for a in result["ambiguous"]], ["BILL/ORDER/B"])
		self.assertEqual(result["not_found"], ["BILL/ORDER/MISSING"])
```

- [ ] **Step 2.4: Run the full test module — expect PASS**

```bash
bench --site site16.local run-tests --app cecypo_powerpack \
  --module cecypo_powerpack.tests.test_zero_allocate_paste
```

Expected: 10 tests, PASS. No changes to `api.py` should be required — the endpoint already handles all these cases.

- [ ] **Step 2.5: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack
git add cecypo_powerpack/tests/test_zero_allocate_paste.py
git commit -m "test(payment-recon): cover matching, partitioning, and edge cases for resolve_bill_numbers_for_credit"
```

---

## Task 3: Documentation-only server change

**Files:**
- Modify: `cecypo_powerpack/custom_payment_reconciliation.py` (~line 70)

- [ ] **Step 3.1: Add the one-line comment above `_reconcile_without_validation`**

Find the line `def _reconcile_without_validation(self):` in `custom_payment_reconciliation.py`. Immediately above the `def` line, add:

```python
	# NOTE: The process-level monkey-patch in zero_reconcile() is safe under preforked
	# Gunicorn (current bench16 config). Under gevent/gthread it would race across greenlets.
```

Keep existing indentation (tab) matching the method.

- [ ] **Step 3.2: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack
git add cecypo_powerpack/custom_payment_reconciliation.py
git commit -m "docs(payment-recon): note gevent risk of zero_reconcile monkey-patch"
```

---

## Task 4: Client — button wiring and paste parser

**Files:**
- Modify: `cecypo_powerpack/public/js/payment_reconciliation_powerup.js`

All new JS lives inside the existing IIFE (the `(function () { ... })();` wrapping the file). Append new code **before** the closing `})();` on the last line.

- [ ] **Step 4.1: Hook the new button into the existing refresh / party_type chain**

In the `frappe.ui.form.on('Payment Reconciliation', { ... })` block, update `refresh` and `party_type` to also call `setup_zero_allocate_paste_button(frm)` inside the `enabled` branch. The edit:

Find this existing block:

```javascript
	refresh(frm) {
		remove_all_displays();
		is_powerpack_enabled().then(enabled => {
			if (!enabled) return;
			setup_zero_allocate_button(frm);
			setup_load_doc_info_button(frm);
			setup_allocate_2pct_button(frm);
		});
	},
	party_type(frm) {
		remove_all_displays();
		is_powerpack_enabled().then(enabled => {
			if (enabled) setup_allocate_2pct_button(frm);
		});
	},
```

Replace with:

```javascript
	refresh(frm) {
		remove_all_displays();
		is_powerpack_enabled().then(enabled => {
			if (!enabled) return;
			setup_zero_allocate_button(frm);
			setup_zero_allocate_paste_button(frm);
			setup_load_doc_info_button(frm);
			setup_allocate_2pct_button(frm);
		});
	},
	party_type(frm) {
		remove_all_displays();
		is_powerpack_enabled().then(enabled => {
			if (!enabled) return;
			setup_zero_allocate_paste_button(frm);
			setup_allocate_2pct_button(frm);
		});
	},
```

Also update the `get_unreconciled_entries` handler (same block) so the paste button appears once supplier payments load:

Find:

```javascript
	get_unreconciled_entries(frm) { remove_all_displays(); },
```

Replace with:

```javascript
	get_unreconciled_entries(frm) {
		remove_all_displays();
		is_powerpack_enabled().then(enabled => {
			if (enabled) setup_zero_allocate_paste_button(frm);
		});
	},
```

- [ ] **Step 4.2: Append the Zero Allocate with Paste section**

Just before the closing `})();` at the bottom of the file, append:

```javascript
// ═══════════════════════════════════════════════════════════════════════════════
// ZERO ALLOCATE WITH PASTE (Supplier only)
// ═══════════════════════════════════════════════════════════════════════════════

function setup_zero_allocate_paste_button(frm) {
	try { frm.page.remove_inner_button(__('Zero Allocate with Paste'), __('Powerup')); } catch (_) {}
	if (frm.doc.party_type !== 'Supplier') return;
	const has_credit = (frm.doc.payments || []).some(p => (p.amount || 0) > 0);
	if (!has_credit) return;
	frm.page.add_inner_button(
		__('Zero Allocate with Paste'),
		() => zero_allocate_with_paste(frm),
		__('Powerup'),
	);
}

// ─── Paste parser ─────────────────────────────────────────────────────────────

const _CURRENCY_SYMBOL_RE = /^(KES|USD|EUR|GBP|INR|\$|€|£|₹)\s*/i;

function _normalize_amount(raw) {
	if (raw == null) return NaN;
	let s = String(raw).trim();
	if (!s) return NaN;
	s = s.replace(_CURRENCY_SYMBOL_RE, '').trim();
	// Strip thousands commas only if a dot is also present OR there are no commas acting as decimals.
	// For Excel/KE locale we expect '.' decimal and ',' thousands.
	s = s.replace(/,/g, '');
	if (!/^-?\d+(\.\d+)?$/.test(s)) return NaN;
	return parseFloat(s);
}

function _split_line(line) {
	// First delimiter wins: tab > multi-space > comma.
	if (line.includes('\t')) return line.split('\t');
	if (/\s{2,}/.test(line)) return line.split(/\s{2,}/);
	if (line.includes(',')) return line.split(',');
	return [line];
}

function parse_paste(text) {
	const rows = [];
	const skipped = [];
	if (!text) return { rows, skipped };

	const raw_lines = text.split(/\r?\n/);
	let first_content_line_seen = false;

	for (let i = 0; i < raw_lines.length; i++) {
		const raw = raw_lines[i];
		const line = raw.trim();
		if (!line) continue;

		const parts = _split_line(line).map(p => p.trim());
		if (parts.length < 2) {
			skipped.push({ line: raw, reason: 'Invalid amount' });
			continue;
		}
		const bill_no = parts[0];
		const amount = _normalize_amount(parts[1]);

		if (!first_content_line_seen) {
			first_content_line_seen = true;
			if (isNaN(amount)) {
				// Auto-detect header row — skip silently
				continue;
			}
		}

		if (!bill_no || isNaN(amount)) {
			skipped.push({ line: raw, reason: 'Invalid amount' });
			continue;
		}
		rows.push({ bill_no, amount });
	}
	return { rows, skipped };
}

function zero_allocate_with_paste(frm) {
	// Stub — wired up in Task 5
	frappe.msgprint(__('Zero Allocate with Paste — coming in Task 5'));
}
```

- [ ] **Step 4.3: Rebuild assets**

```bash
cd /home/frappeuser/bench16
bench build --app cecypo_powerpack
```

Expected: build completes without errors. If it fails with a syntax error, re-read the file at the edited lines and fix.

- [ ] **Step 4.4: Manual smoke test — button visibility**

In a browser (hard-refresh the Desk first):

1. Open any Payment Reconciliation form.
2. Set `party_type = Supplier`, pick a supplier with open PIs and a return PI or PE.
3. Click **Get Unreconciled Entries**.
4. **Expected:** Under the "Powerup" inner-button group, both **Zero Allocate** and **Zero Allocate with Paste** are visible.
5. Change `party_type` to `Customer`. **Expected:** Zero Allocate with Paste disappears on the next refresh.
6. Return to Supplier but with no payments loaded. **Expected:** Button is hidden.

- [ ] **Step 4.5: Smoke test the parser from the browser console**

With the form open, paste into DevTools console:

```javascript
(function () {
	const results = [
		['BILL/1\t150000\nBILL/2\t75000.50\nBILL/3\t1,200.00', 3, 0],
		['Bill No\tAmount\nBILL/1\t100', 1, 0], // header auto-skip
		['BILL/1,100\nBILL/2,oops\nBILL/3,300', 2, 1], // comma delims + bad amount
		['BILL/1  100\nBILL/2  200', 2, 0], // multi-space
		['KES 1,234.56,BILL/1', 0, 1], // wrong column order → reason Invalid amount (first line is taken as header since amount NaN)
		['', 0, 0],
	];
	results.forEach(([text, exp_rows, exp_skipped], i) => {
		const r = window.__cppk_test_parse_paste ? window.__cppk_test_parse_paste(text) : null;
		console.log(i, r);
	});
})();
```

Because helpers are IIFE-scoped, exposing them for smoke testing is optional. If you want runtime confirmation, temporarily add `window.__cppk_test_parse_paste = parse_paste;` above `function zero_allocate_with_paste`, rebuild, run the snippet, **then remove the line** and rebuild again before committing. Alternative: trust the logic and verify via the Task 6 end-to-end smoke test.

- [ ] **Step 4.6: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack
git add cecypo_powerpack/public/js/payment_reconciliation_powerup.js
git commit -m "feat(payment-recon): add Zero Allocate with Paste button + paste parser"
```

---

## Task 5: Client — dialog, review UI, auto-distribute, Proceed

**Files:**
- Modify: `cecypo_powerpack/public/js/payment_reconciliation_powerup.js`

All edits append to or replace sections inside the same IIFE. This is the bulk of the UI.

- [ ] **Step 5.1: Replace the `zero_allocate_with_paste` stub with the full implementation**

Replace the single function `zero_allocate_with_paste` added in Task 4 with the block below, and append all the supporting helpers (`run_auto_distribute`, `render_review_section`, `proceed_zero_allocate_paste`, and shared state constants) in the same section.

Find the Task 4 stub:

```javascript
function zero_allocate_with_paste(frm) {
	// Stub — wired up in Task 5
	frappe.msgprint(__('Zero Allocate with Paste — coming in Task 5'));
}
```

Replace the stub (and append the helpers below it) with:

```javascript
function _credit_options_from_payments(payments) {
	return (payments || []).filter(p => (p.amount || 0) > 0).map(p => {
		const currency = p.currency || frappe.defaults.get_global_default('currency');
		const label = `${p.reference_name} — ${p.reference_type} — ${format_currency(p.amount, currency)}`;
		const value = `${p.reference_type}|${p.reference_name}`;
		return { label, value };
	});
}

function _lookup_credit(frm, composite_key) {
	if (!composite_key) return null;
	const [ref_type, ref_name] = composite_key.split('|');
	return (frm.doc.payments || []).find(
		p => p.reference_type === ref_type && p.reference_name === ref_name && (p.amount || 0) > 0,
	) || null;
}

function _credit_available(frm, payment) {
	if (!payment) return 0;
	const gross = payment.amount || 0;
	const already = (frm.doc.allocation || [])
		.filter(a => a.reference_type === payment.reference_type && a.reference_name === payment.reference_name)
		.reduce((acc, a) => acc + (a.allocated_amount || 0), 0);
	return flt(gross - already, 2);
}

function run_auto_distribute(rows, credit_available) {
	// 1. Cap each row to [0, outstanding]
	rows.forEach(r => {
		r.amount = Math.max(0, Math.min(flt(r.amount || 0), flt(r.outstanding_amount || 0)));
	});
	// 2. Compute total
	let total = rows.reduce((s, r) => s + r.amount, 0);
	// 3. If over credit, absorb from the tail
	if (total > credit_available) {
		let overflow = total - credit_available;
		for (let i = rows.length - 1; i >= 0 && overflow > 0; i--) {
			const take = Math.min(rows[i].amount, overflow);
			rows[i].amount -= take;
			overflow -= take;
		}
	}
	// 4. Round to 2 decimals, nudge last non-zero by residual
	rows.forEach(r => { r.amount = flt(r.amount, 2); });
	const rounded_total = rows.reduce((s, r) => s + r.amount, 0);
	const target = Math.min(total, credit_available);
	const residual = flt(target - rounded_total, 2);
	if (residual !== 0) {
		for (let i = rows.length - 1; i >= 0; i--) {
			if (rows[i].amount > 0) {
				rows[i].amount = flt(rows[i].amount + residual, 2);
				break;
			}
		}
	}
}

function render_review_section(dialog, state) {
	const currency = state.credit.currency || dialog.get_value('_currency') || frappe.defaults.get_global_default('currency');
	const rows_html = state.matched.map((r, idx) => {
		const diff = flt((r.amount || 0) - r.outstanding_amount, 2);
		const diff_color = diff === 0 ? 'var(--text-muted)' : (diff > 0 ? '#ef4444' : '#10b981');
		return `
			<tr data-idx="${idx}">
				<td style="font-family:monospace;">${frappe.utils.escape_html(r.bill_no)}</td>
				<td style="font-family:monospace;">${frappe.utils.escape_html(r.pi_name)}</td>
				<td style="text-align:right;">${format_currency(r.outstanding_amount, currency)}</td>
				<td style="text-align:right;">
					<input type="number" step="0.01" min="0" class="form-control input-xs zap-amount"
					       data-idx="${idx}" value="${flt(r.amount || 0, 2)}"
					       style="text-align:right;max-width:140px;display:inline-block;">
				</td>
				<td style="text-align:right;color:${diff_color};" class="zap-diff" data-idx="${idx}">
					${format_currency(diff, currency)}
				</td>
				<td style="text-align:center;white-space:nowrap;">
					<button class="btn btn-xs btn-default zap-match-out" data-idx="${idx}" title="${__('Set to outstanding')}">↔</button>
					<button class="btn btn-xs btn-default zap-remove" data-idx="${idx}" title="${__('Remove')}">×</button>
				</td>
			</tr>`;
	}).join('');

	const skipped_rows = [
		...state.ambiguous.map(a => `<tr>
			<td style="font-family:monospace;">${frappe.utils.escape_html(a.bill_no)}</td>
			<td>${__('Ambiguous: {0} candidates', [a.candidates.length])}</td>
		</tr>`),
		...state.not_found.map(b => `<tr>
			<td style="font-family:monospace;">${frappe.utils.escape_html(b)}</td>
			<td>${__('Not found')}</td>
		</tr>`),
		...state.invalid.map(s => `<tr>
			<td style="font-family:monospace;">${frappe.utils.escape_html(s.line)}</td>
			<td>${frappe.utils.escape_html(s.reason)}</td>
		</tr>`),
	].join('');

	const total_skipped = state.ambiguous.length + state.not_found.length + state.invalid.length;
	const skipped_collapsed = total_skipped === 0 ? ' hidden' : '';

	const html = `
		<div class="zap-review">
			<div class="zap-summary" style="display:flex;gap:16px;flex-wrap:wrap;padding:8px 0 12px;font-size:12px;">
				<div><strong>${__('Credit Available')}:</strong> <span class="zap-credit">${format_currency(state.credit_available, currency)}</span></div>
				<div><strong>${__('Total Allocated')}:</strong> <span class="zap-total">${format_currency(0, currency)}</span></div>
				<div><strong>${__('Remaining')}:</strong> <span class="zap-remaining" style="font-weight:700;">${format_currency(state.credit_available, currency)}</span></div>
				<div><strong>${__('Matched')}:</strong> ${state.matched.length}</div>
				<div><strong>${__('Skipped')}:</strong> ${total_skipped}</div>
			</div>
			<div class="zap-overalloc-warning" style="display:none;color:#ef4444;font-weight:600;padding:4px 0;"></div>
			<table class="table table-bordered table-sm" style="font-size:12px;">
				<thead style="background:var(--control-bg);">
					<tr>
						<th>${__('Bill No')}</th>
						<th>${__('PI Name')}</th>
						<th style="text-align:right;">${__('Outstanding')}</th>
						<th style="text-align:right;">${__('Amount')}</th>
						<th style="text-align:right;">${__('Diff')}</th>
						<th style="text-align:center;">${__('Actions')}</th>
					</tr>
				</thead>
				<tbody class="zap-matched">${rows_html || `<tr><td colspan="6" style="text-align:center;color:var(--text-muted);">${__('No matched rows')}</td></tr>`}</tbody>
			</table>
			<details${total_skipped === 0 ? '' : ' open'}${skipped_collapsed}>
				<summary style="cursor:pointer;font-weight:600;">${__('Skipped / Unmatched')} (${total_skipped})</summary>
				<table class="table table-bordered table-sm" style="font-size:12px;margin-top:6px;">
					<thead><tr><th>${__('Input')}</th><th>${__('Reason')}</th></tr></thead>
					<tbody>${skipped_rows}</tbody>
				</table>
			</details>
			<div style="display:flex;gap:8px;padding-top:8px;">
				<button class="btn btn-default btn-sm zap-auto">${__('Auto Distribute')}</button>
				<button class="btn btn-default btn-sm zap-reset">${__('Reset')}</button>
			</div>
		</div>
	`;

	dialog.fields_dict.review.$wrapper.html(html);
	_wire_review_handlers(dialog, state);
	_recompute_summary(dialog, state);
}

function _wire_review_handlers(dialog, state) {
	const $w = dialog.fields_dict.review.$wrapper;

	$w.off('input', '.zap-amount').on('input', '.zap-amount', function () {
		const idx = parseInt($(this).data('idx'), 10);
		state.matched[idx].amount = flt($(this).val());
		_recompute_summary(dialog, state);
	});

	$w.off('click', '.zap-match-out').on('click', '.zap-match-out', function () {
		const idx = parseInt($(this).data('idx'), 10);
		state.matched[idx].amount = flt(state.matched[idx].outstanding_amount, 2);
		render_review_section(dialog, state);
	});

	$w.off('click', '.zap-remove').on('click', '.zap-remove', function () {
		const idx = parseInt($(this).data('idx'), 10);
		state.matched.splice(idx, 1);
		render_review_section(dialog, state);
	});

	$w.off('click', '.zap-auto').on('click', '.zap-auto', function () {
		run_auto_distribute(state.matched, state.credit_available);
		render_review_section(dialog, state);
	});

	$w.off('click', '.zap-reset').on('click', '.zap-reset', function () {
		state.matched.forEach(r => { r.amount = r._pasted_amount; });
		render_review_section(dialog, state);
	});
}

function _recompute_summary(dialog, state) {
	const $w = dialog.fields_dict.review.$wrapper;
	const currency = state.credit.currency || frappe.defaults.get_global_default('currency');
	const total = state.matched.reduce((s, r) => s + flt(r.amount || 0), 0);
	const remaining = flt(state.credit_available - total, 2);
	$w.find('.zap-total').text(format_currency(total, currency));
	$w.find('.zap-remaining').text(format_currency(remaining, currency)).css(
		'color', remaining < 0 ? '#ef4444' : '#10b981',
	);
	const $warn = $w.find('.zap-overalloc-warning');
	if (remaining < 0) {
		$warn.text(__('Over-allocated by {0}', [format_currency(-remaining, currency)])).show();
	} else {
		$warn.hide();
	}
	// Disable primary when over-allocated or nothing to allocate
	const has_amount = state.matched.some(r => flt(r.amount || 0) > 0);
	dialog.get_primary_btn().prop('disabled', remaining < 0 || !has_amount);
}

function zero_allocate_with_paste(frm) {
	const credit_options = _credit_options_from_payments(frm.doc.payments);
	if (!credit_options.length) {
		frappe.msgprint({
			title: __('No Credits Available'),
			message: __('Run "Get Unreconciled Entries" first — no payments with amount > 0 were found.'),
			indicator: 'orange',
		});
		return;
	}

	const state = {
		credit: null,
		credit_available: 0,
		matched: [],
		ambiguous: [],
		not_found: [],
		invalid: [],
	};

	const dialog = new frappe.ui.Dialog({
		title: __('Zero Allocate with Paste'),
		size: 'large',
		fields: [
			{
				fieldname: 'credit', fieldtype: 'Select', label: __('Credit'), reqd: 1,
				options: [''].concat(credit_options.map(o => o.value)).join('\n'),
				description: __("Shown: credits loaded from this document. Run 'Get Unreconciled Entries' first if the credit you want is missing."),
			},
			{
				fieldname: 'paste', fieldtype: 'Small Text', label: __('Paste (bill_no, amount)'),
				description: __('Tab-, comma-, or multi-space-separated. First row treated as header if amount column is non-numeric.'),
			},
			{ fieldname: 'parse_btn', fieldtype: 'Button', label: __('Parse & Match') },
			{ fieldname: 'review', fieldtype: 'HTML' },
		],
		primary_action_label: __('Proceed'),
		primary_action() { proceed_zero_allocate_paste(frm, dialog, state); },
	});

	// Relabel the Select options to human-readable via DOM once rendered.
	// Frappe Select only accepts string options; we post-decorate.
	dialog.$wrapper.on('shown.bs.modal', function () {
		const $sel = dialog.fields_dict.credit.$input;
		$sel.find('option').each(function () {
			const val = $(this).val();
			const opt = credit_options.find(o => o.value === val);
			if (opt) $(this).text(opt.label);
		});
	});

	dialog.fields_dict.credit.$input.on('change', function () {
		state.credit = _lookup_credit(frm, dialog.get_value('credit'));
		state.credit_available = _credit_available(frm, state.credit);
		dialog.fields_dict.parse_btn.$input.prop('disabled', !state.credit);
		dialog.fields_dict.paste.$input.prop('disabled', !state.credit);
	});
	dialog.fields_dict.parse_btn.$input.prop('disabled', true);
	dialog.fields_dict.paste.$input.prop('disabled', true);

	dialog.fields_dict.parse_btn.$input.on('click', function () {
		const text = dialog.get_value('paste') || '';
		const { rows, skipped } = parse_paste(text);
		if (!rows.length) {
			frappe.msgprint({ title: __('Nothing to match'),
				message: __('Paste at least one row with a parseable amount.'), indicator: 'orange' });
			return;
		}
		const bill_nos = rows.map(r => r.bill_no);
		frappe.call({
			method: 'cecypo_powerpack.api.resolve_bill_numbers_for_credit',
			args: {
				company: frm.doc.company,
				supplier: frm.doc.party,
				bill_numbers: JSON.stringify(bill_nos),
			},
			freeze: true,
			freeze_message: __('Resolving bill numbers…'),
			callback(r) {
				if (!r.message) return;
				const pasted_map = Object.fromEntries(rows.map(x => [x.bill_no, x.amount]));
				state.matched = (r.message.matched || []).map(m => ({
					...m,
					amount: flt(pasted_map[m.bill_no] || 0, 2),
					_pasted_amount: flt(pasted_map[m.bill_no] || 0, 2),
				}));
				state.ambiguous = r.message.ambiguous || [];
				state.not_found = r.message.not_found || [];
				state.invalid = skipped;
				render_review_section(dialog, state);
			},
		});
	});

	dialog.show();
}

function proceed_zero_allocate_paste(frm, dialog, state) {
	// Guards
	if (!state.credit) {
		frappe.msgprint({ title: __('Error'), message: __('Pick a credit first.'), indicator: 'red' }); return;
	}
	const fresh = _lookup_credit(frm, `${state.credit.reference_type}|${state.credit.reference_name}`);
	if (!fresh) {
		frappe.msgprint({
			title: __('Credit no longer available'),
			message: __('The selected credit is no longer available — please reopen the dialog.'),
			indicator: 'red',
		});
		return;
	}
	const rows = state.matched.filter(r => flt(r.amount || 0) > 0);
	if (!rows.length) {
		frappe.msgprint({ title: __('Nothing to allocate'),
			message: __('Set an amount > 0 on at least one row.'), indicator: 'orange' });
		return;
	}
	const total = rows.reduce((s, r) => s + flt(r.amount), 0);
	if (total - state.credit_available > 0.005) {
		frappe.msgprint({ title: __('Over-allocated'),
			message: __('Reduce amounts so total ≤ Credit Available.'), indicator: 'red' });
		return;
	}

	const do_populate = (replace) => {
		const payments_payload = [fresh];
		const invoices_payload = rows.map(r => ({
			invoice_type: 'Purchase Invoice',
			invoice_number: r.pi_name,
			outstanding_amount: r.outstanding_amount,
			currency: r.currency,
		}));
		frappe.call({
			method: 'cecypo_powerpack.api.zero_allocate_entries',
			args: { doc: frm.doc, payments: payments_payload, invoices: invoices_payload },
			freeze: true,
			freeze_message: __('Building allocation rows…'),
			callback(r) {
				if (!r.message?.length) {
					frappe.msgprint({ title: __('No Allocations Created'),
						message: __('Nothing was produced.'), indicator: 'orange' });
					return;
				}
				if (replace) frm.clear_table('allocation');
				const amount_map = Object.fromEntries(rows.map(x => [x.pi_name, flt(x.amount, 2)]));
				r.message.forEach(a => {
					a.allocated_amount = amount_map[a.invoice_number] ?? 0;
					Object.assign(frm.add_child('allocation'), a);
				});
				frm.refresh_field('allocation');
				dialog.hide();
				frappe.show_alert({
					message: __('Added {0} allocation rows. Click Zero Reconcile to commit.', [r.message.length]),
					indicator: 'green',
				});
				setTimeout(() => setup_zero_reconcile_button(frm), 100);
			},
		});
	};

	if ((frm.doc.allocation || []).length > 0) {
		const picker = new frappe.ui.Dialog({
			title: __('Existing Allocations Found'),
			fields: [
				{ fieldtype: 'HTML', options:
					`<p>${__('There are {0} existing allocation rows.', [frm.doc.allocation.length])}</p>
					 <p>${__('This will add {0} new rows. What would you like to do?', [rows.length])}</p>` },
				{ fieldname: 'action', fieldtype: 'Select', label: 'Action',
				  options: ['Replace existing allocations', 'Append to existing allocations'],
				  default: 'Append to existing allocations', reqd: 1 },
			],
			primary_action_label: __('Continue'),
			primary_action(v) { picker.hide(); do_populate(v.action === 'Replace existing allocations'); },
		});
		picker.show();
	} else {
		do_populate(false);
	}
}
```

- [ ] **Step 5.2: Rebuild assets**

```bash
cd /home/frappeuser/bench16
bench build --app cecypo_powerpack
```

Expected: build completes without errors.

- [ ] **Step 5.3: Commit**

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack
git add cecypo_powerpack/public/js/payment_reconciliation_powerup.js
git commit -m "feat(payment-recon): implement Zero Allocate with Paste dialog + review + Proceed"
```

---

## Task 6: End-to-end manual QA

**Files:**
- None (QA pass — no code changes). If a bug is found, fix in a new task and re-run this checklist.

- [ ] **Step 6.1: Run the regression guard first**

```bash
cd /home/frappeuser/bench16
bench --site site16.local run-tests --app cecypo_powerpack
```

Expected: all tests PASS, including existing `test_powerpack_settings` and the 10 new `test_zero_allocate_paste` tests.

- [ ] **Step 6.2: Execute the manual QA checklist from the spec**

Hard-refresh the Desk, then walk through each item in the spec's "Manual QA checklist" section:

1. Tab-separated paste from Excel parses.
2. Comma-separated paste parses.
3. Header row (`Bill No\tAmount`) auto-skipped.
4. Amounts with thousands separators / `KES` prefix parse.
5. Ambiguous bill_no appears in skipped panel.
6. Not-found bill_no appears in skipped panel.
7. Over-allocation blocks Proceed (pinned red warning; primary button disabled).
8. Auto Distribute with `sum > credit` — bottom rows shrink; total equals credit available.
9. Auto Distribute with one row's amount > outstanding — that row clamps; others untouched.
10. Existing allocation rows → Replace/Append dialog appears.
11. Selected credit has prior allocation rows → Credit Available reflects reduced amount.
12. Credit = Payment Entry → clicking Zero Reconcile succeeds (goes through `reconcile_against_document`).
13. Credit = return Purchase Invoice → Zero Reconcile succeeds (goes through `reconcile_dr_cr_note`).
14. Multi-currency credit vs invoice → `exchange_rate` is populated per allocation row (inspect row before reconcile).
15. Feature flag off (`enable_payment_reconciliation_powerup = 0` in PowerPack Settings) → button hidden on next refresh.

- [ ] **Step 6.3: Final commit (only if QA uncovered trivial tweaks)**

If QA passed with no code changes, skip. Otherwise:

```bash
cd /home/frappeuser/bench16/apps/cecypo_powerpack
git add -A
git commit -m "fix(payment-recon): <brief description of QA finding>"
```

---

## Self-Review (done by plan author before handoff)

- [x] **Spec coverage:** User flow (Tasks 4–5), server endpoint (Tasks 1–2), parser (Task 4), review UI + auto-distribute (Task 5), allocation-row population (Task 5), credit-availability calc (Task 5 `_credit_available`), error handling branches (Tasks 1–2 + Task 5 guards), documentation-only comment (Task 3), tests (Tasks 1–2), regression guard + manual QA (Task 6).
- [x] **No placeholders:** every code step has the code it needs.
- [x] **Type consistency:** `state.matched` / `state.ambiguous` / `state.not_found` / `state.invalid` are used consistently across `zero_allocate_with_paste`, `render_review_section`, `_wire_review_handlers`, `_recompute_summary`, `proceed_zero_allocate_paste`. Server returns `{matched, ambiguous, not_found}` — mapped into state in the `parse_btn` click handler.
- [x] **Acknowledged gap:** JS parser unit tests are explicit non-goal per spec; covered via browser-console smoke (Step 4.5) + Task 6 manual QA.
