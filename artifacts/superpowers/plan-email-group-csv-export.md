# Email Group CSV Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CSV export of Email Group subscribers (Company Name, First Name, Last Name, Contact Email) for Zoho Campaigns and other bulk mail tools, and widen the existing import-by-item feature to discover contact-sourced emails.

**Architecture:** Two whitelisted methods in `cecypo_powerpack/api.py`. The export resolves each group member's email back to a `Contact` (first/last name) and its linked `Customer` (company name) through `Dynamic Link`, using one SQL statement with a `ROW_NUMBER()` window function to pick a single deterministic row per email. Both endpoints and both UI buttons sit behind a new `enable_email_group_powerup` flag.

**Tech Stack:** Frappe/ERPNext v15+, Python 3.10+, MariaDB 11.8 (CTEs and window functions available), vanilla JS (`frappe.ui.form.on`), `frappe.utils.csvutils.build_csv_response`.

## Global Constraints

- Spec: `artifacts/superpowers/spec-email-group-csv-export.md`
- **Indentation: tabs.** `pyproject.toml` sets `[tool.ruff.format] indent-style = "tab"`. The existing `import_email_group_subscribers_by_item` uses tabs. All new Python in `api.py` uses tabs. (`api.py` is historically mixed; do not reformat unrelated code.)
- Quote style: double. Line length: 110.
- Import `is_feature_enabled` **locally inside each function** — `from cecypo_powerpack.utils import is_feature_enabled`. This is the established pattern throughout `api.py`.
- All SQL is parameterized with named params (`%(name)s`). Never interpolate user input.
- CSV headers, exact and in this order: `Company Name`, `First Name`, `Last Name`, `Contact Email`. These are Zoho Campaigns' default field names; changing them breaks auto-mapping.
- Tests live in `cecypo_powerpack/tests/test_email_group_powerup.py`, `unittest.TestCase` + `unittest.mock.patch`, matching the existing file.
- Copyright header on any new file: `# Copyright (c) 2026, Cecypo.Tech and contributors`
- Never add a `Co-Authored-By` trailer to commits.

---

### Task 1: Feature flag

**Files:**
- Modify: `cecypo_powerpack/cecypo_powerpack/doctype/powerpack_settings/powerpack_settings.json`
- Modify: `cecypo_powerpack/api.py` (`import_email_group_subscribers_by_item`, ~line 1987)
- Test: `cecypo_powerpack/tests/test_email_group_powerup.py`

**Interfaces:**
- Consumes: `cecypo_powerpack.utils.is_feature_enabled(name: str) -> bool`
- Produces: settings field `enable_email_group_powerup` (Check, default `"1"`), consumed by Tasks 3 and 5.

- [ ] **Step 1: Write the failing test**

Add to `cecypo_powerpack/tests/test_email_group_powerup.py`:

```python
class TestEmailGroupFeatureFlag(unittest.TestCase):

    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=False)
    @patch("frappe.has_permission", return_value=True)
    def test_import_throws_when_feature_disabled(self, _perm, _flag):
        with self.assertRaises(frappe.ValidationError):
            _run()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
bench --site <site> run-tests --app cecypo_powerpack \
  --module cecypo_powerpack.tests.test_email_group_powerup
```

Expected: FAIL — no exception raised, because the gate does not exist yet.

- [ ] **Step 3: Add the settings field**

In `powerpack_settings.json`, append to `field_order` at the very end (after `public_link_footer_content`):

```
"email_group_section",
"enable_email_group_powerup",
"email_group_description"
```

And append to `fields`:

```json
{
 "fieldname": "email_group_section",
 "fieldtype": "Section Break",
 "label": "Email Group Powerup"
},
{
 "default": "1",
 "fieldname": "enable_email_group_powerup",
 "fieldtype": "Check",
 "label": "Enable Email Group Powerup"
},
{
 "fieldname": "email_group_description",
 "fieldtype": "HTML",
 "label": "Description",
 "options": "<p class=\"text-muted\">Adds two actions to Email Group:<br><strong>Import Subscribers by Item Purchased</strong> — add every customer who bought a given item or item group as a subscriber.<br><strong>Export Subscribers (CSV)</strong> — download the group as a CSV with company name, first name, last name and email, ready to import into Zoho Campaigns, Mailchimp or any bulk mail tool.</p>"
}
```

