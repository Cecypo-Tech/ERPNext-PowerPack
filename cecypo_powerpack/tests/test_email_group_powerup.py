# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

import unittest
from unittest.mock import MagicMock, patch

import frappe

from cecypo_powerpack.api import _EXPORT_SQL


def _run(email_group="TestGroup", filter_type="Item", filter_value="ITEM-001"):
    from cecypo_powerpack.api import import_email_group_subscribers_by_item
    return import_email_group_subscribers_by_item(email_group, filter_type, filter_value)


def _find_sql_call(mock_sql, needle):
    """Return the first mocked frappe.db.sql call whose SQL text contains `needle`.

    Guards against a false pass when a later, unrelated frappe.db.sql call (e.g. a
    metadata lookup) becomes `call_args` (the *last* call) instead of the query under
    test. Raises with a clear message if no call matches, rather than silently
    asserting against the wrong query.
    """
    for call in mock_sql.call_args_list:
        sql = call.args[0] if call.args else None
        if isinstance(sql, str) and needle in sql:
            return sql
    raise AssertionError(f"No frappe.db.sql call contained {needle!r}")


def _get_export_sql_call(mock_sql):
    """Return the mocked frappe.db.sql call whose first positional arg *is* _EXPORT_SQL.

    Identity comparison against the module-level constant, rather than a positional
    call_args[0][0] lookup, so this can never bind to the wrong query even if a future
    change adds another frappe.db.sql call to the export path.
    """
    for call in mock_sql.call_args_list:
        if call.args and call.args[0] is _EXPORT_SQL:
            return call.args[0]
    raise AssertionError("_EXPORT_SQL was not passed to frappe.db.sql")


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
    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    def test_import_by_item(self, _flag, mock_sql, mock_get_doc, _perm):
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
    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    def test_import_by_item_group(self, _flag, mock_sql, mock_get_doc, _perm):
        _wire_get_doc(mock_get_doc, _make_eg(total=1))
        result = _run(filter_type="Item Group", filter_value="Electronics")
        self.assertEqual(result["added"], 1)
        sql_query = mock_sql.call_args[0][0]
        self.assertIn("item_group = %(filter_value)s", sql_query)

    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.get_doc")
    @patch("frappe.db.sql", return_value=[frappe._dict(email_id="a@example.com")])
    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    def test_no_duplicate_on_reimport(self, _flag, mock_sql, mock_get_doc, _perm):
        _wire_get_doc(mock_get_doc, _make_eg(total=1), member_side_effect=frappe.UniqueValidationError)
        result = _run()
        self.assertEqual(result["added"], 0)

    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.get_doc")
    @patch("frappe.db.sql", return_value=[frappe._dict(email_id="a@example.com")])
    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    def test_unsubscribed_flag_preserved(self, _flag, mock_sql, mock_get_doc, _perm):
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
    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    def test_draft_invoice_excluded(self, _flag, mock_sql, mock_get_doc, _perm):
        _wire_get_doc(mock_get_doc, _make_eg(total=0))
        result = _run()
        self.assertEqual(result["added"], 0)
        sql_query = mock_sql.call_args[0][0]
        self.assertIn("docstatus = 1", sql_query)

    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.get_doc")
    @patch("frappe.db.sql", return_value=[])
    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    def test_no_email_customer_excluded(self, _flag, mock_sql, mock_get_doc, _perm):
        _wire_get_doc(mock_get_doc, _make_eg(total=0))
        _run()
        sql_query = mock_sql.call_args[0][0]
        self.assertIn("email_id IS NOT NULL", sql_query)
        self.assertIn("email_id != ''", sql_query)

    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.get_doc")
    @patch("frappe.db.sql", return_value=[])
    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    def test_empty_result_returns_zero(self, _flag, mock_sql, mock_get_doc, _perm):
        _wire_get_doc(mock_get_doc, _make_eg(total=0))
        result = _run()
        self.assertEqual(result["added"], 0)

    @patch("frappe.has_permission", return_value=False)
    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    def test_permission_check(self, _flag, _perm):
        with self.assertRaises(frappe.PermissionError):
            _run()


