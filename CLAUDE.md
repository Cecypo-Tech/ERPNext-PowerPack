# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Cecypo PowerPack is a Frappe/ERPNext app that adds feature enhancements ("power-ups") to ERPNext. All features are centrally toggled via a single `PowerPack Settings` DocType (singleton).

## Common Commands

All commands run from `/home/frappeuser/frappe-bench/`:

```bash
# Build JS/CSS assets after editing public/ files
bench build --app cecypo_powerpack

# Migrate after changing DocType JSON
bench migrate

# Run all app tests
bench run-tests --app cecypo_powerpack

# Run a single test module
bench run-tests --app cecypo_powerpack --module cecypo_powerpack.cecypo_powerpack.doctype.powerpack_settings.test_powerpack_settings

# Restart after Python changes
bench restart

# Clear cache
bench clear-cache
```

## Architecture

### Feature Gating Pattern

Every feature is controlled by a checkbox field in `PowerPack Settings`. The pattern is used consistently on both sides:

**Python (server):**
```python
from cecypo_powerpack.utils import is_feature_enabled
if not is_feature_enabled('enable_some_feature'):
    return
```

**JavaScript (client):**
```javascript
CecypoPowerPack.Settings.isEnabled('enable_some_feature', function(enabled) {
    if (!enabled) return;
    // feature logic
});
```

The JS settings object (`CecypoPowerPack.Settings`) caches settings in memory and is cleared `after_save` on the PowerPack Settings form.

**Never read PowerPack Settings from the client with `frappe.client.get` / `get_single_value` / `get_value`.** Those permission-check the singleton, and `frappe.permissions.has_user_permission()` walks the Link fields of its *child* rows — so one User Permission on Item Group or Company makes the whole singleton unreadable and every gated feature dies with "No permission for PowerPack Settings". Go through `CecypoPowerPack.Settings.get()` / `.isEnabled()`, which call `cecypo_powerpack.api.get_settings_for_client`. Any new Link field on a Settings child table needs `"ignore_user_permissions": 1`, since those rows are configuration, not scoped data.

### Key Files

| File | Purpose |
|------|---------|
| `cecypo_powerpack/hooks.py` | App metadata, `app_include_js/css`, `doc_events`, `override_doctype_class`, `fixtures` |
| `cecypo_powerpack/api.py` | All `@frappe.whitelist()` API methods |
| `cecypo_powerpack/utils.py` | `get_powerpack_settings()`, `is_feature_enabled()` |
| `cecypo_powerpack/validations.py` | `before_cancel` handler for ETR invoice protection |
| `cecypo_powerpack/overrides.py` | `Payment Reconciliation` validate hook for zero-allocation support |
| `cecypo_powerpack/custom_payment_reconciliation.py` | `CustomPaymentReconciliation` class extending ERPNext's `PaymentReconciliation` |
| `cecypo_powerpack/permission_manager.py` | Server side of the Permission Manager page: read all rules, preview/commit a batched change set |
| `cecypo_powerpack/cecypo_powerpack/page/powerpack_permissions/` | The Permission Manager desk page (`/app/powerpack-permissions`) |
| `cecypo_powerpack/cecypo_powerpack/doctype/powerpack_settings/` | Singleton DocType definition |

### Asset bundling (read before adding a JS or CSS file)

`hooks.py` declares exactly two desk assets, and they are **bare bundle names**, not
`/assets/...` paths:

```python
app_include_css = "cecypo_powerpack.bundle.css"   # built from public/css/cecypo_powerpack.bundle.scss
app_include_js  = "cecypo_powerpack.bundle.js"    # public/js/cecypo_powerpack.bundle.js
```

Frappe resolves a bundle name through `assets.json` to a **content-hashed** filename
(`bundled_asset()`, `frappe/utils/jinja_globals.py:147`). A literal `/assets` path is
served verbatim with no hash and no `?ver=`, so browsers cache it indefinitely and a
deployed change never reaches anyone who does not manually hard-reload. Never go back
to listing raw paths.

**To add a file:** create it under `public/js` or `public/css`, then add an `import`
to the matching bundle entry point. Import order is load order.

Two consequences to respect:

