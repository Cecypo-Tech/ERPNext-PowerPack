# Spec: Email Group CSV Export + Contact-aware Import

**Date:** 2026-07-26
**Status:** Approved (design), pending implementation
**Area:** `cecypo_powerpack/api.py`, `public/js/email_group_powerup.js`, `PowerPack Settings`

## Goal

Let a user export an Email Group's subscribers as a CSV suitable for direct import
into Zoho Campaigns (and any other bulk mail tool), with columns for company name,
first name, last name, and email.

Along the way, fix the existing import-by-item feature, which only ever discovers a
customer's *primary* contact email.

## Background

`Email Group Member` stores exactly three fields: `email_group`, `email`,
`unsubscribed`. There is no name or company data in the group, so the export must
reconstruct identity by resolving each email back against `Contact` / `Customer`.

In this ERPNext version, `Customer.email_id`, `Customer.first_name` and
`Customer.last_name` are all **read-only `fetch_from` `customer_primary_contact`**.
Consequently the current import query (`api.py`, `import_email_group_subscribers_by_item`)
misses:

- customers whose `customer_primary_contact` was never set — common on migrated data,
  since `fetch_from` only populates on save
- every non-primary contact on an account
- secondary addresses in the `Contact Email` child table

The true source of names is `Contact` (`first_name`, `last_name`, `is_primary_contact`),
linked to `Customer` through `Dynamic Link` (`link_doctype = 'Customer'`).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Transport | CSV export, not the Zoho Campaigns API | Zoho's API needs self-client OAuth with refresh rotation, region-specific domains (`.com`/`.eu`/`.in`/`.com.au`), a stored client secret, and list-key lookup — significant maintenance for one vendor. CSV works identically for Mailchimp, Brevo, Listmonk. |
| Name resolution | Contact-first, Customer fallback, then blank | Maximum coverage without dropping rows. |
| Collisions | One row per email (case-insensitive), deterministic pick | Zoho dedupes on email and skips duplicates non-deterministically; we choose the winner instead. |
| Individual customers | `customer_name` always fills Company Name | One rule; the column always identifies the ERPNext account. |
| Feature gate | New `enable_email_group_powerup`, default `1` | Every other feature in this app is gated (see `CLAUDE.md`); this one was not. Default on so existing installs don't silently lose it. |

## Scope

### 1. Widen the import query

Rewrite the customer-email discovery inside `import_email_group_subscribers_by_item`.
Keep the existing item / item-group filter and the existing
`contextlib.suppress(UniqueValidationError, InvalidEmailAddressError)` insert loop —
only the email-discovery SQL changes.

Emails are collected from the union of three sources, restricted to customers who
purchased the item (or an item in the item group) on a **submitted** Sales Invoice:

| Source | Catches |
|---|---|
| `Customer.email_id` | current behaviour (primary contact, denormalized) |
| `Contact.email_id` via `Dynamic Link` → Customer | contacts on customers with no `customer_primary_contact` |
| `Contact Email`.`email_id` (child of those contacts) | secondary addresses |

Blank/NULL emails are excluded from every arm. Results are `DISTINCT`.

This is purely additive: it finds strictly more people than today, never fewer.

### 2. New export endpoint

`export_email_group_csv(email_group)` in `cecypo_powerpack/api.py`.

- `@frappe.whitelist(methods=["GET"])` — read-only, so GET is correct and the browser
  can trigger it as a download.
- Responds via `frappe.utils.csvutils.build_csv_response(rows, filename)`. No temp files.
- Filename: `<email-group-slug>-subscribers-YYYY-MM-DD.csv`, sanitized.

**Permissions.** Require *both*:

- `frappe.has_permission("Email Group", "read", doc=email_group)`
- `frappe.has_permission("Customer", "read")`

Email Group access alone must not be enough — this endpoint discloses customer PII.
Throw `frappe.PermissionError` otherwise.

**Feature gate.** Throw if `is_feature_enabled('enable_email_group_powerup')` is false.

**Columns**, in this order, using Zoho Campaigns' exact default field names so its
importer auto-maps them without manual mapping:

```
Company Name, First Name, Last Name, Contact Email
```

**Resolution query.** One SQL statement — not a per-email Python loop. MariaDB 11.8 is
in use, so CTEs and window functions are available.

