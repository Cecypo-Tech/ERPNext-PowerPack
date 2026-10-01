# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""Copy as Image: a PNG of a document's print, for pasting into chat apps.

The picture is rendered from the same PDF the PDF button downloads, so fonts, images
and letterheads come out exactly as printed - a browser screenshot of the preview
HTML gets those wrong. Every page is stacked into one tall image; blank pages at the end
are dropped and the blank space below the last page's content is trimmed.
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

# Each render holds a web worker for seconds, so cap them like frappe's own PDF download.
# frappe.concurrent_limit only exists from v16.33; older sites go without.
_concurrent_limit = getattr(frappe, "concurrent_limit", lambda: lambda fn: fn)


@frappe.whitelist(methods=["GET"])
@_concurrent_limit()
def get_print_image(
	doctype, name, print_format=None, letterhead=None, no_letterhead=0, lang=None, settings=None
):
	"""Respond with a PNG of the document's print, shown inline.

	``settings`` is the print preview sidebar's JSON (Compact Item Print and the like). As
	for frappe's PDF download, printview reads it from ``form_dict``.
	"""
	from frappe.translate import print_language

	if not is_feature_enabled("enable_copy_as_image"):
		frappe.throw(_("Copy as Image is turned off in PowerPack Settings"))
	if doctype not in DOCTYPES:
		frappe.throw(_("Copy as Image is not available for {0}").format(_(doctype)))

	doc = frappe.get_doc(doctype, name)
	doc.check_permission("print")

	print_format = print_format or frappe.get_meta(doctype).default_print_format or "Standard"
	if frappe.db.get_value("Print Format", print_format, "raw_printing"):
		# Printer commands (ESC/P, ESC/POS), not a page: there is nothing to picture.
		frappe.throw(
			_("{0} is a raw printing format and cannot be copied as an image. Choose another print format.").format(
				frappe.bold(print_format)
			)
		)
	frappe.local.form_dict.settings = settings
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
	"""Stack ``pages`` top to bottom, dropping blank pages at the end and trimming blank
	space below the last one's content."""
	while len(pages) > 1 and _content_box(pages[-1]) is None:
		pages = pages[:-1]
	pages = [*pages[:-1], _trim_bottom(pages[-1])]
	image = Image.new("RGB", (max(p.width for p in pages), sum(p.height for p in pages)), "white")
	top = 0
	for page in pages:
		image.paste(page, (0, top))
		top += page.height
	return image


def _content_box(page: Image.Image):
	return ImageChops.difference(page, Image.new(page.mode, page.size, "white")).getbbox()


def _trim_bottom(page: Image.Image) -> Image.Image:
	box = _content_box(page)
	if not box:
		return page
	return page.crop((0, 0, page.width, min(page.height, box[3] + TRIM_MARGIN)))
