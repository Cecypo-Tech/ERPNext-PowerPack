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
