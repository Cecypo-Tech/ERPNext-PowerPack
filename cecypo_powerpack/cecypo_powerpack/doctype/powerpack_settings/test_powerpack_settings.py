# Copyright (c) 2026, Cecypo.Tech and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestPowerPackSettings(FrappeTestCase):
	def test_powerpack_settings_creation(self):
		"""Test that PowerPack Settings can be created and saved"""
		settings = frappe.get_single("PowerPack Settings")
		settings.enable_pos_powerup = 1
		settings.save()

		# Reload and verify
		settings.reload()
		self.assertEqual(settings.enable_pos_powerup, 1)

	def test_feature_check_utility(self):
		"""Test the is_feature_enabled utility function"""
		from cecypo_powerpack.utils import is_feature_enabled

		settings = frappe.get_single("PowerPack Settings")
		settings.enable_pos_powerup = 1
		settings.save()

		self.assertTrue(is_feature_enabled("enable_pos_powerup"))

		settings.enable_pos_powerup = 0
		settings.save()

		self.assertFalse(is_feature_enabled("enable_pos_powerup"))

	def test_quotation_powerup_feature(self):
		"""Test the quotation powerup feature toggle"""
		from cecypo_powerpack.utils import is_feature_enabled

		settings = frappe.get_single("PowerPack Settings")
		settings.enable_quotation_powerup = 1
		settings.save()

		self.assertTrue(is_feature_enabled("enable_quotation_powerup"))

		settings.enable_quotation_powerup = 0
		settings.save()

		self.assertFalse(is_feature_enabled("enable_quotation_powerup"))

	def test_role_validation(self):
		"""Test that invalid role throws error"""
		settings = frappe.get_single("PowerPack Settings")
		settings.sales_visible_to_role = "NonExistentRole123"

		with self.assertRaises(frappe.ValidationError):
			settings.save()

	def test_bulk_selection_features(self):
		"""Test bulk selection feature toggles"""
		from cecypo_powerpack.utils import is_feature_enabled

		settings = frappe.get_single("PowerPack Settings")
		settings.enable_quotation_bulk_selection = 1
		settings.enable_sales_order_bulk_selection = 1
		settings.enable_sales_invoice_bulk_selection = 1
		settings.save()

		self.assertTrue(is_feature_enabled("enable_quotation_bulk_selection"))
		self.assertTrue(is_feature_enabled("enable_sales_order_bulk_selection"))
		self.assertTrue(is_feature_enabled("enable_sales_invoice_bulk_selection"))