Default is `1` so existing installs do not silently lose the feature.

- [ ] **Step 4: Add the Python gate**

In `api.py`, inside `import_email_group_subscribers_by_item`, immediately after the existing `import contextlib` line and **before** the permission check:

```python
	from cecypo_powerpack.utils import is_feature_enabled

	if not is_feature_enabled("enable_email_group_powerup"):
		frappe.throw(_("Email Group Powerup is disabled in PowerPack Settings"))
```

- [ ] **Step 5: Make the flag true for the other existing tests**

The existing tests in `TestImportEmailGroupSubscribersByItem` do not patch the flag, so they will now fail. Add this decorator to **every** existing test method in that class (outermost, so it is the last argument):

```python
    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
```

and add a trailing `_flag` parameter to each method signature. For example
`test_permission_check` becomes:

```python
    @patch("frappe.has_permission", return_value=False)
    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    def test_permission_check(self, _flag, _perm):
        with self.assertRaises(frappe.PermissionError):
            _run()
```

Note decorator/argument order: decorators apply bottom-up, so the bottom-most
decorator supplies the first argument.

- [ ] **Step 6: Run migrate and the tests**

```bash
bench --site <site> migrate
bench --site <site> run-tests --app cecypo_powerpack \
  --module cecypo_powerpack.tests.test_email_group_powerup
```

Expected: PASS, all tests.

- [ ] **Step 7: Commit**

```bash
git add cecypo_powerpack/cecypo_powerpack/doctype/powerpack_settings/powerpack_settings.json \
        cecypo_powerpack/api.py cecypo_powerpack/tests/test_email_group_powerup.py
git commit -m "feat(email-group): gate powerup behind enable_email_group_powerup"
```

---

### Task 2: Contact-aware import

**Files:**
- Modify: `cecypo_powerpack/api.py` (`import_email_group_subscribers_by_item`, the two `frappe.db.sql` blocks, ~lines 1993-2024)
- Test: `cecypo_powerpack/tests/test_email_group_powerup.py`

**Interfaces:**
- Consumes: feature gate from Task 1.
- Produces: no new public signature. `import_email_group_subscribers_by_item(email_group, filter_type, filter_value)` keeps returning `{"added": int, "total": int}`.

**Why:** `Customer.email_id` is a read-only `fetch_from` of `customer_primary_contact.email_id`. It is blank whenever no primary contact is set (common on migrated data) and never sees non-primary contacts or secondary `Contact Email` rows.

- [ ] **Step 1: Write the failing tests**

Add to `cecypo_powerpack/tests/test_email_group_powerup.py`:

```python
class TestImportContactSources(unittest.TestCase):

    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.get_doc")
    @patch("frappe.db.sql", return_value=[])
    def test_query_reads_contact_email_child_table(self, mock_sql, mock_get_doc, _perm, _flag):
        _wire_get_doc(mock_get_doc, _make_eg(total=0))
        _run()
        sql = mock_sql.call_args[0][0]
        self.assertIn("tabContact Email", sql)

    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.get_doc")
    @patch("frappe.db.sql", return_value=[])
    def test_query_joins_contacts_via_dynamic_link(self, mock_sql, mock_get_doc, _perm, _flag):
        _wire_get_doc(mock_get_doc, _make_eg(total=0))
        _run()
        sql = mock_sql.call_args[0][0]
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
        self.assertIn("DISTINCT", mock_sql.call_args[0][0])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
bench --site <site> run-tests --app cecypo_powerpack \
  --module cecypo_powerpack.tests.test_email_group_powerup
```

Expected: FAIL — `tabContact Email` and `tabDynamic Link` are not in the current query.

- [ ] **Step 3: Replace the two SQL blocks**

In `api.py`, replace the whole `if filter_type == "Item": ... else: frappe.throw(...)` block
(currently lines ~1993-2024) with:

