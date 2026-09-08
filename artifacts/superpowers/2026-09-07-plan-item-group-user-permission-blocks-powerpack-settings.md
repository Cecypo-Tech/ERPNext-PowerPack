# Plan: Item Group User Permission blocks PowerPack Settings

## Problem
User `kisumu@cecypo.tech` was restricted to a group of items via a **User Permission
on Item Group**. Every PowerPack feature then died with:

```
You are not allowed to access this Minimum Selling Price Rule record because it is
linked to Item Group 'All Item Groups' in row 2, field Item Group
User kisumu@cecypo.tech does not have access to this document: PowerPack Settings
No permission for PowerPack Settings
```

## Root cause (confirmed, not inferred)
`frappe/permissions.py::has_user_permission()` STEP 2 walks **every link field of the
document and of all its child rows**. Any link field without `ignore_user_permissions`
is checked against the user's User Permissions.

`PowerPack Settings.min_selling_price_rules` -> child doctype `Minimum Selling Price
Rule`, field `item_group` (Link -> Item Group), `ignore_user_permissions: 0`.
One of its config rows points at `All Item Groups`, which is NOT in the user's allowed
set, so `has_user_permission()` returns False for the whole singleton.

For a Single doctype, `frappe.has_permission("PowerPack Settings")` resolves `doc =
meta.name` (permissions.py:133-141) and runs that check even when no doc is passed --
so *every* read path fails, not just form loads.

Reproduced locally on dev.localhost with a Sales User restricted to Item Group
"Cement":
```
role_perms read      : 1        <- roles are fine
has_user_permission  : False    <- fails here
logs: "You are not allowed to access this Minimum Selling Price Rule record because
       it is linked to Item Group 'All Item Groups' in row 1, field Item Group"
```

### Trigger paths in this app
- `public/js/point_of_sale_powerpack.js:45` -> `frappe.client.get_single_value`
- `public/js/point_of_sale_powerpack.js:109` -> `frappe.client.get`
- `public/js/sales_powerup.js:37` -> `frappe.client.get`

All three call `frappe.has_permission("PowerPack Settings")` server-side
(`frappe/client.py:136,178`) and throw `No permission for PowerPack Settings`.

`api.py::get_settings_for_client` is NOT affected -- it uses `frappe.get_doc` with no
permission check. The same class of bug was already patched by hand there for
`Company`; the underlying field flag was never fixed.

### Same latent defect
`Powerpack Company Border.company` (Link -> Company, `ignore_user_permissions: 0`).
A user restricted to one Company hits the identical wall via the same three JS paths.

## Fix
1. Set `"ignore_user_permissions": 1` on
   - `Minimum Selling Price Rule.item_group`
   - `Powerpack Company Border.company`
   These are administrator-only *configuration* rows on a settings singleton. User
   Permissions are meant to scope transactional data, not the config that describes
   the policy. This is the flag Frappe provides for exactly this case
   (`permissions.py:426-427`).
2. Regression test: a user with an Item Group User Permission must still get
   `frappe.has_permission("PowerPack Settings", "read") == True`.
3. Point the three client-side reads at the app's own
   `cecypo_powerpack.api.get_settings_for_client` (via `CecypoPowerPack.Settings`)
   instead of `frappe.client.get` / `get_single_value`. Defense in depth for the same
   failure class, matches the documented pattern in CLAUDE.md, and stops shipping the
   raw singleton (including other companies' `company_borders`) to the browser.

## Verification
- `bench --site dev.localhost run-tests --app cecypo_powerpack --module cecypo_powerpack.tests.test_settings_permissions`
- `bench --site dev.localhost run-tests --app cecypo_powerpack --module cecypo_powerpack.tests.test_min_selling_price`
- Re-run the repro script: `has_user_permission` must flip False -> True.
- `bench build --app cecypo_powerpack` (JS syntax + assets).
- Manual: as the restricted user, open a Quotation and POS; no permission error.

## Deployment (prod)
`bench --site <site> migrate` (doctype JSON changed) then
`bench build --app cecypo_powerpack`, `bench clear-cache`, hard-reload the browser.

## Risks
- `ignore_user_permissions` also removes User Permission filtering from those link
  field *dropdowns* when an admin edits PowerPack Settings. Intended: an admin
  configuring a global policy must be able to pick any item group / company.
- No data migration, no destructive change. Reversible by flipping the flag back.