- **CSS sources are `.scss`.** Most are plain CSS with a renamed extension; Sass nesting is fine and `powerpack_permissions.scss` uses it. The
  rename exists only so sass resolves the bundle's extensionless sibling imports —
  frappe's postcss plugin copies a bundle entry to a temp dir without its siblings,
  so importing a `.css` file by full name fails to resolve.
- **Bundled files get module scope, not global scope.** A top-level `function foo()`
  in a bundled file is NOT on `window`. Anything shared between files must go on
  `window.CecypoPowerPack` or a `frappe.provide()` namespace — see
  `CecypoPowerPack.formatNumber`, which was previously a bare `format_number()` in
  `bulk_selection.js` that silently overwrote frappe's core `window.format_number`
  for every desk page.

Known quirk: the CSS hash changes on every `bench build` even with no source change,
because frappe stages CSS through a randomly-named temp dir that lands in the
sourcemap. Harmless (one extra ~32KB download per deploy) and not specific to this
app. The JS hash is stable.

**Public JS files** (all bundled via `cecypo_powerpack.bundle.js`):
- `cecypo_powerpack.js` — `CecypoPowerPack` namespace, settings cache, Tax ID duplicate check, ETR cancel warning
- `point_of_sale_powerpack.js` — POS compact/thumbnail view toggle, enhanced search (wildcard `%` + multi-word), keyboard nav, barcode feedback
- `sales_powerup.js` — Injects stock/valuation/purchase history info into item lines on Quotation/SO/SI/POS Invoice
- `bulk_selection.js` — Bulk item selection dialog for sales documents
- `profit_calculator.js` — Profit margin display
- `payment_reconciliation_powerup.js` — "Zero Allocate" button for Payment Reconciliation

### Server-Side Extension Points

- **`override_doctype_class`** in `hooks.py`: `Payment Reconciliation` is overridden with `CustomPaymentReconciliation` to add a `zero_reconcile()` method without touching the standard reconcile path.
- **`doc_events`**: `before_cancel` on Sales Invoice and POS Invoice; `validate` on Payment Reconciliation.

### Permission Manager

`/app/powerpack-permissions` replaces the per-checkbox saving of frappe's Role
Permissions Manager with one virtualized grid and a single commit. Rules are keyed by
`(doctype, role, permlevel, if_owner)` — `if_owner` included, because frappe's own
`update_permission_property()` omits it and can hit the wrong row.

- Read: gated on `frappe.has_permission("User Permission", "read")` (`READ_GATE_DOCTYPE`). Not
  Custom DocPerm: frappe never honours custom perms on that doctype itself (`meta.py:645`).
  Grant a role Read on User Permission to let it view the grid.
- Write: `only_for("System Manager")`, unconditionally.
- Stricter than frappe's page on purpose: the engine validates the rules actually in force
  (the custom rows), whereas frappe's page validates the *standard* rows. A doctype whose
  custom rows already break an invariant (e.g. submit/cancel/amend ticked on a
  non-submittable doctype — dev has one: `API Request Log` / `Express Admin`) rejects
  *any* commit touching it until those flags are cleared in the same commit. The error
  names the offending rule.
- Commit groups changes by doctype, calls `setup_custom_perms` once per doctype (which
  **detaches** it from app permission updates — the review step lists these), validates
  the custom rules with frappe's `validate_permissions()`, and clears the user cache once.
- The payload is a list of ops: `{op: "update"|"add"|"remove", doctype, role, permlevel,
  if_owner}`, plus `changes: {flag: 0|1}` for an update. A missing `op` means `update`.
  `_parse_changes` is the only validation gate; `commit_changes` applies removals, then
  additions, then updates per doctype so an update can target a rule the same payload
  adds. A new rule is seeded `read: 1` and nothing else — `_add_rule` sets every flag in
  `FLAGS` explicitly, because `Custom DocPerm` defaults `export` to `'1'` as well as
  `read`, so passing `read` alone would silently grant Export on every rule the page creates.
