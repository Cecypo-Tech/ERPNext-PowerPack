# Finish report: Item Group User Permission blocked PowerPack Settings

Branch: `fix/item-group-user-permission-powerpack-settings` (off `main`)
Plan: `artifacts/superpowers/2026-09-07-plan-item-group-user-permission-blocks-powerpack-settings.md`
All three planned steps delivered.

## What shipped

**1. Root cause — `ignore_user_permissions` on the two config link fields**
- `Minimum Selling Price Rule.item_group`
- `Powerpack Company Border.company`

`frappe.permissions.has_user_permission()` walks every Link field of a document AND of
all its child rows (`permissions.py:426-470`). A config row naming `All Item Groups`
falls outside a scoped user's allowed set, so the whole singleton failed the check. As
`frappe.has_permission()` resolves a Single to its doc even with no doc passed
(`permissions.py:133-141`), every read path failed at once.

**2. Regression test** — `cecypo_powerpack/tests/test_settings_permissions.py`, 5 tests:
field-flag assertions for both fields, plus a scoped Sales User passing
`frappe.has_permission`, `has_user_permission` on the loaded doc, and
`frappe.client.get_single_value` (the exact call the POS makes).

**3. Client reads repointed** off `frappe.client.*` and onto `CecypoPowerPack.Settings`:
- `point_of_sale_powerpack.js:44` `get_single_value` -> `Settings.isEnabled`
- `point_of_sale_powerpack.js:104` `client.get` -> `Settings.get`
- `sales_powerup.js:36` `client.get` -> `Settings.get`

Plus a CLAUDE.md note so the pattern does not come back.

## Verification (all run)
| check | result |
|---|---|
| new module before the fix | 4 failures + 1 error (red) |
| new module after the fix | 5 passed |
| `test_min_selling_price` | 27 passed |
| full app suite | 62 passed, OK |
| `node --check` on both changed JS files | clean |
| `bench build --app cecypo_powerpack` | DONE |
| original repro script | `has_user_permission` False -> True, `doc_permissions read` None -> 1, perm log empty |
| browser, logged in as a Sales User restricted to Item Group "Cement" | `frappe.client.get_single_value` 200 `{"message":1}` (previously PermissionError); `get_settings_for_client` 200, 57 keys; `sales_powerup.settings` populated, `enabled: true`; no permission errors in console |

## Findings by severity
- **Blocker:** none.
- **Major:** none.
- **Minor (behaviour change):** `sales_powerup` used to refetch settings on every form
  load; it now reads the shared in-memory cache. The cache is cleared `after_save` only
  in the tab that saved, so another user's open tab keeps stale settings until reload.
  This is how every other PowerPack feature already behaves, so the change makes
  sales_powerup consistent rather than introducing a new class of staleness.
- **Minor:** `Settings.isEnabled` tests `settings[field] === 1`, stricter than the old
  truthiness check on `get_single_value`. Check fields come back as ints from
  `as_dict()`, and the live endpoint returned `1`, so the paths agree today.
- **Nit:** `ignore_user_permissions` also stops User Permission filtering on those two
  link dropdowns when an admin edits PowerPack Settings. Intended — an admin setting a
  global policy must be able to pick any item group or company.

## Deployment
```
bench --site <site> migrate          # doctype JSON changed
bench build --app cecypo_powerpack
bench clear-cache
```
Then hard-reload the browser (this app's CSS/JS is served without a cache-buster).

## Dev-site scaffolding (created then removed)
Test users `pp-itemgroup-repro@example.com` and `powerpack-perm-test@example.com` plus
their User Permissions — deleted. The site's 7 real `min_selling_price_rules` rows were
verified intact afterwards.
