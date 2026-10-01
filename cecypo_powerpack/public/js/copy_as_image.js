// Copyright (c) 2026, Cecypo.Tech and contributors
// For license information, please see license.txt

// Copy as Image: puts a PNG of a document's print on the clipboard, for pasting into
// WhatsApp or any chat. The server renders it from the same PDF the PDF button makes
// (cecypo_powerpack/copy_as_image.py).
//
// Two entry points: Powerup > Copy as Image on the form (default print format and
// letterhead), and a Copy as Image button on the print preview (whatever format,
// letterhead and language are selected there).

frappe.provide('cecypo_powerpack.copy_as_image');

cecypo_powerpack.copy_as_image = {
	DOCTYPES: ['Quotation', 'Sales Order', 'Sales Invoice', 'Purchase Order'],
	METHOD: '/api/method/cecypo_powerpack.copy_as_image.get_print_image',

	// Must run inside the click handler. Safari only lets a page write to the clipboard
	// during the click, so the ClipboardItem is handed the pending fetch right away
	// rather than created after the image arrives.
	copy(args) {
		frappe.show_alert({ message: __('Preparing image…'), indicator: 'blue' }, 10);

		const png = this.fetch_png(args);
		let written;
		try {
			written = navigator.clipboard.write([new ClipboardItem({ 'image/png': png })]);
		} catch (e) {
			written = Promise.reject(e);
		}

		written
			.then(() => frappe.show_alert({ message: __('Image copied'), indicator: 'green' }))
			.catch(() =>
				// Either the browser cannot put an image on the clipboard, or the render
				// failed. Download it in the first case; say why in the second.
				png.then(
					(blob) => {
						this.download(blob, args.name);
						frappe.show_alert({
							message: __('This browser cannot copy images, so it was downloaded instead'),
							indicator: 'orange',
						});
					},
					(e) => frappe.msgprint(e.message || __('Failed to create the image'))
				)
			);
	},

	async fetch_png(args) {
		const params = new URLSearchParams();
		for (const [key, value] of Object.entries(args)) {
			if (value !== undefined && value !== null && value !== '') params.append(key, value);
		}
		const r = await fetch(`${this.METHOD}?${params}`, {
			credentials: 'same-origin',
			headers: { 'X-Frappe-CSRF-Token': frappe.csrf_token },
		});
		if (!r.ok) throw new Error(await this.error_message(r));
		return new Blob([await r.arrayBuffer()], { type: 'image/png' });
	},

	async error_message(r) {
		try {
			const body = await r.json();
			const messages = JSON.parse(body._server_messages || '[]').map((m) => JSON.parse(m).message);
			if (messages.length) return messages.join('<br>');
			if (body.exc_type) return __(body.exc_type);
		} catch (e) {
			// Not a frappe error body - fall through.
		}
		return __('Failed to create the image');
	},

	download(blob, name) {
		const a = document.createElement('a');
		a.href = URL.createObjectURL(blob);
		a.download = `${name.replace(/[ /]/g, '-')}.png`;
		document.body.appendChild(a);
		a.click();
		a.remove();
		setTimeout(() => URL.revokeObjectURL(a.href), 1000);
	},

	// Print preview: frappe.ui.form.PrintView is defined by the print page's own script,
	// which loads after this bundle. Patch the class the moment it is assigned, before the
	// page builds its one instance.
	patch_print_view(PrintView) {
		if (!PrintView || PrintView.prototype._pp_copy_as_image) return PrintView;
		PrintView.prototype._pp_copy_as_image = true;

		const show = PrintView.prototype.show;
		PrintView.prototype.show = function (frm) {
			const result = show.apply(this, arguments);
			cecypo_powerpack.copy_as_image.setup_print_view_button(this);
			return result;
		};
		return PrintView;
	},

	setup_print_view_button(view) {
		const me = this;
		if (!view._pp_copy_image) {
			const label = __('Copy as Image');
			const click = () =>
				me.copy({
					doctype: view.frm.doc.doctype,
					name: view.frm.doc.name,
					print_format: view.selected_format(),
					letterhead: view.with_letterhead() ? view.get_letterhead() : '',
					no_letterhead: view.with_letterhead() ? 0 : 1,
					lang: view.lang_code,
				});
			const $button = view.page.add_button(label, click, { icon: 'image' });
			// add_button also adds a mobile menu item; asking again returns that same item.
			const $item = view.page.add_menu_item(label, click, false).parent();
			view._pp_copy_image = $button.add($item);
		}

		// One PrintView serves every document, so decide per document.
		view._pp_copy_image.toggle(false);
		if (!this.DOCTYPES.includes(view.frm.doctype)) return;
		CecypoPowerPack.Settings.isEnabled('enable_copy_as_image', (enabled) => {
			view._pp_copy_image.toggle(!!enabled && this.DOCTYPES.includes(view.frm.doctype));
		});
	},
};

(() => {
	const me = cecypo_powerpack.copy_as_image;

	for (const doctype of me.DOCTYPES) {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				if (frm.is_new() || frm.doc.docstatus === 2) return;
				CecypoPowerPack.Settings.isEnabled('enable_copy_as_image', (enabled) => {
					if (!enabled) return;
					frm.add_custom_button(
						__('Copy as Image'),
						() => me.copy({ doctype: frm.doc.doctype, name: frm.doc.name }),
						__('Powerup')
					);
				});
			},
		});
	}

	let PrintView = me.patch_print_view(frappe.ui.form.PrintView);
	Object.defineProperty(frappe.ui.form, 'PrintView', {
		configurable: true,
		enumerable: true,
		get: () => PrintView,
		set: (value) => {
			PrintView = me.patch_print_view(value);
		},
	});
})();
