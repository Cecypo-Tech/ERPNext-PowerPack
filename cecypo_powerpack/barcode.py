# Copyright (c) 2026, Cecypo.Tech and contributors
# For license information, please see license.txt

"""Barcode helpers for print formats.

`qr_data_uri` renders a QR code directly into the HTML as a ``data:`` URI so a
print format never depends on a network fetch. This matters because
wkhtmltopdf treats a failed ``<img>`` as fatal: it aborts with a network error
and `frappe.utils.pdf.get_pdf` turns that into "PDF generation failed because
of broken image links", killing the whole PDF. Browsers only show a broken
image icon, so such a format still previews fine — the failure surfaces only
when a PDF is generated (emails, WhatsApp attachments, Download PDF).

An inline data URI has no such failure mode. `frappe.utils.data.scrub_urls`
skips ``data:`` URIs, and `frappe.utils.pdf.inline_private_images` ignores them
too, so the value reaches wkhtmltopdf untouched.
"""

import base64
import io
from functools import lru_cache

import frappe

# Guard against a caller passing a whole document into a QR code. Well beyond
# any item code, invoice name or short link we put on a print format.
MAX_DATA_LENGTH = 512

# Bounds keep a runaway argument from producing a multi-megabyte PNG.
MAX_SCALE = 20
MAX_BORDER = 16


def qr_data_uri(data: str, scale: int = 4, border: int = 2, error_correction: str = "M") -> str:
	"""Return a QR code encoding `data` as a base64 PNG ``data:`` URI.

	:param data: Text to encode, e.g. an item code or a document short link.
	:param scale: Pixel size of one QR module (1-20).
	:param border: Quiet-zone width in modules (0-16). The spec requires 4;
	        2 is usually enough on paper and saves space.
	:param error_correction: One of ``L``, ``M``, ``Q``, ``H`` — rising
	        redundancy, and rising QR size for the same payload.

	Returns an empty string when `data` is empty or the QR cannot be built.
	This never raises: an exception inside a print format aborts the entire
	render, and a missing barcode is not worth losing the document over. An
	empty ``src`` is inert in both browsers and wkhtmltopdf.

	Results are memoised because a batch print (item labels, a picking list)
	re-renders the same codes many times, and the output is deterministic.
	"""
	data = frappe.utils.cstr(data).strip()
	if not data:
		return ""

	try:
		return _render_qr(data, scale, border, error_correction)
	except TypeError:
		# An unhashable argument would blow up in the lru_cache lookup itself,
		# before _render_qr's own error handling could catch it.
		frappe.log_error(title="qr_data_uri: unhashable argument")
		return ""


@lru_cache(maxsize=256)
def _render_qr(data: str, scale, border, error_correction) -> str:
	"""Build the data URI. Split out so `qr_data_uri` stays a plain function.

	`frappe.utils.jinja.get_obj_dict_from_paths` only registers hook targets
	that are a `types.FunctionType`; an `lru_cache` wrapper is silently
	dropped, leaving the method undefined in print formats.
	"""
	import qrcode

	if len(data) > MAX_DATA_LENGTH:
		frappe.log_error(
			title="qr_data_uri: payload too long",
			message=f"{len(data)} chars exceeds MAX_DATA_LENGTH={MAX_DATA_LENGTH}",
		)
		return ""

	levels = {
		"L": qrcode.constants.ERROR_CORRECT_L,
		"M": qrcode.constants.ERROR_CORRECT_M,
		"Q": qrcode.constants.ERROR_CORRECT_Q,
		"H": qrcode.constants.ERROR_CORRECT_H,
	}

	try:
		qr = qrcode.QRCode(
			box_size=min(max(int(scale), 1), MAX_SCALE),
			border=min(max(int(border), 0), MAX_BORDER),
			error_correction=levels.get(str(error_correction).upper(), qrcode.constants.ERROR_CORRECT_M),
		)
		qr.add_data(data)
		qr.make(fit=True)

		buffer = io.BytesIO()
		qr.make_image(fill_color="black", back_color="white").save(buffer, format="PNG")
	except Exception:
		frappe.log_error(title="qr_data_uri: failed to build QR code")
		return ""

	encoded = base64.b64encode(buffer.getvalue()).decode()
	return f"data:image/png;base64,{encoded}"