class TestImportContactSources(unittest.TestCase):

    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.get_doc")
    @patch("frappe.db.sql", return_value=[])
    def test_query_reads_contact_email_child_table(self, mock_sql, mock_get_doc, _perm, _flag):
        _wire_get_doc(mock_get_doc, _make_eg(total=0))
        _run()
        sql = _find_sql_call(mock_sql, "tabSales Invoice Item")
        self.assertIn("tabContact Email", sql)

    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.get_doc")
    @patch("frappe.db.sql", return_value=[])
    def test_query_joins_contacts_via_dynamic_link(self, mock_sql, mock_get_doc, _perm, _flag):
        _wire_get_doc(mock_get_doc, _make_eg(total=0))
        _run()
        sql = _find_sql_call(mock_sql, "tabSales Invoice Item")
        self.assertIn("tabDynamic Link", sql)
        self.assertIn("link_doctype = 'Customer'", sql)

    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.get_doc")
    @patch("frappe.db.sql", return_value=[
        frappe._dict(email_id="a@example.com"),
    ])
    def test_email_from_multiple_sources_inserted_once(self, mock_sql, mock_get_doc, _perm, _flag):
        # DISTINCT in SQL collapses duplicates; one row in => one insert.
        _wire_get_doc(mock_get_doc, _make_eg(total=1))
        result = _run()
        self.assertEqual(result["added"], 1)
        sql = _find_sql_call(mock_sql, "tabSales Invoice Item")
        self.assertIn("DISTINCT", sql)


class TestEmailGroupFeatureFlag(unittest.TestCase):

    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=False)
    @patch("frappe.has_permission", return_value=True)
    def test_import_throws_when_feature_disabled(self, _perm, _flag):
        with self.assertRaises(frappe.ValidationError):
            _run()


def _export(email_group="TestGroup"):
    from cecypo_powerpack.api import export_email_group_csv
    return export_email_group_csv(email_group)


class TestExportEmailGroupCsv(unittest.TestCase):

    def setUp(self):
        frappe.response.clear()
        frappe.response["docs"] = []
        # Warm the System Settings meta/cache outside the frappe.db.sql mock below:
        # frappe.utils.today() reads the site's time zone from System Settings, and on
        # a cold cache that read hits the DB. Priming it here keeps the mocked db.sql
        # call count in each test limited to the export's own query.
        frappe.utils.today()

    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.db.sql", return_value=[])
    def test_headers_are_zoho_field_names(self, _sql, _perm, _flag):
        _export()
        rows = frappe.response["result"]
        self.assertIn("Company Name", rows)
        self.assertIn("First Name", rows)
        self.assertIn("Last Name", rows)
        self.assertIn("Contact Email", rows)

    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.db.sql", return_value=[])
    def test_empty_group_returns_headers_only(self, _sql, _perm, _flag):
        _export()
        self.assertEqual(frappe.response["type"], "csv")
        # One header line; allow a trailing newline.
        self.assertEqual(len(frappe.response["result"].strip().splitlines()), 1)

    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.db.sql", return_value=[
        frappe._dict(
            email="jane@acme.co.ke", customer_name="Acme Ltd",
            first_name="Jane", last_name="Wanjiru",
        )
    ])
    def test_row_maps_columns_in_order(self, _sql, _perm, _flag):
        _export()
        line = frappe.response["result"].strip().splitlines()[1]
        self.assertIn("Acme Ltd", line)
        self.assertIn("Jane", line)
        self.assertIn("Wanjiru", line)
        self.assertIn("jane@acme.co.ke", line)
        self.assertLess(line.index("Acme Ltd"), line.index("jane@acme.co.ke"))

    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.db.sql", return_value=[
        frappe._dict(email="ghost@example.com", customer_name=None,
                     first_name=None, last_name=None)
    ])
    def test_unresolved_email_exports_with_blank_names(self, _sql, _perm, _flag):
        _export()
        lines = frappe.response["result"].strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("ghost@example.com", lines[1])
        self.assertNotIn("None", lines[1])

    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.db.sql", return_value=[])
    def test_query_excludes_unsubscribed(self, mock_sql, _perm, _flag):
        _export()
        sql = _get_export_sql_call(mock_sql)
        self.assertIn("unsubscribed = 0", sql)

    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.db.sql", return_value=[])
    def test_query_picks_one_row_per_email(self, mock_sql, _perm, _flag):
        _export()
        sql = _get_export_sql_call(mock_sql)
        self.assertIn("ROW_NUMBER()", sql)
        self.assertIn("PARTITION BY key_email", sql)
        self.assertIn("is_primary_contact DESC", sql)

    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=False)
    @patch("frappe.has_permission", return_value=True)
    def test_throws_when_feature_disabled(self, _perm, _flag):
        with self.assertRaises(frappe.ValidationError):
            _export()

    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    @patch("frappe.has_permission", return_value=False)
    def test_throws_without_email_group_read(self, _perm, _flag):
        with self.assertRaises(frappe.PermissionError):
            _export()

    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    def test_throws_without_customer_read(self, _flag):
        def perms(doctype, ptype="read", doc=None, *a, **kw):
            return doctype != "Customer"

        with patch("frappe.has_permission", side_effect=perms):
            with self.assertRaises(frappe.PermissionError):
                _export()


