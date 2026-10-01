# Finish: Rate Price Picker

Landed: `feat/rate-price-picker` merged to `main` (964d8ff) and pushed to `upstream/main`.

## Verification
- `bench --site dev.localhost run-tests --app cecypo_powerpack`: 63 + 10 + 223 + 83, all OK
  (1 pre-existing skip), quiet site.
- Browser e2e on dev (headless Chromium; throwaway Quotation, prices and user, all removed):
  main flow at 1400 / 375 px and review scenarios R1-R8. No page errors.

## State left on dev.localhost
- PowerPack Settings > Enable Rate Price Picker is ON (turned on for testing; default is off).

## Deploy on other sites
`bench migrate` (new Check field) and `bench build --app cecypo_powerpack`; then tick
Enable Rate Price Picker where wanted.

## Follow-ups
- Not tried on a real phone (virtual keyboard / touch); headless 375 px only.
- Esc after a cell-click open during a grid redraw leaves focus on the page body.
