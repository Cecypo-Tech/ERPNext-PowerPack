import json
import uuid
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import UnitTestCase


class TestQpUpdateStockSetting(UnitTestCase):
	"""Doesn't touch any Sales Order / Payment Entry data — safe to re-run."""

	def setUp(self):
		self._original = frappe.db.sql(
			"""select value from `tabSingles` where doctype='PowerPack Settings' and field='qp_update_stock'"""
		)

	def tearDown(self):
		if self._original:
			frappe.db.set_single_value("PowerPack Settings", "qp_update_stock", self._original[0][0])
		else:
			frappe.db.sql(
				"""delete from `tabSingles` where doctype='PowerPack Settings' and field='qp_update_stock'"""
			)
		frappe.db.commit()

	def test_respects_explicit_disable(self):
		from cecypo_powerpack.utils import is_feature_enabled

		frappe.db.set_single_value("PowerPack Settings", "qp_update_stock", 0)
		self.assertFalse(is_feature_enabled("qp_update_stock"))

	def test_respects_explicit_enable(self):
		from cecypo_powerpack.utils import is_feature_enabled

		frappe.db.set_single_value("PowerPack Settings", "qp_update_stock", 1)
		self.assertTrue(is_feature_enabled("qp_update_stock"))

	def test_patch_backfills_default_when_never_saved(self):
		from cecypo_powerpack.patches.v1.default_qp_update_stock import execute
		from cecypo_powerpack.utils import is_feature_enabled

		frappe.db.sql(
			"""delete from `tabSingles` where doctype='PowerPack Settings' and field='qp_update_stock'"""
		)
		frappe.db.commit()

		execute()

		self.assertTrue(is_feature_enabled("qp_update_stock"))

	def test_patch_leaves_explicit_value_untouched(self):
		from cecypo_powerpack.patches.v1.default_qp_update_stock import execute
		from cecypo_powerpack.utils import is_feature_enabled

		frappe.db.set_single_value("PowerPack Settings", "qp_update_stock", 0)

		execute()

		self.assertFalse(is_feature_enabled("qp_update_stock"))


class TestGetPaymentModes(UnitTestCase):
	def setUp(self):
		frappe.db.set_single_value("PowerPack Settings", "enable_quick_pay", 1)

	def tearDown(self):
		frappe.db.set_single_value("PowerPack Settings", "enable_quick_pay", 0)

	def test_returns_three_buckets(self):
		from cecypo_powerpack.quick_pay.api import get_payment_modes

		company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
			"Company", {}, "name"
		)
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


class TestProcessQuickPay(UnitTestCase):
	def setUp(self):
		frappe.db.set_single_value("PowerPack Settings", "enable_quick_pay", 1)

	def tearDown(self):
		frappe.db.set_single_value("PowerPack Settings", "enable_quick_pay", 0)

	def test_full_payment_creates_pe_and_optional_invoice(self):
		from cecypo_powerpack.quick_pay.api import process_quick_pay
		from cecypo_powerpack.quick_pay.validators import effective_total

		so_name = frappe.db.get_value(
			"Sales Order",
			{"docstatus": 1, "per_billed": 0, "status": ["not in", ["Closed", "Cancelled"]]},
			"name",
		)
		if not so_name:
			self.skipTest("No unbilled SO available")
		so = frappe.get_doc("Sales Order", so_name)
		# Match production: outstanding is measured against the rounded
		# ceiling Payment Entry actually enforces, not the raw grand_total.
		outstanding = effective_total(so) - float(so.advance_paid or 0)
		if outstanding <= 0:
			self.skipTest("SO has no outstanding")

		mop_row = frappe.db.sql(
			"""
			SELECT parent FROM `tabMode of Payment Account`
			WHERE company = %s AND default_account IS NOT NULL LIMIT 1
		""",
			so.company,
			as_dict=True,
		)
		if not mop_row:
			self.skipTest("No MOP available")
		mop = mop_row[0]["parent"]

		token = "test-" + uuid.uuid4().hex
		payments = json.dumps(
			[
				{"type": "Cash", "amount": outstanding, "mode_of_payment": mop, "reference": ""},
			]
		)

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
		from cecypo_powerpack.quick_pay.validators import IdempotencyError, claim_idempotency_token

		token = "test-" + uuid.uuid4().hex
		# Pre-claim the token, then call should fail with IdempotencyError
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


