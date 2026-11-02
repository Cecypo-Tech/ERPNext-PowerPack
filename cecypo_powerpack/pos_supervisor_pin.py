# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""Supervisor PIN for authorising a below-minimum sale at a till."""

import re

import frappe
from frappe import _

from cecypo_powerpack.pos_list_floor import PIN_FIELD


def validate_pin_format(doc, method=None):
	"""User.validate. A saved Password field reads back as asterisks; leave that alone."""
	pin = doc.get(PIN_FIELD)
	if not pin or set(pin) == {"*"}:
		return
	if not re.fullmatch(r"\d{4,6}", pin):
		frappe.throw(_("POS Supervisor PIN must be 4 to 6 digits."))
