// Copyright (c) 2026, Cecypo.Tech and contributors
// For license information, please see license.txt

// Copy as Image: puts a PNG of a document's print on the clipboard, for pasting into
// WhatsApp or any chat. The server renders it from the same PDF the PDF button makes
// (cecypo_powerpack/copy_as_image.py).
//
// Two entry points: Powerup > Copy as Image on the form (default print format and
// letterhead), and the same Powerup menu on the print preview (whatever format,
// letterhead and language are selected there). The print preview's Powerup also
// carries the site's Copy as Message Client Script (see setup_copy_message below),
// so both menus offer the same actions.

frappe.provide('cecypo_powerpack.copy_as_image');

cecypo_powerpack.copy_as_image = {
	DOCTYPES: ['Quotation', 'Sales Order', 'Sales Invoice', 'Purchase Order'],
	METHOD: '/api/method/cecypo_powerpack.copy_as_image.get_print_image',

	// Must run inside the click handler. Safari only lets a page write to the clipboard
	// during the click, so the ClipboardItem is handed the pending fetch right away
	// rather than created after the image arrives.
	copy(args) {
		// A render takes a few seconds and holds a server worker; ignore repeat clicks.
		if (this.busy) return;
		this.busy = true;
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
				// Either the clipboard refused the image (an older browser, or the tab lost
				// focus while it rendered), or the render failed. Download it in the first
				// case; say why in the second.
				png.then(
					(blob) => {
						this.download(blob, args.name);
						frappe.show_alert({
							message: __('Could not copy the image, so it was downloaded instead'),
							indicator: 'orange',
						});
					},
					(e) => frappe.msgprint(e.message || __('Failed to create the image'))
				)
			)
			.finally(() => {
				this.busy = false;
			});
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
			const me = cecypo_powerpack.copy_as_image;
			me.setup_print_view_powerup(this);
			// show() picks this document's print format in async tasks; look again once set.
			Promise.resolve(result).then(() => me.update_print_view_powerup(this));
			return result;
		};
		// Runs whenever the print format changes. A raw-printing format has no PDF, and
		// frappe hides its own PDF button for one, so hide Copy as Image too (Copy as
		// Message does not depend on the format and stays).
		const toggle_raw_printing = PrintView.prototype.toggle_raw_printing;
		PrintView.prototype.toggle_raw_printing = function () {
			const result = toggle_raw_printing.apply(this, arguments);
			cecypo_powerpack.copy_as_image.update_print_view_powerup(this);
			return result;
		};
		return PrintView;
	},

	setup_print_view_powerup(view) {
		const me = this;
		if (!view._pp_group) {
			// The same Powerup ▾ dropdown as the form toolbar. Its container
			// (.custom-actions) is hidden on narrow and medium screens, so every item
			// keeps a plain twin in the page's ... menu for those.
			view._pp_group = view.page.add_custom_button_group(__('Powerup'));
			view._pp_copy_image = this.make_powerup_item(view, __('Copy as Image'), () =>
				me.copy({
					doctype: view.frm.doc.doctype,
					name: view.frm.doc.name,
					print_format: view.selected_format(),
					letterhead: view.with_letterhead() ? view.get_letterhead() : '',
					no_letterhead: view.with_letterhead() ? 0 : 1,
					lang: view.lang_code,
					// The sidebar's Compact Item Print etc., as the PDF button sends them.
					settings: JSON.stringify(view.additional_settings || {}),
				})
			);
			view._pp_copy_message = this.make_powerup_item(view, __('Copy as Message'), () => {
				if (view._pp_copy_message_click) view._pp_copy_message_click();
			});
		}

		// One PrintView serves every document, so decide per document.
		view._pp_copy_image_allowed = false;
		view._pp_copy_message_click = null;
		this.update_print_view_powerup(view);

		if (this.DOCTYPES.includes(view.frm.doctype)) {
			CecypoPowerPack.Settings.isEnabled('enable_copy_as_image', (enabled) => {
				view._pp_copy_image_allowed = !!enabled && this.DOCTYPES.includes(view.frm.doctype);
				this.update_print_view_powerup(view);
			});
		}
		this.setup_copy_message(view);
	},

	// One dropdown item plus its narrow-screen twin, as one toggleable jQuery set.
	make_powerup_item(view, label, click) {
		const $item = view.page.add_custom_menu_item(view._pp_group, label, click, true);
		const $menu_item = view.page.add_menu_item(label, click, true);
		return $item.closest('li').add($menu_item.closest('li'));
	},

	update_print_view_powerup(view) {
		if (!view._pp_group) return;
		// docstatus 2: the form hides its button for a cancelled document, and the server
		// refuses to print one ("Not allowed to print cancelled documents").
		const image =
			!!view._pp_copy_image_allowed && !view.is_raw_printing() && view.frm.doc.docstatus !== 2;
		const message = !!view._pp_copy_message_click;
		view._pp_copy_image.toggle(image);
		view._pp_copy_message.toggle(message);
		view._pp_group.closest('.custom-btn-group').toggle(image || message);
	},

	// Copy as Message is a Client Script the site owns (seeded by copy_as_message.py,
	// then edited freely - its bank details live in the source). The print page has no
	// real form for it to hook, so the same source the desk form runs is fetched and run
	// here against a stub frm. Shown exactly when the script would show it on the form:
	// the script's own refresh guards (cancelled document etc.) decide.
	setup_copy_message(view) {
		const me = this;
		const doc = view.frm.doc;
		this.message_script(doc.doctype).then((script) => {
			// The view serves every document; a stale fetch must not touch a newer one.
			if (view.frm.doc !== doc) return;
			view._pp_copy_message_click = script ? me.collect_copy_message(script, doc) : null;
			me.update_print_view_powerup(view);
		});
	},

	message_script(doctype) {
		this._message_scripts = this._message_scripts || {};
		if (!(doctype in this._message_scripts)) {
			this._message_scripts[doctype] = frappe
				.xcall('cecypo_powerpack.copy_as_message.get_copy_message_script', { doctype })
				.then(
					(script) => script || null,
					() => null
				);
		}
		return this._message_scripts[doctype];
	},

	// Runs the script source - the same code the desk form runs - intercepting only
	// frappe.ui.form.on (to catch its handlers) and handing its refresh a stub frm.
	// Everything else it touches is the real desk API. Returns the action it registered
	// for the Copy as Message button, or null.
	collect_copy_message(script, doc) {
		const handlers = [];
		const frappe_shim = Object.assign(Object.create(frappe), {
			ui: Object.assign(Object.create(frappe.ui), {
				form: Object.assign(Object.create(frappe.ui.form), {
					on: (doctype, events) => {
						if (doctype === doc.doctype) handlers.push(events);
					},
				}),
			}),
		});
		let click = null;
		const frm = {
			doc,
			doctype: doc.doctype,
			docname: doc.name,
			is_new: () => false,
			is_dirty: () => false,
			add_custom_button(label, action) {
				const text = (label || '').trim();
				if (text === __('Copy as Message') || text === 'Copy as Message') click = action;
				return $();
			},
			remove_custom_button() {},
		};
		try {
			new Function('frappe', 'cur_frm', script)(frappe_shim, frm);
			for (const events of handlers) events.refresh && events.refresh(frm);
		} catch (e) {
			console.warn('Copy as Message script failed in the print preview:', e);
			return null;
		}
		return click;
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
						() => {
							// The image is rendered from the saved document.
							if (frm.is_dirty()) {
								frappe.msgprint(__('Save the document first: the image shows the saved version.'));
								return;
							}
							me.copy({ doctype: frm.doc.doctype, name: frm.doc.name });
						},
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
