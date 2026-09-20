(function () {

frappe.ui.form.on('Email Queue', {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.message) return;
		render_email_preview(frm);
	},
});

function render_email_preview(frm) {
	const raw = frm.doc.message;

	// -------------------------------
	// Extract HTML (Robust)
	// -------------------------------
	function extractHTML(raw) {
		const parts = raw.split('Content-Type: text/html');
		if (parts.length < 2) return null;

		let htmlPart = parts[1];
		const startIndex = htmlPart.indexOf('\r\n\r\n');
		if (startIndex === -1) return null;

		htmlPart = htmlPart.substring(startIndex + 4);

		const boundaryIndex = htmlPart.indexOf('\r\n--');
		if (boundaryIndex !== -1) htmlPart = htmlPart.substring(0, boundaryIndex);

		return htmlPart.trim();
	}

	// -------------------------------
	// Extract Plain Text (fallback)
	// -------------------------------
	function extractText(raw) {
		const parts = raw.split('Content-Type: text/plain');
		if (parts.length < 2) return 'No content found';

		let textPart = parts[1];
		const startIndex = textPart.indexOf('\r\n\r\n');
		if (startIndex === -1) return 'No content found';

		textPart = textPart.substring(startIndex + 4);
		const boundaryIndex = textPart.indexOf('\r\n--');
		if (boundaryIndex !== -1) textPart = textPart.substring(0, boundaryIndex);

		return textPart.trim();
	}

	// -------------------------------
	// Decode quoted-printable
	// -------------------------------
	function decodeQP(str) {
		return str
			.replace(/=\r?\n/g, '') // remove soft breaks
			.replace(/=([A-Fa-f0-9]{2})/g, function (match, hex) {
				return String.fromCharCode(parseInt(hex, 16));
			});
	}

	const html = extractHTML(raw);
	const text = extractText(raw);
	const finalContent = html
		? decodeQP(html)
		: `<pre style="white-space:pre-wrap;">${frappe.utils.escape_html(decodeQP(text))}</pre>`;

	const message_field = frm.fields_dict.message;
	if (!message_field) return;

	// Hide the raw Code editor control that shows the message as-is
	message_field.$wrapper.hide();

	// Re-render cleanly on every refresh instead of stacking duplicates
	frm.$wrapper.find('#email-preview-block').remove();

	const $block = $(`
		<div id="email-preview-block" class="form-group" style="margin-bottom: 15px;">
			<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
				<label class="control-label" style="margin:0;">${__('Message')}</label>
				<button type="button" class="btn btn-xs btn-default" id="email-preview-toggle">
					${__('View Raw Source')}
				</button>
			</div>
			<div id="email-preview-rendered" style="border:1px solid var(--border-color, #d1d8dd); border-radius:4px; overflow:hidden;">
				<iframe style="width:100%; height:600px; border:none; display:block;"></iframe>
			</div>
			<div id="email-preview-raw" style="display:none;">
				<pre style="max-height:600px; overflow:auto; background:var(--bg-color, #f4f5f6); padding:10px; border-radius:4px; white-space:pre-wrap; word-break:break-word;"></pre>
			</div>
		</div>
	`);

	message_field.$wrapper.after($block);

	// Raw pane: plain text, escaped by jQuery's .text()
	$block.find('#email-preview-raw pre').text(raw);

	// Rendered pane: sandboxed iframe so the email's own CSS/HTML can't touch the desk
	const iframe = $block.find('iframe')[0];
	iframe.setAttribute('sandbox', '');
	setTimeout(() => {
		if (iframe && iframe.contentWindow) {
			iframe.contentWindow.document.open();
			iframe.contentWindow.document.write(finalContent);
			iframe.contentWindow.document.close();
		}
	}, 200);

	// Toggle between rendered preview and raw source
	$block.find('#email-preview-toggle').on('click', function () {
		const $btn = $(this);
		const raw_visible = $block.find('#email-preview-raw').is(':visible');
		if (raw_visible) {
			$block.find('#email-preview-raw').hide();
			$block.find('#email-preview-rendered').show();
			$btn.text(__('View Raw Source'));
		} else {
			$block.find('#email-preview-rendered').hide();
			$block.find('#email-preview-raw').show();
			$btn.text(__('View Preview'));
		}
	});
}

})();