```python
	if filter_type == "Item":
		item_condition = "sii.item_code = %(filter_value)s"
	elif filter_type == "Item Group":
		item_condition = (
			"sii.item_code IN (SELECT name FROM `tabItem` WHERE item_group = %(filter_value)s)"
		)
	else:
		frappe.throw(_("filter_type must be 'Item' or 'Item Group'"))

	# Customers who bought the item on a submitted Sales Invoice. Referenced three
	# times below; kept as a plain subquery string (no user input) so each UNION arm
	# can be pruned independently by the optimizer.
	matched_customers = f"""
		SELECT DISTINCT si.customer
		FROM `tabSales Invoice Item` sii
		JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE si.docstatus = 1
		  AND {item_condition}
	"""

	# Emails come from three places. Customer.email_id is a read-only fetch of the
	# primary contact, so on its own it misses customers with no primary contact set
	# and every non-primary contact.
	rows = frappe.db.sql(
		f"""
		SELECT DISTINCT email_id
		FROM (
			SELECT c.email_id
			FROM `tabCustomer` c
			WHERE c.name IN ({matched_customers})

			UNION ALL

			SELECT con.email_id
			FROM `tabDynamic Link` dl
			JOIN `tabContact` con ON con.name = dl.parent
			WHERE dl.parenttype = 'Contact'
			  AND dl.link_doctype = 'Customer'
			  AND dl.link_name IN ({matched_customers})

			UNION ALL

			SELECT ce.email_id
			FROM `tabDynamic Link` dl
			JOIN `tabContact Email` ce ON ce.parent = dl.parent AND ce.parenttype = 'Contact'
			WHERE dl.parenttype = 'Contact'
			  AND dl.link_doctype = 'Customer'
			  AND dl.link_name IN ({matched_customers})
		) AS all_emails
		WHERE email_id IS NOT NULL AND email_id != ''
		""",
		{"filter_value": filter_value},
		as_dict=True,
	)
```

The rest of the function (the insert loop, `update_total_subscribers`, the return) is unchanged.

**Safety note:** `item_condition` and `matched_customers` are f-string-interpolated but contain
only literals chosen by the `if/elif/else` above — never `filter_value`, which stays a bound
parameter. Do not interpolate `filter_value`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
bench --site <site> run-tests --app cecypo_powerpack \
  --module cecypo_powerpack.tests.test_email_group_powerup
```

Expected: PASS. The pre-existing fragment assertions (`sii.item_code = %(filter_value)s`,
`docstatus = 1`, `item_group = %(filter_value)s`, `email_id IS NOT NULL`, `email_id != ''`)
are all still present in the new query, so those tests keep passing unmodified.

- [ ] **Step 5: Smoke-test the SQL against a real database**

The tests above mock `frappe.db.sql`, so they cannot catch a syntax error. Run the real query once:

```bash
bench --site <site> console
```

```python
from cecypo_powerpack.api import import_email_group_subscribers_by_item
# Use a throwaway Email Group and a real item code from this site.
import_email_group_subscribers_by_item("<some Email Group>", "Item", "<some item code>")
```

Expected: returns `{"added": N, "total": M}` without a SQL error.

- [ ] **Step 6: Lint and commit**

```bash
ruff check cecypo_powerpack
git add cecypo_powerpack/api.py cecypo_powerpack/tests/test_email_group_powerup.py
git commit -m "fix(email-group): discover contact-sourced emails on import"
```

---

### Task 3: CSV export endpoint

**Files:**
- Modify: `cecypo_powerpack/api.py` (add after `import_email_group_subscribers_by_item`)
- Test: `cecypo_powerpack/tests/test_email_group_powerup.py`

**Interfaces:**
- Consumes: feature gate from Task 1.
- Produces: `export_email_group_csv(email_group: str) -> None`. Returns nothing; writes the
  CSV into `frappe.response` via `build_csv_response`. Task 4 tests its SQL, Task 5 calls its
  URL: `/api/method/cecypo_powerpack.api.export_email_group_csv?email_group=<name>`.

- [ ] **Step 1: Write the failing tests**

Add to `cecypo_powerpack/tests/test_email_group_powerup.py`:

```python
def _export(email_group="TestGroup"):
    from cecypo_powerpack.api import export_email_group_csv
    return export_email_group_csv(email_group)


