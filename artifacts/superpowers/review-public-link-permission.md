# Review: permission check on get_document_public_link

Branch: fix/public-link-permission

## Bug
`cecypo_powerpack.api.get_document_public_link` (whitelisted) loaded the document with
`frappe.get_doc`, which does not check permission, and returned a guest-viewable short
link. Any logged-in user could mint a public link to any document of any doctype by name,
including ones they cannot open. The reuse path (existing short link) returned before
any check too.

## Fix
- `api.get_document_public_link`: `doc.check_permission("read")`, then `build_public_link(doc)`.
- `api.build_public_link(doc)`: the old body, unchanged apart from taking the doc.
- `jinja.get_document_public_link`: new; the Jinja method print formats call, no check.
  hooks.py `jinja.methods` now points here. Frappe exposes a Jinja method under its
  function name (utils/jinja.py:246), so templates keep calling
  `get_document_public_link(...)`. It must not check: a share-key web view renders the
  print format as Guest. Only privileged users author print formats.

Read (not share) is the bar: a user who can read a document can already print or PDF it
and send it.

## Verification
- `run-tests --module cecypo_powerpack.tests.test_public_link`: 4 tests. Before the fix the
  two refusal tests failed (PermissionError not raised); after, all 4 pass.
  - no-read user -> PermissionError, no Short Link created
  - no-read user refused even when a link already exists (reuse path)
  - reader gets a /s/ link
  - Jinja method resolved through frappe's get_jinja_hooks works as Guest
- Browser (Administrator): Sales Invoice POS-00239 > Powerup > Copy as Message still copies
  the link; the /s/ link returns 200.
- Full app suite (no other test run on the site): 316 tests OK. An earlier run that overlapped another session hit 2 QueryDeadlockErrors; clean on rerun.

## Findings
- Blocker / Major: none.
- Minor: a site whose print format called the Jinja method is unaffected; a custom
  Client/Server Script that called the whitelisted API for documents the user cannot read
  now gets PermissionError (intended). None exist on dev.
