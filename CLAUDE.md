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

- **CSS sources are `.scss`.** They are plain CSS with a renamed extension. The
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

Plain CSS with a `.scss` extension, imported by `cecypo_powerpack.bundle.scss` — see
**Asset bundling** above for why the extension matters.

- `cecypo_powerpack.scss` — global compact theme (`body.compact-theme`)
- `point_of_sale_powerpack.scss` — POS compact/thumbnail view layouts
- `sales_powerup.scss` — Sales powerup info panels
- `quick_pay.scss` — Quick Pay dialog
- `lens_powerup.scss` — Lens powerup panels

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
