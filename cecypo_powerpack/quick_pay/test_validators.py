from frappe.tests import UnitTestCase

from cecypo_powerpack.quick_pay.validators import (
	normalize_amount,
	compute_outstanding,
	cap_allocation,
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