- Three invariants frappe enforces only in its **page endpoint**, never in
  `validate_permissions()`, so this path enforces them itself: a doctype must keep at
  least one rule (checked per doctype across the whole payload — row-by-row would let
  you delete both rules of a two-rule doctype); no duplicate
  `(doctype, role, permlevel, if_owner)`; and `report` cannot be set with `if_owner`.
  `frappe.permissions.add_permission()` is deliberately unused — it `msgprint`s and
  returns on a duplicate, and hardcodes `if_owner=0`.
- A fourth invariant, `BASIC_RIGHTS`, frappe *does* enforce — but in
  `validate_permissions()`, which `_apply_to_doctype` runs only after every row is
  written, so one stray checkbox rolls the whole commit back with
  "<rule>: No basic permissions set" and no hint which rule or flag caused it. A rule
  needs one of `select` / `read` / `write` / `create` / `submit` / `cancel`; `delete`,
  `print` or `export` alone does not count. Enforced twice on purpose:
  `_check_keeps_a_basic_right` in `_parse_changes` (which reads the rule in force and
  applies the payload's deltas, so read-off-plus-write-on is correctly allowed), and
  `set_flag` in the browser, which refuses the click and puts the tick back. The
  commonest way in is unticking Read on a rule you just added, since a new rule starts
  with Read and nothing else. `test_the_guard_matches_frappe_own_predicate` fails if
  frappe ever changes the predicate, rather than letting the two drift.
- Adds and removes are staged in the browser (`pending_adds` / `pending_removes`) and
  render as `pp-new` / `pp-removed`. Like flag edits, they reach the server only on
  Commit and are dropped by Discard.
- A staged removal is undoable on its own: **Restore Selected** (shown only while
  `pending_removes` is non-empty, like Discard) clears the mark for the selected rows.
  Without it the only undo was Discard, which throws away every other unsaved change
  too. `stage_remove` re-selects the rows it just staged (`reselect`), because
  `apply_filters` drops the datatable's index-keyed checkbox map — otherwise the rows
  needing restoring are exactly the ones no longer selected. A restored row comes back
  as it was *loaded*: `stage_remove` restores its loaded flags and forgets its pending
  edits (it must, or the payload emits an update and a remove for one identity), so it
  says how many edits it dropped at the moment that is still true.
- The page JS is loaded by frappe's page loader and is a classic script; its SCSS goes
  through the bundle like everything else.
- Deploying this feature needs `bench migrate` (it ships a new Page record — the route
  404s without it) and `bench build --app cecypo_powerpack` (new bundle entry;
  `public/dist` is gitignored).

### Fixtures

`hooks.py` exports these as fixtures (synced with `bench export-fixtures`):
- `Custom Field` — specifically `POS Profile-enable_powerpack_by_cecypo`, `POS Profile-powerpack_column_config`, `Quotation-set_warehouse`
- `Print Format` — `Powerpack POS Template`
- `Server Script` and `Client Script` — all in the `Cecypo PowerPack` module

### POS Powerpack Initialization

`point_of_sale_powerpack.js` uses a polling approach (every 500ms) waiting for `cur_pos.item_selector` to exist before initializing. It always patches the item description field regardless of settings, then conditionally loads full PowerPack features based on `enable_pos_powerup`.

POS search reads from `POS Settings.pos_search_fields` (child table) to extend the search fields beyond `item_code` and `item_name`.

### API Conventions

- All public API methods are in `cecypo_powerpack/api.py` with `@frappe.whitelist()`
- Bulk data APIs accept pipe-delimited strings (`|||`) or JSON-style lists as input to work around Frappe's URL parameter limitations
- `get_bulk_item_details()` uses an optimized batch-query path by default; set `optimized=False` for the per-item fallback

### CSS

SCSS sources (plain CSS or nested), imported by `cecypo_powerpack.bundle.scss` — see
**Asset bundling** above for why the extension matters.

- `cecypo_powerpack.scss` — global compact theme (`body.compact-theme`)
- `point_of_sale_powerpack.scss` — POS compact/thumbnail view layouts
- `sales_powerup.scss` — Sales powerup info panels
- `quick_pay.scss` — Quick Pay dialog
- `lens_powerup.scss` — Lens powerup panels
- `powerpack_permissions.scss` — Permission Manager page

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec
