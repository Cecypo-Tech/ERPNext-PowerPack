# Copyright (c) 2026, Cecypo.Tech and Contributors
# See license.txt

import json

import frappe
from frappe.tests.utils import FrappeTestCase


TEST_SUPPLIER = "_Test ZAP Supplier"
TEST_SUPPLIER_OTHER = "_Test ZAP Supplier Other"
TEST_ITEM = "_Test ZAP Item"


class TestResolveBillNumbersForCredit(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from erpnext.stock.doctype.item.test_item import make_item
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
