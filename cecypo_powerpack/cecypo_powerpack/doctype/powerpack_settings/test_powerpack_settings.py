# Copyright (c) 2024, Cecypo.Tech and Contributors
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

	def test_quotation_tweaks_feature(self):
		"""Test the quotation tweaks feature toggle"""
		from cecypo_powerpack.utils import is_feature_enabled

		settings = frappe.get_single("PowerPack Settings")
		settings.enable_quotation_tweaks = 1
		settings.save()

		self.assertTrue(is_feature_enabled("enable_quotation_tweaks"))

		settings.enable_quotation_tweaks = 0
		settings.save()

		self.assertFalse(is_feature_enabled("enable_quotation_tweaks"))