class TestFinalizeWithInvoice(UnitTestCase):
	"""Pins the naming-series lock fix.

	The Sales Invoice stage must run *after* an explicit commit, because the
	`ACC-PAY-<year>-` row lock in `tabSeries` taken by the first `pe.insert()` is
	held by InnoDB until the transaction commits — and Sales Invoice submission
	fires a synchronous KRA eTIMS HTTPS call (30s timeout) through
	cecypo_etims_compliance's `before_submit` hook. Without the commit, every
	other Payment Entry on the site serialises behind that network round-trip.

	Nothing here touches real documents: the builders and both transaction
	boundaries are mocked, so no commit or rollback reaches the site.
	"""

	class _FakeSO:
		name = "SO-TEST-0001"
		company = "_Test Co"

		def reload(self):
			pass

	def _run(self, *, submit_invoice=1, build_raises=None, submit_raises=None, docstatus=1):
		from cecypo_powerpack.quick_pay import api

		calls = []
		si = MagicMock()
		si.name = "ACC-SINV-TEST-0001"
		si.docstatus = docstatus
		si.insert.side_effect = lambda *a, **kw: calls.append("insert")

		def fake_submit(*a, **kw):
			calls.append("submit")
			if submit_raises:
				raise submit_raises

		si.submit.side_effect = fake_submit

		def fake_build(*a, **kw):
			calls.append("build")
			if build_raises:
				raise build_raises
			return si

		result = {"success": True, "payment_entries": [{"name": "ACC-PAY-TEST-0001"}]}

		with (
			patch.object(frappe.db, "commit", side_effect=lambda: calls.append("commit")),
			patch.object(frappe.db, "rollback", side_effect=lambda **kw: calls.append("rollback")),
			patch.object(api.builders, "build_sales_invoice", side_effect=fake_build),
			patch.object(api.builders, "sync_so_party_fields", side_effect=lambda *a: calls.append("sync")),
			patch.object(api, "is_feature_enabled", return_value=False),
			patch.object(frappe, "log_error"),
		):
			api._finalize_with_invoice(self._FakeSO(), submit_invoice=submit_invoice, result=result)

		return calls, result

	def test_commit_precedes_invoice_build(self):
		"""The whole point: lock released before any invoice work starts."""
		calls, _ = self._run()
		self.assertEqual(calls[0], "commit")
		self.assertLess(calls.index("commit"), calls.index("build"))
		self.assertLess(calls.index("commit"), calls.index("submit"))

	def test_successful_invoice_reported_in_result(self):
		_, result = self._run(submit_invoice=1, docstatus=1)
		self.assertEqual(result["sales_invoice"]["name"], "ACC-SINV-TEST-0001")
		self.assertTrue(result["sales_invoice"]["submitted"])
		self.assertNotIn("invoice_error", result)

	def test_unsubmitted_invoice_reported_as_draft(self):
		calls, result = self._run(submit_invoice=0, docstatus=0)
		self.assertNotIn("submit", calls)
		self.assertFalse(result["sales_invoice"]["submitted"])

	def test_build_failure_keeps_payments_and_reports_error(self):
		"""A KRA timeout must not present as 'nothing happened' — the money was received."""
		calls, result = self._run(build_raises=frappe.ValidationError("eTIMS API timeout"))
		self.assertIn("rollback", calls)
		self.assertTrue(result["success"])
		self.assertEqual(result["payment_entries"], [{"name": "ACC-PAY-TEST-0001"}])
		self.assertIsNone(result["sales_invoice"])
		self.assertIn("invoice_error", result)

	def test_submit_failure_rolls_back_only_the_invoice(self):
		"""Rollback returns to our commit point, so the Payment Entries survive."""
		calls, result = self._run(submit_raises=frappe.ValidationError("eTIMS API timeout"))
		self.assertLess(calls.index("commit"), calls.index("rollback"))
		self.assertTrue(result["success"])
		self.assertIsNone(result["sales_invoice"])
		self.assertIn("invoice_error", result)