```
WITH group_emails AS (
    SELECT DISTINCT LOWER(email) AS key_email
    FROM `tabEmail Group Member`
    WHERE email_group = %(email_group)s AND unsubscribed = 0
),
candidates AS (
    -- src_rank 1: contact-sourced (Contact Email child table)
    SELECT LOWER(ce.email_id) AS key_email,
           c.first_name, c.last_name,
           cust.customer_name,
           1 AS src_rank, c.is_primary_contact, c.modified
    FROM `tabContact Email` ce
    JOIN `tabContact` c ON c.name = ce.parent AND ce.parenttype = 'Contact'
    LEFT JOIN `tabDynamic Link` dl
           ON dl.parent = c.name AND dl.parenttype = 'Contact'
          AND dl.link_doctype = 'Customer'
    LEFT JOIN `tabCustomer` cust ON cust.name = dl.link_name
    WHERE LOWER(ce.email_id) IN (SELECT key_email FROM group_emails)

    UNION ALL
    -- src_rank 1: contact-sourced (Contact.email_id, belt-and-braces)
    SELECT LOWER(c.email_id), c.first_name, c.last_name, cust.customer_name,
           1, c.is_primary_contact, c.modified
    FROM `tabContact` c
    LEFT JOIN `tabDynamic Link` dl ...
    LEFT JOIN `tabCustomer` cust ...
    WHERE LOWER(c.email_id) IN (SELECT key_email FROM group_emails)

    UNION ALL
    -- src_rank 2: customer fallback
    SELECT LOWER(cust.email_id), cust.first_name, cust.last_name, cust.customer_name,
           2, 0, cust.modified
    FROM `tabCustomer` cust
    WHERE LOWER(cust.email_id) IN (SELECT key_email FROM group_emails)
),
ranked AS (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY key_email
        ORDER BY src_rank ASC, is_primary_contact DESC, modified DESC
    ) AS rn
    FROM candidates
)
SELECT egm.email, r.customer_name, r.first_name, r.last_name
FROM `tabEmail Group Member` egm
LEFT JOIN ranked r ON r.key_email = LOWER(egm.email) AND r.rn = 1
WHERE egm.email_group = %(email_group)s AND egm.unsubscribed = 0
ORDER BY egm.email
```

The `IN (SELECT ... FROM group_emails)` prefilter is load-bearing: without it the
candidate CTE scans every Contact and Customer on the site.

**Behaviour guarantees:**

- CSV row count always equals the number of non-unsubscribed members in the group.
  Unresolved emails export with blank name columns rather than being dropped.
- `unsubscribed = 1` members are always excluded.
- An empty group returns a headers-only CSV.
- Dedupe is case-insensitive; `Acme@x.com` and `acme@x.com` collapse to one row.

### 3. UI

In `public/js/email_group_powerup.js`, add a second button to the existing `Powerup`
group: **Export Subscribers (CSV)**, triggering the download with `window.open()` against
the endpoint URL (email group name URL-encoded).

Both this button and the existing "Import Subscribers by Item Purchased" button move
behind `CecypoPowerPack.Settings.isEnabled('enable_email_group_powerup', ...)`.

If `frm.doc.total_subscribers` is 0, show an info alert instead of downloading an
empty file.

### 4. Feature flag

Add `enable_email_group_powerup` (Check, default `1`) to the `PowerPack Settings`
DocType JSON, placed in the tab where the other document-level powerups live. Gate:

- JS: both buttons
- Python: `import_email_group_subscribers_by_item` and `export_email_group_csv`

Requires `bench migrate`.

## Testing

Extend `cecypo_powerpack/tests/test_email_group_powerup.py`. Red-first per repo rules.

**Existing tests are brittle but survive.** The current suite mocks `frappe.db.sql`
wholesale and asserts on SQL *string fragments* — `test_import_by_item` asserts
`"sii.item_code = %(filter_value)s"` and `"docstatus = 1"`, `test_import_by_item_group`
asserts `"item_group = %(filter_value)s"`, `test_no_email_customer_excluded` asserts
`"email_id IS NOT NULL"` and `"email_id != ''"`. The widened query retains every one of
those fragments, so these tests keep passing unmodified. They still assert nothing about
correctness; the new contact-source coverage must come from new tests, not from these.

**Mock-based tests cannot validate the new CTE.** At least one test must execute the
export query against the real test database so a SQL syntax or column-name error fails
CI instead of shipping.

Cases:

*Import*
- contact on a customer with no `customer_primary_contact` set is discovered
- secondary `Contact Email` address is discovered
- an email reachable via two sources is inserted once, not twice
- existing behaviour preserved: draft invoices excluded, item-group filter works,
  re-import adds nothing, blank emails excluded

*Export*
- contact-sourced name wins over the customer fallback
- customer fallback used when no Contact matches
- unresolvable email → row present, name columns blank
- `unsubscribed = 1` member excluded
- collision → exactly one row; `is_primary_contact` wins
- `customer_type = Individual` → `customer_name` in Company Name
- header row matches the four Zoho names exactly, in order
- empty group → headers only
- **integration:** query executes against the test DB without error

*Guards*
- `PermissionError` without Email Group read
- `PermissionError` with Email Group read but no Customer read
- both endpoints throw when the feature flag is off

## Verification

```bash
bench --site <site> run-tests --app cecypo_powerpack \
  --module cecypo_powerpack.tests.test_email_group_powerup
bench --site <site> migrate
ruff check cecypo_powerpack
node --check cecypo_powerpack/public/js/email_group_powerup.js
bench build --app cecypo_powerpack
```

## Out of scope

- Zoho Campaigns OAuth push (separate project if wanted later)
- Scheduled or automatic exports
- Export provenance — recording which item a member came from. `Email Group Member`
  has no such field, and adding one means custom fields on a core doctype plus fixtures.

## Known risks

- **Excel + UTF-8.** `build_csv_response` writes no BOM, so accented names may render
  incorrectly when the file is opened directly in Excel. Zoho's importer is unaffected.
  Accepted; not solved here.
- **Large groups.** The response is built fully in memory. At roughly 60 bytes/row a
  100k-member group is ~6 MB, which is acceptable for an on-demand export.
- **PII.** The export widens who can see customer names and emails. Mitigated by
  requiring Customer read permission.
