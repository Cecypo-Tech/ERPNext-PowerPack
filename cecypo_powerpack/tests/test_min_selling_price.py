# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestMinSellingPriceScaffold(FrappeTestCase):
	def test_child_doctype_exists(self):
		self.assertTrue(frappe.db.exists("DocType", "Minimum Selling Price Rule"))
		meta = frappe.get_meta("Minimum Selling Price Rule")
		self.assertTrue(meta.istable)
		self.assertEqual(
			{"item_group", "basis", "floor_percent"},
			{df.fieldname for df in meta.fields},
		)


class TestMinSellingPriceSettings(FrappeTestCase):
	def test_settings_fields_exist(self):
		meta = frappe.get_meta("PowerPack Settings")
		names = {df.fieldname for df in meta.fields}
		for fn in (
			"min_selling_price_section",
			"enable_min_selling_price",
			"min_selling_price_default_basis",
			"min_selling_price_default_percent",
			"min_selling_price_override_role",
			"min_selling_price_rules",
		):
			self.assertIn(fn, names)

	def test_feature_flag_toggles(self):
		from cecypo_powerpack.utils import is_feature_enabled

		s = frappe.get_single("PowerPack Settings")
		s.enable_min_selling_price = 1
		s.save()
		frappe.clear_cache(doctype="PowerPack Settings")
		self.assertTrue(is_feature_enabled("enable_min_selling_price"))

		s.enable_min_selling_price = 0
		s.save()
		frappe.clear_cache(doctype="PowerPack Settings")
		self.assertFalse(is_feature_enabled("enable_min_selling_price"))
