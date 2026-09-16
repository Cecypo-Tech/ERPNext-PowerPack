# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

CUSTOMER = "_Test Customer"
COMPANY = "_Test Company"


def make_invoice(days_ago_posted, days_to_due, rate=100):
	"""Submitted invoice: posted `days_ago_posted` days ago, due `days_to_due` days from today (negative = overdue)."""
	from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice

	si = create_sales_invoice(customer=CUSTOMER, company=COMPANY, rate=rate, qty=1, do_not_save=True)
	si.set_posting_time = 1
	si.posting_date = add_days(today(), -days_ago_posted)
	si.due_date = add_days(today(), days_to_due)
	si.insert()
	si.submit()
	return si


def make_advance(amount):
	from erpnext.accounts.doctype.payment_entry.test_payment_entry import create_payment_entry

	pe = create_payment_entry(
		payment_type="Receive", party_type="Customer", party=CUSTOMER,
		paid_from="Debtors - _TC", paid_to="_Test Cash - _TC", paid_amount=amount, save=True,
	)
	pe.submit()
	return pe


class TestHighlightRule(FrappeTestCase):
	def test_rule(self):
		from cecypo_powerpack.customer_snapshot import highlight_for

		self.assertEqual(highlight_for(1, 500, 0), "red")
		self.assertEqual(highlight_for(0, 500, 0), "amber")
		self.assertEqual(highlight_for(0, 0, 200), "amber")
		self.assertEqual(highlight_for(0, 0, 0), "")


