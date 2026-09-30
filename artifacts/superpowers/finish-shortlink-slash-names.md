# Finish: short links for document names containing "/"

## Problem
`/s/LPO/26/09/00109-Fq0R` (Pramukh PO) 404'd. Token = `{name}-{suffix}`; route `/s/<token>`
matches one path segment only.

## Changes
- hooks.py: `/s/<token>` -> `/s/<path:token>` - already-sent slashed links resolve.
- api.py build_public_link: new tokens slug the name (`[^A-Za-z0-9._-]+` -> `-`), e.g.
  `LPO-26-09-00109-x7kQ`. Existing tokens reused unchanged.
- www/s.py docstring; tests in tests/test_public_link.py (route + token), both red first.

## Verification
- `bench --site dev.localhost run-tests --app cecypo_powerpack` -> 346 OK
- `... --module cecypo_powerpack.tests.test_public_link` -> 7 OK
- Guest curl against dev server: plain / slashed / %2F-encoded tokens 200; unknown 404.

## Review (Blocker/Major/Minor/Nit)
- Blocker: none. Major: none.
- Minor: Deploy MUST run `bench clear-cache` - frappe caches the failed URL in `website_404`
  and the route rules in `website_route_rules`; without it the supplier's link stays 404.
- Minor: Short Link form JS shows `/s/LPO%2F26%2F...` for old slashed tokens (works, ugly).
- Minor: non-ASCII letters are dropped from new token slugs (`Müller` -> `M-ller`).
- Nit: no test drives www/s.py get_context with a slashed token (covered by manual HTTP check).

## Deploy (Pramukh)
Pull cecypo_powerpack, then `bench --site <site> clear-cache`. No migrate, no build.

## Manual validation
Open https://erp.pramukh.co.ke/s/LPO/26/09/00109-Fq0R as guest after deploy -> PO renders.
