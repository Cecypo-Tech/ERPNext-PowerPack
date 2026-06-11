# cecypo_powerpack/tests/test_email_group_powerup.py
import unittest
from unittest.mock import MagicMock, patch

import frappe


def _run(email_group="TestGroup", filter_type="Item", filter_value="ITEM-001"):
    from cecypo_powerpack.api import import_email_group_subscribers_by_item
    return import_email_group_subscribers_by_item(email_group, filter_type, filter_value)


def _make_eg(total=1):
    eg = MagicMock()
    eg.update_total_subscribers.return_value = total
    return eg


def _wire_get_doc(mock_get_doc, eg, member_side_effect=None):
    def side(data_or_type, name=None):
        if isinstance(data_or_type, dict):
            m = MagicMock()
            if member_side_effect:
                m.insert.side_effect = member_side_effect
            return m
        return eg
    mock_get_doc.side_effect = side


class TestImportEmailGroupSubscribersByItem(unittest.TestCase):

    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.get_doc")
    @patch("frappe.db.sql", return_value=[frappe._dict(email_id="a@example.com")])
    def test_import_by_item(self, mock_sql, mock_get_doc, _perm):
        _wire_get_doc(mock_get_doc, _make_eg(total=1))
        result = _run()
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["total"], 1)
        sql_query = mock_sql.call_args[0][0]
        self.assertIn("sii.item_code = %(filter_value)s", sql_query)
        self.assertIn("docstatus = 1", sql_query)

    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.get_doc")
    @patch("frappe.db.sql", return_value=[frappe._dict(email_id="a@example.com")])
    def test_import_by_item_group(self, mock_sql, mock_get_doc, _perm):
        _wire_get_doc(mock_get_doc, _make_eg(total=1))
        result = _run(filter_type="Item Group", filter_value="Electronics")
        self.assertEqual(result["added"], 1)
        sql_query = mock_sql.call_args[0][0]
        self.assertIn("item_group = %(filter_value)s", sql_query)

    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.get_doc")
    @patch("frappe.db.sql", return_value=[frappe._dict(email_id="a@example.com")])
    def test_no_duplicate_on_reimport(self, mock_sql, mock_get_doc, _perm):
        _wire_get_doc(mock_get_doc, _make_eg(total=1), member_side_effect=frappe.UniqueValidationError)
        result = _run()
        self.assertEqual(result["added"], 0)

    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.get_doc")
    @patch("frappe.db.sql", return_value=[frappe._dict(email_id="a@example.com")])
    def test_unsubscribed_flag_preserved(self, mock_sql, mock_get_doc, _perm):
        eg = _make_eg()
        captured = []

        def side(data_or_type, name=None):
            if isinstance(data_or_type, dict) and data_or_type.get("doctype") == "Email Group Member":
                captured.append(dict(data_or_type))
                return MagicMock()
            return eg

        mock_get_doc.side_effect = side
        _run()
        self.assertTrue(captured, "Expected at least one Email Group Member doc to be created")
        self.assertNotIn("unsubscribed", captured[0])

    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.get_doc")
    @patch("frappe.db.sql", return_value=[])
    def test_draft_invoice_excluded(self, mock_sql, mock_get_doc, _perm):
        _wire_get_doc(mock_get_doc, _make_eg(total=0))
        result = _run()
        self.assertEqual(result["added"], 0)
        sql_query = mock_sql.call_args[0][0]
        self.assertIn("docstatus = 1", sql_query)

    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.get_doc")
    @patch("frappe.db.sql", return_value=[])
    def test_no_email_customer_excluded(self, mock_sql, mock_get_doc, _perm):
        _wire_get_doc(mock_get_doc, _make_eg(total=0))
        _run()
        sql_query = mock_sql.call_args[0][0]
        self.assertIn("email_id IS NOT NULL", sql_query)
        self.assertIn("email_id != ''", sql_query)

    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.get_doc")
    @patch("frappe.db.sql", return_value=[])
    def test_empty_result_returns_zero(self, mock_sql, mock_get_doc, _perm):
        _wire_get_doc(mock_get_doc, _make_eg(total=0))
        result = _run()
        self.assertEqual(result["added"], 0)

    @patch("frappe.has_permission", return_value=False)
    def test_permission_check(self, _perm):
        with self.assertRaises(frappe.PermissionError):
            _run()
