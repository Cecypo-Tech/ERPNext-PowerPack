from frappe.tests import UnitTestCase

from cecypo_powerpack.quick_pay.validators import (
	cap_allocation,
	compute_outstanding,
	normalize_amount,
)


class TestPrecisionNormalization(UnitTestCase):
	def test_normalize_handles_float_drift(self):
		# 0.1 + 0.2 = 0.30000000000000004 in IEEE-754
		drifted = 0.1 + 0.2
		self.assertEqual(normalize_amount(drifted, precision=2), 0.30)

	def test_normalize_passes_through_clean_values(self):
		self.assertEqual(normalize_amount(133.40, precision=2), 133.40)

	def test_compute_outstanding_rounds_to_precision(self):
		out = compute_outstanding(grand_total=133.40, advance_paid=0, precision=2)
		self.assertEqual(out, 133.40)

	def test_compute_outstanding_with_drift(self):
		# 50.10 + 83.30 = 133.40000000000003 in float
		out = compute_outstanding(grand_total=133.40, advance_paid=50.10 + 83.30 - 133.40, precision=2)
		self.assertEqual(out, 133.40)

	def test_cap_allocation_clamps_overshoot(self):
		capped = cap_allocation(amount=133.40000000000003, outstanding=133.40, precision=2)
		self.assertEqual(capped, 133.40)
		self.assertLessEqual(capped, 133.40)

	def test_cap_allocation_preserves_partial(self):
		capped = cap_allocation(amount=50.00, outstanding=133.40, precision=2)
		self.assertEqual(capped, 50.00)


import uuid

from cecypo_powerpack.quick_pay.validators import IdempotencyError, claim_idempotency_token


class TestIdempotency(UnitTestCase):
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


import frappe

from cecypo_powerpack.quick_pay.validators import preflight_stock_for_so


class TestStockPreflight(UnitTestCase):
	def test_no_stock_items_returns_empty(self):
		class FakeItem:
			item_code = "_Test Service Item QP"
			qty = 1
			warehouse = ""
			batch_no = None
			serial_no = None

		class FakeSO:
			items: list = [FakeItem()]  # noqa: RUF012

		if not frappe.db.exists("Item", "_Test Service Item QP"):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": "_Test Service Item QP",
					"item_name": "_Test Service Item QP",
					"item_group": "Services",
					"stock_uom": "Nos",
					"is_stock_item": 0,
				}
			).insert(ignore_permissions=True)
		issues = preflight_stock_for_so(FakeSO())
		self.assertEqual(issues, [])


from unittest.mock import patch

from cecypo_powerpack.quick_pay.validators import assert_can_process_quick_pay, effective_total


class TestEffectiveTotal(UnitTestCase):
	def test_prefers_rounded_total_when_set(self):
		so = frappe._dict(rounded_total=271.0, grand_total=271.44)
		self.assertEqual(effective_total(so), 271.0)

	def test_falls_back_to_grand_total_when_rounding_disabled(self):
		# disable_rounded_total sets rounded_total to 0, which is falsy
		so = frappe._dict(rounded_total=0, grand_total=271.44)
		self.assertEqual(effective_total(so), 271.44)

	def test_falls_back_to_grand_total_when_rounded_total_missing(self):
		so = frappe._dict(rounded_total=None, grand_total=271.44)
		self.assertEqual(effective_total(so), 271.44)


class TestAssertCanProcessQuickPay(UnitTestCase):
	def test_raises_when_so_write_denied(self):
		so = frappe._dict(name="SAL-ORD-TEST")
		with patch("cecypo_powerpack.quick_pay.validators.frappe.has_permission", return_value=False):
			with self.assertRaises(frappe.ValidationError):
				assert_can_process_quick_pay(so, create_invoice=False, submit_invoice=False)

	def test_passes_when_so_write_allowed_and_no_invoice_requested(self):
		so = frappe._dict(name="SAL-ORD-TEST")
		with patch("cecypo_powerpack.quick_pay.validators.frappe.has_permission", return_value=True):
			assert_can_process_quick_pay(so, create_invoice=False, submit_invoice=False)

	def test_raises_when_invoice_create_denied(self):
		so = frappe._dict(name="SAL-ORD-TEST")

		def fake_has_permission(doctype, ptype="read", *args, **kwargs):
			if doctype == "Sales Invoice" and ptype == "create":
				return False
			return True

		with patch(
			"cecypo_powerpack.quick_pay.validators.frappe.has_permission",
			side_effect=fake_has_permission,
		):
			with self.assertRaises(frappe.ValidationError):
				assert_can_process_quick_pay(so, create_invoice=True, submit_invoice=False)

	def test_raises_when_submit_not_allowed_as_owner(self):
		so = frappe._dict(name="SAL-ORD-TEST")
		with (
			patch("cecypo_powerpack.quick_pay.validators.frappe.has_permission", return_value=True),
			patch("cecypo_powerpack.quick_pay.validators._can_submit_as_owner", return_value=False),
		):
			with self.assertRaises(frappe.ValidationError):
				assert_can_process_quick_pay(so, create_invoice=True, submit_invoice=True)

	def test_passes_when_submit_allowed_as_owner(self):
		so = frappe._dict(name="SAL-ORD-TEST")
		with (
			patch("cecypo_powerpack.quick_pay.validators.frappe.has_permission", return_value=True),
			patch("cecypo_powerpack.quick_pay.validators._can_submit_as_owner", return_value=True),
		):
			assert_can_process_quick_pay(so, create_invoice=True, submit_invoice=True)
