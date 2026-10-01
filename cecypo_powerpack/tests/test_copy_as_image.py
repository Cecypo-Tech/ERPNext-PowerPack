# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

import io
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from cecypo_powerpack import copy_as_image
from cecypo_powerpack.copy_as_image import MAX_PAGES, get_print_image, pdf_to_png, stitch_pages

NO_ACCESS_USER = "pp-copy-as-image-no-access@example.com"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _page(height, ink_until=None, width=100):
	"""A white page, inked black from the top down to ``ink_until`` (default: all of it)."""
	page = Image.new("RGB", (width, height), "white")
	ink_until = height if ink_until is None else ink_until
	if ink_until:
		page.paste((0, 0, 0), (0, 0, width, ink_until))
	return page


def _pdf(pages):
	"""A real PDF of ``pages`` A4 pages, made by the site's own PDF generator."""
	from frappe.utils.pdf import get_pdf

	body = '<div style="page-break-after: always">page</div>' * (pages - 1) + "<div>last</div>"
	return get_pdf(f"<html><body>{body}</body></html>")


class TestStitchPages(FrappeTestCase):
	def test_stacks_every_page_top_to_bottom(self):
		image = stitch_pages([_page(50), _page(50), _page(50)])

		self.assertEqual(image.size, (100, 150))

	def test_trims_blank_space_below_the_last_page_only(self):
		# The middle page's blank half stays - only the tail of the document is dead space.
		image = stitch_pages([_page(100), _page(100, ink_until=40), _page(100, ink_until=30)])

		self.assertEqual(image.height, 100 + 100 + 30 + copy_as_image.TRIM_MARGIN)

	def test_drops_blank_pages_at_the_end(self):
		# A format ending in a page break leaves an empty last page - not a blank A4 in chat.
		image = stitch_pages([_page(100), _page(100, ink_until=30), _page(100, ink_until=0), _page(100, ink_until=0)])

		self.assertEqual(image.height, 100 + 30 + copy_as_image.TRIM_MARGIN)

	def test_keeps_one_page_when_every_page_is_blank(self):
		# Nothing to trim to - don't collapse it to zero height.
		image = stitch_pages([_page(100, ink_until=0), _page(100, ink_until=0)])

		self.assertEqual(image.height, 100)


class TestPdfToPng(FrappeTestCase):
	def test_renders_every_page_of_a_real_pdf_into_one_png(self):
		one = Image.open(io.BytesIO(pdf_to_png(_pdf(1))))
		two = Image.open(io.BytesIO(pdf_to_png(_pdf(2))))

		self.assertEqual(one.format, "PNG")
		self.assertEqual(one.width, two.width)
		self.assertGreater(two.height, one.height)
		# ~150 DPI across an A4 / Letter page width.
		self.assertTrue(1150 < one.width < 1350, one.width)

	def test_stops_at_max_pages(self):
		capped = Image.open(io.BytesIO(pdf_to_png(_pdf(MAX_PAGES + 2))))
		full = Image.open(io.BytesIO(pdf_to_png(_pdf(MAX_PAGES))))

		self.assertEqual(capped.height, full.height)


def _call(doctype, name, **kwargs):
	# The render itself is covered above; here only the guard and the response matter.
	with patch.object(copy_as_image, "pdf_to_png", return_value=PNG_MAGIC + b"png"):
		with patch.object(frappe, "get_print", return_value=b"%PDF") as get_print:
			get_print_image(doctype, name, **kwargs)
	return get_print


class TestGetPrintImageGuards(FrappeTestCase):
	"""Checked before the document is loaded, so they need none on the site."""

	def tearDown(self):
		frappe.db.rollback()

	def test_refuses_doctypes_outside_the_four(self):
		with self.assertRaises(frappe.ValidationError):
			_call("User", "Administrator")

	def test_refuses_when_the_setting_is_off(self):
		frappe.db.set_single_value("PowerPack Settings", "enable_copy_as_image", 0)

		with self.assertRaises(frappe.ValidationError):
			_call("Sales Invoice", "does-not-matter")


class TestGetPrintImage(FrappeTestCase):
	"""The endpoint hands out a picture of the print, so it guards like the PDF download."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.name = frappe.db.get_value("Sales Invoice", {"docstatus": 1}, "name")

	def setUp(self):
		if not self.name:
			self.skipTest("needs a submitted Sales Invoice on the site")
		if not frappe.db.exists("User", NO_ACCESS_USER):
			frappe.get_doc(
				{"doctype": "User", "email": NO_ACCESS_USER, "first_name": "No Access", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.db.set_single_value("PowerPack Settings", "enable_copy_as_image", 1)
		frappe.local.response.pop("filecontent", None)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _call(self, **kwargs):
		return _call("Sales Invoice", self.name, **kwargs)

	def test_returns_the_png_inline(self):
		# Named, because a site's default format may be a raw (ESC/P) one, which is refused.
		self._call(print_format="Standard")

		response = frappe.local.response
		self.assertEqual(response.filecontent, PNG_MAGIC + b"png")
		self.assertEqual(response.type, "download")
		self.assertEqual(response.content_type, "image/png")
		self.assertEqual(response.display_content_as, "inline")
		self.assertTrue(response.filename.endswith(".png"))
		self.assertNotIn("/", response.filename)

	def test_passes_the_selected_format_letterhead_and_generator_through(self):
		get_print = self._call(print_format="Standard", letterhead="LH", no_letterhead="1")

		kwargs = get_print.call_args.kwargs
		self.assertEqual(kwargs["as_pdf"], True)
		self.assertEqual(get_print.call_args.args[:3], ("Sales Invoice", self.name, "Standard"))
		self.assertEqual(kwargs["letterhead"], "LH")
		self.assertEqual(kwargs["no_letterhead"], 1)
		self.assertIn(kwargs["pdf_generator"], ("wkhtmltopdf", "chrome"))

	def test_renders_with_the_print_settings_ticked_in_the_preview_sidebar(self):
		# Compact Item Print etc. reach printview through form_dict.settings, as with the PDF button.
		seen = {}

		def get_print(*args, **kwargs):
			seen["settings"] = frappe.form_dict.get("settings")
			return b"%PDF"

		settings = '{"compact_item_print": 1}'
		with patch.object(copy_as_image, "pdf_to_png", return_value=PNG_MAGIC):
			with patch.object(frappe, "get_print", side_effect=get_print):
				get_print_image("Sales Invoice", self.name, print_format="Standard", settings=settings)

		self.assertEqual(seen["settings"], settings)

	def test_refuses_a_raw_printing_format(self):
		# ESC/P and ESC/POS formats are printer commands; there is no PDF to picture.
		frappe.get_doc(
			{
				"doctype": "Print Format",
				"name": "PP Copy as Image Raw Test",
				"doc_type": "Sales Invoice",
				"standard": "No",
				"custom_format": 1,
				"raw_printing": 1,
				"raw_commands": "ESC @",
			}
		).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError) as caught:
			self._call(print_format="PP Copy as Image Raw Test")
		self.assertIn("raw printing", str(caught.exception))

	def test_refuses_a_user_who_cannot_print_the_document(self):
		frappe.set_user(NO_ACCESS_USER)

		with self.assertRaises(frappe.PermissionError):
			self._call()

