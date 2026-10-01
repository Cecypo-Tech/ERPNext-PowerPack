# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""Copy as Image: a PNG of a document's print, for pasting into chat apps.

The picture is rendered from the same PDF the PDF button downloads, so fonts, images
and letterheads come out exactly as printed - a browser screenshot of the preview
HTML gets those wrong. Every page is stacked into one tall image and the blank space
below the last page's content is trimmed.
"""

import io

import frappe
from frappe import _
from PIL import Image, ImageChops

from cecypo_powerpack.utils import is_feature_enabled

DOCTYPES = ("Quotation", "Sales Order", "Sales Invoice", "Purchase Order")

# ~150 DPI: an A4 page comes out ~1240px wide, sharp on a phone without being heavy.
SCALE = 150 / 72
# A runaway print should not turn into a 50,000px image.
MAX_PAGES = 10
# White kept below the last line of content when the last page is trimmed.
TRIM_MARGIN = 40


@frappe.whitelist(methods=["GET"])
def get_print_image(doctype, name, print_format=None, letterhead=None, no_letterhead=0, lang=None):
	"""Respond with a PNG of the document's print, shown inline."""
	from frappe.translate import print_language

	if not is_feature_enabled("enable_copy_as_image"):
		frappe.throw(_("Copy as Image is turned off in PowerPack Settings"))
	if doctype not in DOCTYPES:
		frappe.throw(_("Copy as Image is not available for {0}").format(_(doctype)))

	doc = frappe.get_doc(doctype, name)
	doc.check_permission("print")

	print_format = print_format or frappe.get_meta(doctype).default_print_format or "Standard"
	with print_language(lang or None):
		pdf = frappe.get_print(
			doctype,
			name,
			print_format,
			doc=doc,
			as_pdf=True,
			letterhead=letterhead or None,
			no_letterhead=frappe.utils.cint(no_letterhead),
			pdf_generator=_pdf_generator(print_format),
		)

	frappe.local.response.filename = "{}.png".format(name.replace(" ", "-").replace("/", "-"))
	frappe.local.response.filecontent = pdf_to_png(pdf)
	frappe.local.response.content_type = "image/png"
	frappe.local.response.display_content_as = "inline"
	frappe.local.response.type = "download"


def _pdf_generator(print_format):
	# Same order as the print page's PDF button: the format's own, then Print Settings.
	return (
		frappe.db.get_value("Print Format", print_format, "pdf_generator")
		or frappe.db.get_single_value("Print Settings", "pdf_generator")
		or "wkhtmltopdf"
	)


def pdf_to_png(pdf: bytes) -> bytes:
	"""Render up to MAX_PAGES pages of ``pdf`` and return them stacked as one PNG."""
	import pypdfium2

	document = pypdfium2.PdfDocument(pdf)
	try:
		pages = [
			document[i].render(scale=SCALE).to_pil().convert("RGB")
			for i in range(min(len(document), MAX_PAGES))
		]
	finally:
		document.close()

	out = io.BytesIO()
	stitch_pages(pages).save(out, format="PNG", optimize=True)
	return out.getvalue()


def stitch_pages(pages: list[Image.Image]) -> Image.Image:
	"""Stack ``pages`` top to bottom, trimming blank space below the last one's content."""
	pages = [*pages[:-1], _trim_bottom(pages[-1])]
	image = Image.new("RGB", (max(p.width for p in pages), sum(p.height for p in pages)), "white")
	top = 0
	for page in pages:
		image.paste(page, (0, top))
		top += page.height
	return image


def _trim_bottom(page: Image.Image) -> Image.Image:
	blank = Image.new(page.mode, page.size, "white")
	box = ImageChops.difference(page, blank).getbbox()
	if not box:
		return page
	return page.crop((0, 0, page.width, min(page.height, box[3] + TRIM_MARGIN)))
