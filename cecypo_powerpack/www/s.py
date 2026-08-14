"""
Public document viewer for PowerPack short links.
Handles URLs of the form /s/{doc.name}-{4-char-token}

- If PowerPack Settings.public_link_page is set, redirects to that Builder page
  with ?t=<token> so the Builder component handles the display.
- Otherwise renders the built-in branded viewer (s.html).
"""

import frappe

no_cache = 1


def get_context(context):
	token = frappe.form_dict.get("token")

	if not token:
		frappe.throw("Invalid link.", frappe.PageDoesNotExistError)

	short_link = frappe.db.get_value(
		"PowerPack Short Link",
		token,
		["target_url", "reference_doctype", "reference_docname", "expires_on"],
		as_dict=True,
	)

	if not short_link:
		frappe.throw("This link does not exist.", frappe.PageDoesNotExistError)

	if short_link.expires_on and str(short_link.expires_on) < frappe.utils.today():
		frappe.throw("This link has expired.", frappe.PageDoesNotExistError)

	# Atomic click counter — explicit commit needed before redirect exceptions
	frappe.db.sql(
		"UPDATE `tabPowerPack Short Link` SET click_count = COALESCE(click_count, 0) + 1 WHERE name = %s",
		token,
	)
	frappe.db.commit()

	# External links (no reference document) — just redirect directly
	if not short_link.reference_doctype:
		frappe.local.flags.redirect_location = short_link.target_url
		raise frappe.Redirect

	# If a Builder page route is configured, redirect there
	public_link_page = frappe.db.get_single_value("PowerPack Settings", "public_link_page")
	if public_link_page:
		route = public_link_page.rstrip("/")
		frappe.local.flags.redirect_location = f"{route}?t={token}"
		raise frappe.Redirect

	# Render the built-in viewer — populate template context
	context.no_cache = 1
	context.token = token
	context.target_url = short_link.target_url
	context.reference_doctype = short_link.reference_doctype
	context.reference_docname = short_link.reference_docname

	# Branding — prefer the company on the linked document (correct in multi-company setups)
	doc_company = frappe.db.get_value(
		short_link.reference_doctype,
		short_link.reference_docname,
		"company",
	)
	company = None
	if doc_company:
		company = frappe.db.get_value(
			"Company",
			doc_company,
			["company_name", "company_logo"],
			as_dict=True,
		)
	if not company:
		default_company = frappe.db.get_single_value("Global Defaults", "default_company")
		if default_company:
			company = frappe.db.get_value(
				"Company",
				default_company,
				["company_name", "company_logo"],
				as_dict=True,
			)
	if not company:
		rows = frappe.get_all("Company", fields=["company_name", "company_logo"], limit=1)
		company = rows[0] if rows else frappe._dict()

	context.company_name = company.get("company_name") or ""
	context.company_logo = company.get("company_logo") or ""

	# Website Settings fallback for logo / app name
	if not context.company_logo or not context.company_name:
		ws = frappe.get_single("Website Settings")
		context.company_logo = context.company_logo or ws.get("banner_image") or ""
		context.company_name = context.company_name or ws.get("app_name") or "Portal"

	# PowerPack banner / footer config
	# Offer M-Pesa only while the document is actually awaiting payment. No
	# payment request is created here - that happens if the customer presses Pay.
	from cecypo_powerpack.pay_by_link import get_payable, payable_gateways, receipt_for

	context.mpesa_payable = get_payable(
		short_link.reference_doctype, short_link.reference_docname
	)
	# Several shortcodes can collect for one company. Offer the choice rather
	# than picking one, since the wrong pick sends the money to the wrong till.
	context.mpesa_gateways = (
		payable_gateways(context.mpesa_payable["company"]) if context.mpesa_payable else []
	)
	if not context.mpesa_gateways:
		context.mpesa_payable = None
	# The raw figure as well as the formatted one: the sheet lets the payer edit
	# what they send, so the script needs a number to validate against.
	context.mpesa_amount = context.mpesa_payable["amount"] if context.mpesa_payable else 0
	context.mpesa_currency = (
		context.mpesa_payable["currency"] if context.mpesa_payable else ""
	)
	context.mpesa_amount_display = (
		frappe.utils.fmt_money(
			context.mpesa_payable["amount"], currency=context.mpesa_payable["currency"]
		)
		if context.mpesa_payable
		else ""
	)

	# A staff member previewing the link is a logged-in session, and Frappe
	# enforces CSRF on POST for anyone who is not Guest - without this the
	# payment calls come back as "Invalid Request". Guests need no token.
	# Frappe exempts Guest from CSRF, so a paying customer needs no token. A
	# signed-in viewer does, or the payment calls come back "Invalid Request".
	context.csrf_token = ""
	if frappe.session.user != "Guest":
		try:
			# Imported here rather than as frappe.sessions: importing frappe
			# does not bind its submodules.
			from frappe.sessions import get_csrf_token

			context.csrf_token = get_csrf_token()
		except Exception:
			# Never fatal. Without a token a signed-in previewer's payment is
			# refused, but the page itself must still render for customers.
			frappe.log_error(
				frappe.get_traceback(), "Pay by link: could not issue a CSRF token"
			)

	# Nothing left to pay: offer the receipt instead of a dead toolbar.
	context.mpesa_receipt = (
		None
		if context.mpesa_payable
		else receipt_for(short_link.reference_doctype, short_link.reference_docname)
	)

	ps = frappe.get_single("PowerPack Settings")
	context.top_banner = ps.get("public_link_top_banner") or ""
	context.top_banner_link = ps.get("public_link_top_banner_link") or ""
	context.header_content = ps.get("public_link_header_content") or ""
	context.footer_content = ps.get("public_link_footer_content") or ""
	context.hide_header = bool(ps.get("public_link_hide_header"))
