# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt
"""A Sales Invoice return keeps the original sale's tax_id.

Sales Invoice.tax_id is fetched from Customer.tax_id on every draft save, BEFORE validate
hooks run. Walk-in sales use a shared Cash Sale customer with a blank tax_id, so a return made
from the desk Return button lost the buyer's PIN (Sayona CS-X-26-00010, 2026-10-20). The hook
fills a blank tax_id from return_against and never overwrites one that is already set.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from cecypo_powerpack.validations import carry_return_tax_id


def _return_doc(**fields):
	doc = frappe.new_doc("Sales Invoice")
	doc.update({"is_return": 1, "return_against": "CS-26-02929", "tax_id": None, **fields})
	return doc


class TestCarryReturnTaxId(FrappeTestCase):
	def test_blank_tax_id_on_a_return_is_copied_from_the_original(self):
		doc = _return_doc()
		with patch("cecypo_powerpack.validations.frappe.db.get_value", return_value="P051716963V") as gv:
			carry_return_tax_id(doc)
		gv.assert_called_once_with("Sales Invoice", "CS-26-02929", "tax_id")
		self.assertEqual(doc.tax_id, "P051716963V")

	def test_an_existing_tax_id_is_left_alone(self):
		doc = _return_doc(tax_id="A006261858S")
		with patch("cecypo_powerpack.validations.frappe.db.get_value") as gv:
			carry_return_tax_id(doc)
		gv.assert_not_called()
		self.assertEqual(doc.tax_id, "A006261858S")

	def test_a_normal_sale_is_not_touched(self):
		doc = _return_doc(is_return=0, return_against=None)
		with patch("cecypo_powerpack.validations.frappe.db.get_value") as gv:
			carry_return_tax_id(doc)
		gv.assert_not_called()
		self.assertIsNone(doc.tax_id)

	def test_an_original_without_tax_id_leaves_the_return_blank(self):
		doc = _return_doc()
		with patch("cecypo_powerpack.validations.frappe.db.get_value", return_value=None):
			carry_return_tax_id(doc)
		self.assertIsNone(doc.tax_id)
