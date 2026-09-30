# Execution: short links for document names containing "/"

## Step 1 — route matches tokens containing "/"
- Files: cecypo_powerpack/hooks.py, cecypo_powerpack/tests/test_public_link.py
- `/s/<token>` -> `/s/<path:token>`; comment says why.
- New TestShortLinkRoute builds a werkzeug Map from the app's own website_route_rules hook.
- Verify: `bench --site dev.localhost run-tests --app cecypo_powerpack --module cecypo_powerpack.tests.test_public_link`
- Result: red first (None != ('s', {'token': 'LPO/26/09/00109-Fq0R'})), then 6/6 pass.

## Step 2 — new tokens are URL-safe
- Files: cecypo_powerpack/api.py, cecypo_powerpack/www/s.py (docstring), cecypo_powerpack/tests/test_public_link.py
- build_public_link: slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "doc"; token = f"{slug}-{suffix}".
- Reused tokens are returned as stored (old slashed ones still route via Step 1).
- New TestTokenForNamesWithSlashes: Role "PP/Slash Test/00109" -> token PP-Slash-Test-00109-XXXX, resolves via get_short_link_target.
- Verify: same module run.
- Result: red first ('PP/Slash Test/00109-xxJw' didn't match), then 7/7 pass.

## Step 3 — verification + review
- Full suite: `bench --site dev.localhost run-tests --app cecypo_powerpack` -> 346 tests OK (1 skipped).
- Guest HTTP on dev: /s/<plain> 200, /s/LPO/26/09/E2E-Test 200, /s/LPO%2F26%2F09%2FE2E-Test 200, unknown slashed 404. Seeded link deleted after.
- Code review (subagent): Ready to merge, no Critical/Important.