class TestListPendingMpesaPayments(UnitTestCase):
	"""Covers the with_count caching flag and the 3-char search gate on the
	Quick Pay - Mpesa listing.

	The shortcode lookup is mocked so the test exercises the listing logic
	without needing a full (heavily-required) Mpesa Settings fixture. Register
	rows have no required fields, so a handful can be inserted directly and
	filtered by a unique businessshortcode for exact-count assertions.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.shortcode = "TST" + uuid.uuid4().hex[:8]
		cls.company = "_Test QP Mpesa Co"
		cls.rows = []
		# full_name is derived from firstname/lastname by the register's
		# set_missing_values(), so set the name parts rather than full_name.
		specs = [
			{"firstname": "Alice", "lastname": "Wanjiru", "msisdn": "254700000001"},
			{"firstname": "Bob", "lastname": "Otieno", "msisdn": "254700000002"},
			{"firstname": "Carol", "lastname": "Njoroge", "msisdn": "254700000003"},
		]
		for spec in specs:
			doc = frappe.get_doc(
				{
					"doctype": "Mpesa C2B Payment Register",
					"businessshortcode": cls.shortcode,
					"transamount": 100,
					"transid": "QPM" + uuid.uuid4().hex[:10],
					**spec,
				}
			).insert(ignore_permissions=True)
			cls.rows.append(doc.name)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		for name in cls.rows:
			frappe.db.delete("Mpesa C2B Payment Register", {"name": name})
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		self._orig = frappe.db.get_single_value("PowerPack Settings", "enable_quick_pay_mpesa")
		frappe.db.set_single_value("PowerPack Settings", "enable_quick_pay_mpesa", 1)

	def tearDown(self):
		frappe.db.set_single_value("PowerPack Settings", "enable_quick_pay_mpesa", self._orig or 0)
		frappe.db.commit()

	def _call(self, search="", with_count=1):
		from cecypo_powerpack.quick_pay import api

		with patch.object(api, "_mpesa_shortcode_for_company", return_value=self.shortcode):
			return api.list_pending_mpesa_payments(self.company, search, with_count)

	def test_with_count_computes_total(self):
		self.assertEqual(self._call(with_count=1)["count"], 3)

	def test_with_count_zero_skips_total_but_still_searches(self):
		res = self._call(search="wanjiru", with_count=0)
		self.assertEqual(res["count"], 0)  # count skipped
		self.assertEqual(len(res["payments"]), 1)  # search still runs

	def test_with_count_accepts_string_flag(self):
		# HTTP passes whitelisted args as strings.
		self.assertEqual(self._call(with_count="0")["count"], 0)
		self.assertEqual(self._call(with_count="1")["count"], 3)

	def test_short_search_returns_no_rows_but_keeps_count(self):
		res = self._call(search="al", with_count=1)  # 2 chars < 3
		self.assertEqual(res["payments"], [])
		self.assertEqual(res["count"], 3)

	def test_search_matches_full_name(self):
		res = self._call(search="wanjiru")
		self.assertEqual({p["name"] for p in res["payments"]}, {self.rows[0]})

	def test_search_matches_transid(self):
		tid = frappe.db.get_value("Mpesa C2B Payment Register", self.rows[1], "transid")
		self.assertIn(self.rows[1], {p["name"] for p in self._call(search=tid)["payments"]})
