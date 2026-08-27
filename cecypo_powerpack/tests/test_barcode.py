# Copyright (c) 2026, Cecypo.Tech and Contributors
# See license.txt

"""Tests for the QR code print-format helper.

The point of `qr_data_uri` is that a print format can render a barcode without
a network fetch, because wkhtmltopdf aborts the whole PDF on a failed <img>.
So the contract under test is: always a ``data:`` URI or an empty string,
never an exception and never a URL.
"""

import base64
import io

import frappe
from frappe.tests import UnitTestCase

from cecypo_powerpack.barcode import MAX_DATA_LENGTH, qr_data_uri

PREFIX = "data:image/png;base64,"


def decoded_png(uri: str) -> bytes:
	return base64.b64decode(uri.removeprefix(PREFIX))


class TestQrDataUri(UnitTestCase):
	def test_returns_inline_png_data_uri(self):
		uri = qr_data_uri("VRELE7905")

		self.assertTrue(uri.startswith(PREFIX))
		# PNG magic number - proves we emitted a real image, not a stub.
		self.assertEqual(decoded_png(uri)[:8], b"\x89PNG\r\n\x1a\n")

	def test_is_decodable_by_pillow(self):
		from PIL import Image

		image = Image.open(io.BytesIO(decoded_png(qr_data_uri("VRELE7905"))))
		image.verify()
		self.assertEqual(image.format, "PNG")

	def test_never_emits_a_url(self):
		"""A URL would reintroduce the network fetch this helper exists to avoid."""
		for value in ("VRELE7905", "https://example.com/x", "a b&c=d"):
			self.assertTrue(qr_data_uri(value).startswith(PREFIX), value)

	def test_blank_input_returns_empty_string(self):
		# An empty src is inert in both browsers and wkhtmltopdf; a template can
		# also gate on the falsy value.
		for value in ("", "   ", None):
			self.assertEqual(qr_data_uri(value), "")

	def test_distinct_payloads_produce_distinct_images(self):
		self.assertNotEqual(qr_data_uri("VRELE7905"), qr_data_uri("VRELE7906"))

	def test_scale_changes_image_size(self):
		self.assertLess(
			len(decoded_png(qr_data_uri("VRELE7905", scale=2))),
			len(decoded_png(qr_data_uri("VRELE7905", scale=10))),
		)

	def test_error_correction_levels_are_accepted(self):
		for level in ("L", "M", "Q", "H", "h"):
			self.assertTrue(qr_data_uri("VRELE7905", error_correction=level).startswith(PREFIX), level)

	def test_unknown_error_correction_falls_back_to_medium(self):
		self.assertEqual(
			qr_data_uri("VRELE7905", error_correction="Z"),
			qr_data_uri("VRELE7905", error_correction="M"),
		)

	def test_out_of_range_scale_and_border_are_clamped_not_rejected(self):
		for kwargs in ({"scale": 0}, {"scale": 9999}, {"border": -5}, {"border": 9999}):
			self.assertTrue(qr_data_uri("VRELE7905", **kwargs).startswith(PREFIX), kwargs)

	def test_oversized_payload_returns_empty_string(self):
		self.assertEqual(qr_data_uri("x" * (MAX_DATA_LENGTH + 1)), "")

	def test_payload_at_the_limit_still_renders(self):
		self.assertTrue(qr_data_uri("x" * MAX_DATA_LENGTH).startswith(PREFIX))

	def test_bad_argument_type_does_not_raise(self):
		"""An exception here would abort the entire print format render."""
		self.assertEqual(qr_data_uri("VRELE7905", scale="not-a-number"), "")


class TestQrDataUriJinjaHook(UnitTestCase):
	def test_exposed_to_print_formats_as_qr_data_uri(self):
		rendered = frappe.render_template('<img src="{{ qr_data_uri(code) }}">', {"code": "VRELE7905"})

		self.assertIn(f'src="{PREFIX}', rendered)

	def test_public_symbol_stays_a_plain_function(self):
		"""Frappe's jinja hook loader ignores anything that is not a FunctionType.

		Wrapping `qr_data_uri` in a decorator such as `lru_cache` makes it a
		`functools._lru_cache_wrapper`, which is dropped without warning.
		"""
		from types import FunctionType

		self.assertIsInstance(qr_data_uri, FunctionType)

	def test_unhashable_argument_does_not_raise(self):
		self.assertEqual(qr_data_uri("VRELE7905", scale=[4]), "")

	def test_survives_scrub_urls_untouched(self):
		"""scrub_urls must not prepend the site URL to a data: URI."""
		from frappe.utils.data import scrub_urls

		html = frappe.render_template('<img src="{{ qr_data_uri(code) }}">', {"code": "VRELE7905"})

		self.assertEqual(scrub_urls(html), html)
