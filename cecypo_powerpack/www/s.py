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
	ps = frappe.get_single("PowerPack Settings")
	context.top_banner = ps.get("public_link_top_banner") or ""
	context.top_banner_link = ps.get("public_link_top_banner_link") or ""
	context.header_content = ps.get("public_link_header_content") or ""
	context.footer_content = ps.get("public_link_footer_content") or ""
	context.hide_header = bool(ps.get("public_link_hide_header"))
