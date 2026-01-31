# Copyright (c) 2024, Cecypo.Tech and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PowerPackSettings(Document):
	def validate(self):
		"""Validate PowerPack Settings"""
		pass

	def on_update(self):
		"""Handle settings update"""
		# Clear cache when settings are updated
		frappe.clear_cache()
