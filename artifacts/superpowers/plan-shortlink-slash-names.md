# Plan: short links break for document names containing "/"

## Root cause (confirmed)
`build_public_link` (api.py) makes the token `f"{name}-{suffix}"`, so PO `LPO/26/09/00109`
gets token `LPO/26/09/00109-Fq0R`. The route rule in hooks.py is `/s/<token>`; werkzeug's
default converter matches one path segment only, so `/s/LPO/26/09/00109-Fq0R` matches
nothing and 404s. Reproduced with werkzeug Map: `<token>` -> 404, `<path:token>` -> match.
The share-key target `/Purchase Order/LPO/26/09/00109?key=` is fine: frappe's PrintPage
splits on the first "/" only. ERPNext's own portal routes use `<path:name>` for this reason.

## Fix
1. hooks.py: `/s/<token>` -> `/s/<path:token>`. Makes every link already sent work,
   including the one Pramukh already sent to the supplier (token is the DB key, unchanged).
2. api.py `build_public_link`: new tokens replace any char outside `[A-Za-z0-9._-]` with
   `-` (so `LPO-26-09-00109-Fq0R`). Cleaner URLs, safe in WhatsApp/SMS link detection,
   and safe for spaces/`#`/`?` in custom names. Existing tokens are reused unchanged.

## Tests (TDD, red first)
- test_public_link: route rule from hooks matches `/s/LPO/26/09/00109-Fq0R` (werkzeug Map).
- test_public_link: doc named with "/" gets a slash-free token; link resolves via `get_short_link_target`.

## Verify
- `bench --site dev.localhost run-tests --app cecypo_powerpack --module cecypo_powerpack.tests.test_public_link`
- full app suite
- browser: create PO with "/" in name on dev, Copy as Message, open `/s/...` as guest.
- Deploy on Pramukh: pull + `bench clear-cache` (route rules are cached) — no migrate needed.
