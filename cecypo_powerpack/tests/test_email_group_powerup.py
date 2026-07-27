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
        # Snapshot and restore in tearDown: frappe.response is process-global, so
        # leaving type="csv" and a CSV body in it leaks into whatever test module the
        # runner executes next in the same `bench run-tests --app` process.
        self._saved_response = dict(frappe.response)
        frappe.response.clear()
        frappe.response["docs"] = []
        # Warm the System Settings meta/cache outside the frappe.db.sql mock below:
        # frappe.utils.today() reads the site's time zone from System Settings, and on
        # a cold cache that read hits the DB. Priming it here keeps the mocked db.sql
        # call count in each test limited to the export's own query.
        frappe.utils.today()

    def tearDown(self):
        frappe.response.clear()
        frappe.response.update(self._saved_response)

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

    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.db.sql", return_value=[
        frappe._dict(
            email="+15550000@example.com",
            customer_name='=HYPERLINK("http://evil","click")',
            first_name="@SUM(1+1)",
            last_name="-2+3",
        )
    ])
    def test_formula_injection_is_neutralised(self, _sql, _perm, _flag):
        # Quoting does not stop Excel/LibreOffice evaluating a cell that starts with
        # =, +, - or @. Every one of the four columns must be defused.
        _export()
        line = frappe.response["result"].strip().splitlines()[1]
        self.assertIn("'=HYPERLINK", line)
        self.assertIn("'@SUM(1+1)", line)
        self.assertIn("'-2+3", line)
        self.assertIn("'+15550000@example.com", line)

    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.db.sql", return_value=[
        frappe._dict(email="ok@example.com", customer_name="Acme Ltd",
                     first_name="Jane", last_name="O'Brien")
    ])
    def test_ordinary_values_are_not_mangled(self, _sql, _perm, _flag):
        _export()
        line = frappe.response["result"].strip().splitlines()[1]
        self.assertIn('"Acme Ltd"', line)
        self.assertIn('"Jane"', line)
        self.assertNotIn("'Acme", line)


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
        self.suffix = frappe.generate_hash(length=8)

    def tearDown(self):
        for doctype, name in reversed(self._created):
            frappe.delete_doc(
                doctype, name, force=True, ignore_permissions=True, delete_permanently=True
            )
        frappe.db.commit()

    # --- fixture helpers -------------------------------------------------------
    # Every fixture is registered in self._created so tearDown removes it in reverse
    # creation order (children before the parents they link to).

    def _email(self, local):
        return f"{local}.{self.suffix}@example.com"

    def _mk_group(self):
        doc = frappe.get_doc(
            {"doctype": "Email Group", "title": f"_Test PowerPack Export Group {self.suffix}"}
        ).insert(ignore_permissions=True)
        self._created.append(("Email Group", doc.name))
        return doc.name

    def _mk_member(self, group, email):
        doc = frappe.get_doc(
            {"doctype": "Email Group Member", "email_group": group, "email": email}
        ).insert(ignore_permissions=True)
        self._created.append(("Email Group Member", doc.name))
        return doc.name

    def _mk_customer(self, label, email=None, first_name=None, last_name=None,
                     customer_type="Company"):
        doc = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": f"{label} {self.suffix}",
                "customer_type": customer_type,
            }
        ).insert(ignore_permissions=True)
        self._created.append(("Customer", doc.name))

        # Customer.email_id / first_name / last_name are read-only `fetch_from`
        # customer_primary_contact in this ERPNext version, so a normal .save() will not
        # persist them. Write the columns directly -- which is exactly the state migrated
        # data is in, and the state the src_rank 2 fallback arm exists to serve.
        updates = {}
        if email:
            updates["email_id"] = email
        if first_name:
            updates["first_name"] = first_name
        if last_name:
            updates["last_name"] = last_name
        if updates:
            frappe.db.set_value("Customer", doc.name, updates, update_modified=False)
        return doc.name

    def _mk_contact(self, first_name, last_name, email, customers=None, is_primary_contact=0):
        payload = {
            "doctype": "Contact",
            "first_name": first_name,
            "last_name": last_name,
            "is_primary_contact": is_primary_contact,
            "email_ids": [{"email_id": email, "is_primary": 1}],
        }
        if customers:
            payload["links"] = [
                {"link_doctype": "Customer", "link_name": c} for c in customers
            ]
        doc = frappe.get_doc(payload).insert(ignore_permissions=True)
        self._created.append(("Contact", doc.name))
        return doc.name

    def _export_rows(self, group):
        return frappe.db.sql(_EXPORT_SQL, {"email_group": group}, as_dict=True)

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
        email = self._email("jane.export")
        group = self._mk_group()
        self._mk_contact("Jane", "Wanjiru", email)
        self._mk_member(group, email)

        rows = self._export_rows(group)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].email, email)
        self.assertEqual(rows[0].first_name, "Jane")
        self.assertEqual(rows[0].last_name, "Wanjiru")

    # --- spec case: contact-sourced name wins over the customer fallback -------

    def test_contact_name_wins_over_customer_fallback(self):
        email = self._email("both")
        group = self._mk_group()
        customer = self._mk_customer(
            "_Test Acme", email=email, first_name="Stale", last_name="Fetch"
        )
        self._mk_contact("Jane", "Wanjiru", email, customers=[customer])
        self._mk_member(group, email)

        rows = self._export_rows(group)

        self.assertEqual(len(rows), 1)
        # src_rank 1 (Contact) beats src_rank 2 (Customer) for the name columns...
        self.assertEqual(rows[0].first_name, "Jane")
        self.assertEqual(rows[0].last_name, "Wanjiru")
        # ...and the linked Customer still supplies Company Name.
        self.assertEqual(rows[0].customer_name, customer)

    # --- spec case: customer fallback used when no Contact matches -------------

    def test_customer_fallback_used_when_no_contact(self):
        email = self._email("customeronly")
        group = self._mk_group()
        customer = self._mk_customer(
            "_Test Fallback Co", email=email, first_name="Peter", last_name="Kamau"
        )
        self._mk_member(group, email)

        rows = self._export_rows(group)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].customer_name, customer)
        self.assertEqual(rows[0].first_name, "Peter")
        self.assertEqual(rows[0].last_name, "Kamau")

    # --- spec case: collision -> one row, is_primary_contact wins --------------

    def test_collision_resolves_to_one_row_with_primary_contact_winning(self):
        email = self._email("collide")
        group = self._mk_group()
        self._mk_contact("Secondary", "Person", email, is_primary_contact=0)
        self._mk_contact("Primary", "Person", email, is_primary_contact=1)
        self._mk_member(group, email)

        rows = self._export_rows(group)

        self.assertEqual(len(rows), 1, "two Contacts on one email must collapse to one row")
        self.assertEqual(rows[0].first_name, "Primary")

    # --- spec case: customer_type = Individual still fills Company Name --------

    def test_individual_customer_fills_company_name(self):
        email = self._email("individual")
        group = self._mk_group()
        customer = self._mk_customer(
            "_Test Sole Trader",
            email=email,
            first_name="Asha",
            last_name="Njeri",
            customer_type="Individual",
        )
        self._mk_member(group, email)

        rows = self._export_rows(group)

        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0].customer_name,
            customer,
            "Individual customers must still populate Company Name (spec decision)",
        )

    # --- regression: a Contact match must not blank a Company Name we have -----

    def test_contact_without_customer_link_keeps_customer_company_name(self):
        """Regression: row-level precedence used to blank a recoverable Company Name.

        The Contact wins the name because it is src_rank 1, but it has no Dynamic Link
        to a Customer, so its own customer_name is NULL. A src_rank 2 Customer row
        carries the real company name for the same email. Fallback is per-field, so the
        export must take the name from the Contact and the company from the Customer,
        rather than exporting a blank Company Name.
        """
        email = self._email("nolink")
        group = self._mk_group()
        customer = self._mk_customer("_Test Acme Ltd", email=email)
        self._mk_contact("Ann", "Alpha", email)  # deliberately NOT linked to any Customer
        self._mk_member(group, email)

        rows = self._export_rows(group)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].first_name, "Ann")
        self.assertEqual(rows[0].last_name, "Alpha")
        self.assertEqual(
            rows[0].customer_name,
            customer,
            "Company Name must fall back to the Customer when the winning Contact has none",
        )

    # --- case-insensitive collapsing, proven end to end -----------------------

    def test_case_differing_addresses_collapse_to_one_resolved_row(self):
        """Proves removing LOWER() from the WHERE clauses kept dedupe case-insensitive.

        All four email columns are utf8mb4_unicode_ci so the IN (...) prefilter matches
        regardless of case, and the projected key_email is lowered so PARTITION BY and
        the final join still collapse the two spellings into one row.
        """
        upper = f"Upper.{self.suffix}@Example.COM"
        lower = upper.lower()
        group = self._mk_group()
        self._mk_contact("Case", "Insensitive", upper)
        self._mk_member(group, lower)

        rows = self._export_rows(group)

        self.assertEqual(len(rows), 1, "case-differing addresses must yield exactly one row")
        self.assertEqual(rows[0].first_name, "Case")
        self.assertEqual(rows[0].last_name, "Insensitive")

    # --- determinism when one Contact links to more than one Customer ---------

    def test_multi_customer_contact_picks_the_same_company_every_run(self):
        email = self._email("multilink")
        group = self._mk_group()
        c1 = self._mk_customer("_Test Alpha Co", customer_type="Company")
        c2 = self._mk_customer("_Test Beta Co", customer_type="Company")
        self._mk_contact("Multi", "Linked", email, customers=[c1, c2])
        self._mk_member(group, email)

        picks = {self._export_rows(group)[0].customer_name for _ in range(5)}

        self.assertEqual(len(picks), 1, f"non-deterministic company pick across runs: {picks}")
        self.assertIn(picks.pop(), {c1, c2})