class TestExportSqlExecutes(unittest.TestCase):
    """Executes the real export SQL. Mock-based tests cannot catch SQL errors.

    Every test in TestExportEmailGroupCsv above mocks frappe.db.sql, so a syntax
    error, a wrong column name, or an unsupported construct in _EXPORT_SQL would
    ship completely undetected. These two tests run the real statement against the
    test database instead.

    Fixtures use unique throwaway names and are deleted explicitly in tearDown
    (rather than relying on frappe.db.rollback()) because this is a plain
    unittest.TestCase, not FrappeTestCase, so bench's test runner does not
    automatically wrap each test in a transaction/savepoint that gets rolled back.
    """

    def setUp(self):
        self._created = []  # list of (doctype, name), deleted in reverse order

    def tearDown(self):
        for doctype, name in reversed(self._created):
            frappe.delete_doc(
                doctype, name, force=True, ignore_permissions=True, delete_permanently=True
            )
        frappe.db.commit()

    def test_export_sql_runs_against_database(self):
        # No fixtures needed: an Email Group that does not exist yields zero rows,
        # which still fully parses, plans and executes the statement.
        rows = frappe.db.sql(
            _EXPORT_SQL,
            {"email_group": "__cecypo_nonexistent_group__"},
            as_dict=True,
        )
        self.assertEqual(rows, [])

    def test_export_sql_resolves_a_real_contact(self):
        suffix = frappe.generate_hash(length=8)
        email = f"jane.export.{suffix}@example.com"

        group = frappe.get_doc(
            {"doctype": "Email Group", "title": f"_Test PowerPack Export Group {suffix}"}
        ).insert(ignore_permissions=True)
        self._created.append(("Email Group", group.name))

        contact = frappe.get_doc(
            {
                "doctype": "Contact",
                "first_name": "Jane",
                "last_name": "Wanjiru",
                "email_ids": [{"email_id": email, "is_primary": 1}],
            }
        ).insert(ignore_permissions=True)
        self._created.append(("Contact", contact.name))

        member = frappe.get_doc(
            {"doctype": "Email Group Member", "email_group": group.name, "email": email}
        ).insert(ignore_permissions=True)
        self._created.append(("Email Group Member", member.name))

        rows = frappe.db.sql(_EXPORT_SQL, {"email_group": group.name}, as_dict=True)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].email, email)
        self.assertEqual(rows[0].first_name, "Jane")
        self.assertEqual(rows[0].last_name, "Wanjiru")
