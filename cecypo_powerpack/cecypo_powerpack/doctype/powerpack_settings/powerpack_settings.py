# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class PowerPackSettings(Document):
	def validate(self):
		"""Validate PowerPack Settings"""
		# Validate role exists if specified
		if self.sales_visible_to_role:
			if not frappe.db.exists("Role", self.sales_visible_to_role):
				frappe.throw(_("Role {0} does not exist").format(self.sales_visible_to_role))

		# Validate logical dependencies
		if any([self.show_stock_info, self.show_valuation_rate, self.show_profit_indicator,
		        self.show_last_purchase, self.show_last_sale, self.show_last_sale_to_customer]):
			if not any([self.enable_quotation_powerup, self.enable_sales_order_powerup,
			           self.enable_sales_invoice_powerup, self.enable_pos_invoice_powerup]):
				frappe.msgprint(
					_("Sales Powerup detail settings are enabled but no sales document types are enabled. "
					  "These settings will have no effect."),
					indicator="orange",
					alert=True
				)

	def on_update(self):
		"""Handle settings update"""
		# Clear specific cache keys instead of entire cache
		frappe.cache().delete_value("powerpack_settings")

		# Clear feature-specific caches
		for feature in ["enable_compact_theme", "enable_pos_powerup",
		                "enable_quotation_powerup", "enable_sales_order_powerup",
		                "enable_sales_invoice_powerup", "enable_pos_invoice_powerup",
		                "enable_item_list_powerup", "enable_duplicate_tax_id_check",
		                "prevent_etr_invoice_cancellation", "enable_warnings"]:
			frappe.cache().delete_value(f"powerpack_feature_{feature}")