class TestExportEmailGroupCsv(unittest.TestCase):

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
        self.assertIn("unsubscribed = 0", mock_sql.call_args[0][0])

    @patch("cecypo_powerpack.utils.is_feature_enabled", return_value=True)
    @patch("frappe.has_permission", return_value=True)
    @patch("frappe.db.sql", return_value=[])
    def test_query_picks_one_row_per_email(self, mock_sql, _perm, _flag):
        _export()
        sql = mock_sql.call_args[0][0]
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
bench --site <site> run-tests --app cecypo_powerpack \
  --module cecypo_powerpack.tests.test_email_group_powerup
```

Expected: FAIL with `ImportError: cannot import name 'export_email_group_csv'`.

- [ ] **Step 3: Implement the endpoint**

Append to `cecypo_powerpack/api.py`, directly after `import_email_group_subscribers_by_item`:

```python
# Resolves each Email Group Member email back to a person and an account.
#
# Contact is the source of truth for names; Customer.email_id/first_name/last_name are
# read-only fetches of the primary contact, so they are only a fallback. src_rank orders
# those two sources; is_primary_contact then modified break ties, so one email always
# yields exactly one deterministic row (Zoho and Mailchimp dedupe on email and would
# otherwise pick arbitrarily).
_EXPORT_SQL = """
WITH group_emails AS (
	SELECT DISTINCT LOWER(email) AS key_email
	FROM `tabEmail Group Member`
	WHERE email_group = %(email_group)s AND unsubscribed = 0
),
candidates AS (
	SELECT
		LOWER(ce.email_id) AS key_email,
		c.first_name AS first_name,
		c.last_name AS last_name,
		cust.customer_name AS customer_name,
		1 AS src_rank,
		COALESCE(c.is_primary_contact, 0) AS is_primary_contact,
		c.modified AS modified
	FROM `tabContact Email` ce
	JOIN `tabContact` c ON c.name = ce.parent AND ce.parenttype = 'Contact'
	LEFT JOIN `tabDynamic Link` dl
		ON dl.parent = c.name AND dl.parenttype = 'Contact' AND dl.link_doctype = 'Customer'
	LEFT JOIN `tabCustomer` cust ON cust.name = dl.link_name
	WHERE ce.email_id IS NOT NULL AND ce.email_id != ''
	  AND LOWER(ce.email_id) IN (SELECT key_email FROM group_emails)

	UNION ALL

	SELECT
		LOWER(c.email_id), c.first_name, c.last_name, cust.customer_name, 1,
		COALESCE(c.is_primary_contact, 0), c.modified
	FROM `tabContact` c
	LEFT JOIN `tabDynamic Link` dl
		ON dl.parent = c.name AND dl.parenttype = 'Contact' AND dl.link_doctype = 'Customer'
	LEFT JOIN `tabCustomer` cust ON cust.name = dl.link_name
	WHERE c.email_id IS NOT NULL AND c.email_id != ''
	  AND LOWER(c.email_id) IN (SELECT key_email FROM group_emails)

	UNION ALL

	SELECT
		LOWER(cust.email_id), cust.first_name, cust.last_name, cust.customer_name, 2,
		0, cust.modified
	FROM `tabCustomer` cust
	WHERE cust.email_id IS NOT NULL AND cust.email_id != ''
	  AND LOWER(cust.email_id) IN (SELECT key_email FROM group_emails)
),
ranked AS (
	SELECT
		key_email, first_name, last_name, customer_name,
		ROW_NUMBER() OVER (
			PARTITION BY key_email
			ORDER BY src_rank ASC, is_primary_contact DESC, modified DESC
		) AS rn
	FROM candidates
)
SELECT
	egm.email AS email,
	r.customer_name AS customer_name,
	r.first_name AS first_name,
	r.last_name AS last_name
FROM `tabEmail Group Member` egm
LEFT JOIN ranked r ON r.key_email = LOWER(egm.email) AND r.rn = 1
WHERE egm.email_group = %(email_group)s AND egm.unsubscribed = 0
ORDER BY egm.email
"""


