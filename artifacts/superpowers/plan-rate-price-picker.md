# Plan: Rate Price Picker
Design: `design-rate-price-picker.md` (approved 2026-10-01). Branch `feat/rate-price-picker`.

1. Setting `enable_rate_price_picker` (Check, default 0) in PowerPack Settings > Sales & POS.
   `bench migrate`. Verify: field present.
2. TDD `tests/test_rate_price_picker.py` (red), then `rate_price_picker.py`
   `get_rate_options`: currency filter, disabled/buying lists out, customer price wins,
   UOM conversion, expired out, below_floor, gate/doctype/permission. Verify: module green.
3. `public/js/rate_price_picker.js` + `public/css/rate_price_picker.scss`, bundle imports.
   `bench build --app cecypo_powerpack`. Verify: build clean.
4. Browser e2e (throwaway user, unsaved draft, then one saved throwaway QT deleted after),
   1400px + 375px. Verify: all interactions in the design.
5. README + CLAUDE.md. Full suite on a quiet site. Code review subagent, fix, merge to main,
   push upstream/main, finish notes.
