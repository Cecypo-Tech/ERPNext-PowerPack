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

**Public JS files** (all globally included via `hooks.py`):
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

- `cecypo_powerpack.css` — global compact theme (`body.compact-theme`)
- `point_of_sale_powerpack.css` — POS compact/thumbnail view layouts
- `sales_powerup.css` — Sales powerup info panels