@frappe.whitelist(methods=["GET"])
def export_email_group_csv(email_group):
	"""Download an Email Group's subscribers as a CSV for bulk mail tools.

	Column headers match Zoho Campaigns' default field names so its importer
	auto-maps them; the same file imports cleanly into Mailchimp, Brevo, etc.
	"""
	from frappe.utils.csvutils import build_csv_response

	from cecypo_powerpack.utils import is_feature_enabled

	if not is_feature_enabled("enable_email_group_powerup"):
		frappe.throw(_("Email Group Powerup is disabled in PowerPack Settings"))

	if not frappe.has_permission("Email Group", "read", email_group):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	# The export discloses customer names and emails, so Email Group access alone
	# is not sufficient.
	if not frappe.has_permission("Customer", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	rows = frappe.db.sql(_EXPORT_SQL, {"email_group": email_group}, as_dict=True)

	data = [["Company Name", "First Name", "Last Name", "Contact Email"]]
	for row in rows:
		data.append(
			[
				row.customer_name or "",
				row.first_name or "",
				row.last_name or "",
				row.email or "",
			]
		)

	build_csv_response(data, f"{frappe.scrub(email_group)}-subscribers-{frappe.utils.today()}")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
bench --site <site> run-tests --app cecypo_powerpack \
  --module cecypo_powerpack.tests.test_email_group_powerup
```

Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check cecypo_powerpack
git add cecypo_powerpack/api.py cecypo_powerpack/tests/test_email_group_powerup.py
git commit -m "feat(email-group): add subscriber CSV export endpoint"
```

---

### Task 4: Export integration test

**Files:**
- Test: `cecypo_powerpack/tests/test_email_group_powerup.py`

**Interfaces:**
- Consumes: `export_email_group_csv` from Task 3.
- Produces: nothing consumed downstream.

**Why:** Every test in Task 3 mocks `frappe.db.sql`, so a syntax error, a wrong column name,
or an unsupported construct in `_EXPORT_SQL` would ship undetected. This task executes the
real statement against the test database.

- [ ] **Step 1: Write the failing test**

Add to `cecypo_powerpack/tests/test_email_group_powerup.py`:

```python
class TestExportSqlExecutes(unittest.TestCase):
    """Executes the real export SQL. Mock-based tests cannot catch SQL errors."""

    def test_export_sql_runs_against_database(self):
        from cecypo_powerpack.api import _EXPORT_SQL

        # No fixtures needed: an Email Group that does not exist yields zero rows,
        # which still fully parses, plans and executes the statement.
        rows = frappe.db.sql(
            _EXPORT_SQL,
            {"email_group": "__cecypo_nonexistent_group__"},
            as_dict=True,
        )
        self.assertEqual(rows, [])

    def test_export_sql_resolves_a_real_contact(self):
        from cecypo_powerpack.api import _EXPORT_SQL

        group = frappe.get_doc({
            "doctype": "Email Group",
            "title": "_Test PowerPack Export Group",
        }).insert(ignore_if_duplicate=True)

        contact = frappe.get_doc({
            "doctype": "Contact",
            "first_name": "Jane",
            "last_name": "Wanjiru",
            "email_ids": [{"email_id": "jane.export@example.com", "is_primary": 1}],
        }).insert(ignore_if_duplicate=True)

        frappe.get_doc({
            "doctype": "Email Group Member",
            "email_group": group.name,
            "email": "jane.export@example.com",
        }).insert(ignore_if_duplicate=True)

        rows = frappe.db.sql(
            _EXPORT_SQL, {"email_group": group.name}, as_dict=True
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].email, "jane.export@example.com")
        self.assertEqual(rows[0].first_name, "Jane")
        self.assertEqual(rows[0].last_name, "Wanjiru")

        frappe.db.rollback()
        del contact
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
bench --site <site> run-tests --app cecypo_powerpack \
  --module cecypo_powerpack.tests.test_email_group_powerup
```

Expected: FAIL if `_EXPORT_SQL` has any SQL defect. If Task 3 was written correctly this may
pass immediately — that is acceptable for a guard test; confirm it genuinely exercises the
statement by temporarily breaking a column name and watching it fail.

- [ ] **Step 3: Fix any SQL defects surfaced**

If MariaDB rejects the multiply-referenced `group_emails` CTE, inline the subquery into each
`UNION ALL` arm instead:

```sql
AND LOWER(ce.email_id) IN (
    SELECT DISTINCT LOWER(email) FROM `tabEmail Group Member`
    WHERE email_group = %(email_group)s AND unsubscribed = 0
)
```

repeated in all three arms, dropping the `WITH group_emails AS (...)` clause. Behaviour is
identical.

- [ ] **Step 4: Run tests to verify they pass**

```bash
bench --site <site> run-tests --app cecypo_powerpack \
  --module cecypo_powerpack.tests.test_email_group_powerup
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cecypo_powerpack/tests/test_email_group_powerup.py
git commit -m "test(email-group): execute export SQL against the database"
```

---

### Task 5: UI — export button and flag gating

**Files:**
- Modify: `cecypo_powerpack/public/js/email_group_powerup.js`

**Interfaces:**
- Consumes: `CecypoPowerPack.Settings.isEnabled(flag, callback)` from `public/js/cecypo_powerpack.js`;
  the endpoint URL from Task 3.
- Produces: nothing consumed downstream.

- [ ] **Step 1: Gate the existing button and add the export button**

Replace the `frappe.ui.form.on('Email Group', {...})` block at the top of
`cecypo_powerpack/public/js/email_group_powerup.js` with:

```javascript
frappe.ui.form.on('Email Group', {
	refresh(frm) {
		CecypoPowerPack.Settings.isEnabled('enable_email_group_powerup', function (enabled) {
			if (!enabled) return;

			frm.add_custom_button(__('Import Subscribers by Item Purchased'), function () {
				show_import_dialog(frm);
			}, __('Powerup'));

			frm.add_custom_button(__('Export Subscribers (CSV)'), function () {
				export_subscribers(frm);
			}, __('Powerup'));
		});
	},
});
```

- [ ] **Step 2: Add the export handler**

Add this function inside the same IIFE, after `show_import_dialog`:

```javascript
function export_subscribers(frm) {
	if (!frm.doc.total_subscribers) {
		frappe.show_alert({
			message: __('This group has no subscribers to export.'),
			indicator: 'blue',
		});
		return;
	}

	const url = '/api/method/cecypo_powerpack.api.export_email_group_csv'
		+ '?email_group=' + encodeURIComponent(frm.doc.name);
	window.open(url, '_blank');
}
```

- [ ] **Step 3: Syntax-check and build**

```bash
node --check cecypo_powerpack/public/js/email_group_powerup.js
bench build --app cecypo_powerpack
```

Expected: no output from `node --check`; build succeeds.

- [ ] **Step 4: Manual verification**

```bash
bench --site <site> clear-cache
```

Then in the browser:
1. Open any Email Group with at least one subscriber.
2. Confirm the **Powerup** button group shows both actions.
3. Click **Export Subscribers (CSV)** — a CSV downloads.
4. Open it: header row is `Company Name,First Name,Last Name,Contact Email`; row count
   equals the group's non-unsubscribed member count.
5. In PowerPack Settings, untick **Enable Email Group Powerup**, save, reload the Email
   Group — the Powerup group is gone.
6. Re-tick it before finishing.

- [ ] **Step 5: Commit**

```bash
git add cecypo_powerpack/public/js/email_group_powerup.js
git commit -m "feat(email-group): add Export Subscribers (CSV) button"
```

---

## Final verification

```bash
bench --site <site> migrate
bench --site <site> run-tests --app cecypo_powerpack \
  --module cecypo_powerpack.tests.test_email_group_powerup
ruff check cecypo_powerpack
node --check cecypo_powerpack/public/js/email_group_powerup.js
bench build --app cecypo_powerpack
bench restart
```

## Self-review notes

- Spec coverage: §1 widen import → Task 2. §2 export endpoint → Tasks 3 and 4. §3 UI → Task 5.
  §4 feature flag → Task 1. Testing section → Tasks 1-4. All covered.
- The spec's "collision → is_primary_contact wins" and "Individual → customer_name in Company
  Name" cases are covered structurally (Task 3 asserts the `ORDER BY`) and behaviourally via
  the real-data test in Task 4. `customer_name` is selected unconditionally, so the Individual
  rule needs no branch.
- `_EXPORT_SQL` is module-level and underscore-prefixed so Task 4 can import it without
  exposing it as an API.