class TestCustomerSnapshot(FrappeTestCase):
	def setUp(self):
		frappe.db.set_single_value("PowerPack Settings", "enable_warnings", 1)
		frappe.clear_cache(doctype="PowerPack Settings")
		frappe.cache().delete_value("powerpack_settings")
		frappe.cache().delete_value("powerpack_feature_enable_warnings")

	def tearDown(self):
		frappe.db.rollback()
		frappe.cache().delete_value("powerpack_settings")
		frappe.cache().delete_value("powerpack_feature_enable_warnings")

	def _snapshot(self):
		from cecypo_powerpack.customer_snapshot import build_customer_snapshot

		return build_customer_snapshot(CUSTOMER, COMPANY)

	def test_shape_keys(self):
		snap = self._snapshot()
		for key in (
			"customer", "customer_name", "company", "currency", "primary_contact", "contacts",
			"credit_limit", "payment_terms", "outstanding_total", "overdue_total", "overdue_count",
			"advances_total", "net_position", "invoices", "advances", "highlight",
		):
			self.assertIn(key, snap, key)
		self.assertNotIn("stats", snap)  # no billing totals in the sales-document dialog

	def test_overdue_and_not_yet_due_are_classified(self):
		overdue = make_invoice(days_ago_posted=40, days_to_due=-10, rate=100)
		current = make_invoice(days_ago_posted=1, days_to_due=+20, rate=50)
		snap = self._snapshot()
		names = {r["name"]: r for r in snap["invoices"]}
		self.assertIn(overdue.name, names)
		self.assertIn(current.name, names)
		self.assertEqual(names[overdue.name]["days_overdue"], 10)
		self.assertEqual(names[current.name]["days_overdue"], 0)
		self.assertEqual(snap["overdue_count"], sum(1 for r in snap["invoices"] if r["days_overdue"] > 0))
		self.assertEqual(snap["overdue_total"], sum(r["outstanding_amount"] for r in snap["invoices"] if r["days_overdue"] > 0))
		self.assertEqual(snap["highlight"], "red")
		# overdue rows come first
		self.assertEqual(snap["invoices"][0]["name"], overdue.name)

	def test_only_current_invoices_is_amber(self):
		make_invoice(days_ago_posted=1, days_to_due=+20, rate=50)
		snap = self._snapshot()
		if snap["overdue_count"]:
			self.skipTest("site has pre-existing overdue invoices for _Test Customer")
		self.assertEqual(snap["highlight"], "amber")

	def test_advances_and_net_position(self):
		make_advance(750)
		snap = self._snapshot()
		self.assertTrue(any(a["unallocated_amount"] == 750 for a in snap["advances"]))
		self.assertGreaterEqual(snap["advances_total"], 750)
		self.assertEqual(snap["net_position"], round(snap["outstanding_total"] - snap["advances_total"], 2))
		self.assertIn(snap["highlight"], ("red", "amber"))

	def test_company_filter_excludes_other_company(self):
		from cecypo_powerpack.customer_snapshot import build_customer_snapshot

		si = make_invoice(days_ago_posted=1, days_to_due=+5, rate=10)
		self.assertIn(si.name, {r["name"] for r in self._snapshot()["invoices"]})
		other = build_customer_snapshot(CUSTOMER, "_Test Company 1")
		self.assertNotIn(si.name, {r["name"] for r in other["invoices"]})

	def test_api_gates_on_switch_and_permission(self):
		from cecypo_powerpack.api import get_customer_snapshot

		self.assertTrue(get_customer_snapshot(CUSTOMER, COMPANY))
		self.assertEqual(get_customer_snapshot("", COMPANY), {})
		frappe.db.set_single_value("PowerPack Settings", "enable_warnings", 0)
		frappe.cache().delete_value("powerpack_settings")
		frappe.cache().delete_value("powerpack_feature_enable_warnings")
		self.assertEqual(get_customer_snapshot(CUSTOMER, COMPANY), {})

	def test_old_overdue_method_is_gone(self):
		import cecypo_powerpack.api as api

		self.assertFalse(hasattr(api, "get_customer_overdue_invoices"))

	def test_paid_is_never_negative_and_uses_the_rounded_total(self):
		from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice

		si = create_sales_invoice(customer=CUSTOMER, company=COMPANY, rate=135.72, qty=1, do_not_save=True)
		si.disable_rounded_total = 0
		si.insert()
		si.submit()
		row = next(r for r in self._snapshot()["invoices"] if r["name"] == si.name)
		self.assertGreaterEqual(row["paid"], 0)
		expected = si.rounded_total or si.grand_total
		self.assertEqual(row["grand_total"], round(expected, 2))
		self.assertEqual(row["paid"], round(expected - si.outstanding_amount, 2))

	def _sales_only_user(self):
		email = "_pp_sales_only@example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc({
				"doctype": "User", "email": email, "first_name": "PP Sales",
				"send_welcome_email": 0, "roles": [{"role": "Sales User"}],
			}).insert(ignore_permissions=True)
		return email

	def test_sales_user_sees_the_full_position(self):
		from cecypo_powerpack.api import get_customer_snapshot

		si = make_invoice(days_ago_posted=30, days_to_due=-5, rate=120)
		pe = make_advance(300)
		email = self._sales_only_user()
		frappe.set_user(email)
		try:
			snap = get_customer_snapshot(CUSTOMER, COMPANY)
			self.assertIn(si.name, [r["name"] for r in snap["invoices"]])
			self.assertIn(pe.name, [a["name"] for a in snap["advances"]])
		finally:
			frappe.set_user("Administrator")

	def test_customer_user_permission_is_enforced(self):
		from cecypo_powerpack.api import get_customer_snapshot

		email = self._sales_only_user()
		if not frappe.db.exists("Customer", "_Test Customer 1"):
			self.skipTest("_Test Customer 1 missing")
		frappe.get_doc({"doctype": "User Permission", "user": email, "allow": "Customer", "for_value": "_Test Customer 1"}).insert(ignore_permissions=True)
		frappe.clear_cache(user=email)
		frappe.set_user(email)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_customer_snapshot(CUSTOMER, COMPANY)
		finally:
			frappe.set_user("Administrator")

	def test_company_user_permission_is_enforced(self):
		from cecypo_powerpack.api import get_customer_snapshot

		email = self._sales_only_user()
		if not frappe.db.exists("Company", "_Test Company 1"):
			self.skipTest("_Test Company 1 missing")
		frappe.get_doc({"doctype": "User Permission", "user": email, "allow": "Company", "for_value": "_Test Company 1"}).insert(ignore_permissions=True)
		frappe.clear_cache(user=email)
		frappe.set_user(email)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_customer_snapshot(CUSTOMER, COMPANY)
		finally:
			frappe.set_user("Administrator")


class TestWarningsDescription(FrappeTestCase):
	def test_description_describes_the_dialog(self):
		note = frappe.get_meta("PowerPack Settings").get_field("warnings_description").options
		self.assertIn("(i)", note)
		self.assertIn("Copy", note)
		self.assertIn("Email", note)
		self.assertNotIn("popup if the customer has outstanding overdue invoices", note)
