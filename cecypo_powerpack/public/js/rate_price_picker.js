// Copyright (c) 2026, Cecypo.Tech and contributors
// For license information, please see license.txt

// Rate Price Picker: focusing an item's Rate on a Quotation, Sales Order or Sales Invoice
// opens a dropdown of the item's price on each selling price list in the document's
// currency, plus an editable Custom Price when the rate can be edited. Prices come from
// cecypo_powerpack/rate_price_picker.py.
//
// Frappe's grid has its own keyboard navigation (Up/Down change rows, Enter acts on the
// row), so the dropdown's keys are handled in the capture phase and swallowed while it is
// open. A read-only Rate renders a disabled input, which swallows clicks, so the cell is
// watched in the capture phase too.

frappe.provide('cecypo_powerpack.rate_price_picker');

cecypo_powerpack.rate_price_picker = {
	DOCTYPES: ['Quotation', 'Sales Order', 'Sales Invoice'],
	RATE_INPUT: '.grid-row input[data-fieldname="rate"]',
	RATE_CELL: '.grid-row .grid-static-col[data-fieldname="rate"]',
	WIDTH: 260,

	popup: null, // { $el, options, index, cdt, cdn, anchor }
	loading: null, // row name being fetched: the click and the focus that follows both ask
	cache: new Map(),

	enabled_for(frm) {
		return !!(frm && this.DOCTYPES.includes(frm.doctype) && frm.__pp_rate_price_picker);
	},

	row_for(el) {
		const frm = window.cur_frm;
		if (!this.enabled_for(frm)) return null;
		const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
		const $row = $(el).closest('.grid-row');
		const cdn = $row.attr('data-name');
		if (!grid || !cdn || !$row.closest(grid.wrapper).length) return null;
		const row = locals[grid.doctype] && locals[grid.doctype][cdn];
		return row && row.item_code ? { frm, row } : null;
	},

	args(frm, row) {
		const doc = frm.doc;
		const rate = flt(row.rate);
		return {
			doctype: doc.doctype,
			item_code: row.item_code,
			uom: row.uom,
			stock_uom: row.stock_uom,
			conversion_factor: row.conversion_factor || 1,
			qty: row.qty || 1,
			currency: doc.currency,
			customer: doc.doctype === 'Quotation'
				? (doc.quotation_to === 'Customer' ? doc.party_name : null)
				: doc.customer,
			company: doc.company,
			warehouse: row.warehouse,
			transaction_date: doc.posting_date || doc.transaction_date,
			conversion_rate: doc.conversion_rate || 1,
			// The row's net / gross: inclusive taxes and the document discount, so the
			// floor flag is judged like the check on save. 1 until the row has a rate.
			net_factor: rate ? flt(row.net_rate) / rate || 1 : 1,
		};
	},

	async fetch(args) {
		const key = JSON.stringify({ ...args, net_factor: flt(args.net_factor, 4) });
		if (!this.cache.has(key)) {
			this.cache.set(
				key,
				frappe
					.xcall('cecypo_powerpack.rate_price_picker.get_rate_options', args)
					.catch((e) => {
						this.cache.delete(key);
						throw e;
					})
			);
		}
		return this.cache.get(key);
	},

	async open(el, editable_input) {
		const ctx = this.row_for(el);
		if (!ctx) return;
		const { frm, row } = ctx;
		if ((this.popup && this.popup.cdn === row.name) || this.loading === row.name) return;
		this.close();

		this.loading = row.name;
		let options;
		try {
			options = await this.fetch(this.args(frm, row));
		} catch (e) {
			return;
		} finally {
			this.loading = null;
		}
		// The rate field may have lost focus while prices loaded.
		if (editable_input && document.activeElement !== editable_input) return;

		const lines = options.map((o) => ({ ...o, label: o.price_list }));
		// Decided from the document, not the grid's DOM, which may be mid-redraw. Custom
		// Price has its own input in the dropdown, so it needs no grid input either.
		if (this.rate_editable(frm, row)) {
			lines.push({ label: __('Custom Price'), rate: flt(row.rate), custom: true });
		}
		if (!lines.length) return;
		this.render(frm, row, lines, editable_input || el);
	},

	rate_editable(frm, row) {
		const df = frm.fields_dict.items.grid.get_docfield('rate');
		return (
			frm.doc.docstatus === 0 &&
			!!df &&
			!df.read_only &&
			frappe.perm.has_perm(frm.doctype, df.permlevel || 0, 'write', frm.doc)
		);
	},

	render(frm, row, lines, anchor) {
		const $el = $('<div class="pp-rate-picker" role="listbox"></div>').appendTo(document.body);
		lines.forEach((line, i) => {
			const $line = $(`<div class="pp-rate-picker-line" role="option">
					<span class="pp-rate-picker-label"></span>
					<span class="pp-rate-picker-value"></span>
				</div>`).appendTo($el);
			$line.find('.pp-rate-picker-label').text(line.label);
			if (line.custom) {
				$line.find('.pp-rate-picker-value').html(
					`<input class="pp-rate-picker-custom" type="text" inputmode="decimal" autocomplete="off">`
				);
				$line.find('input').val(line.rate);
			} else {
				$line.find('.pp-rate-picker-value').html(format_currency(line.rate, frm.doc.currency));
				if (line.below_floor) {
					$line.addClass('pp-below-floor');
					$line.find('.pp-rate-picker-label').append(
						` <span class="pp-rate-picker-tag">${__('below min')}</span>`
					);
				}
			}
			$line.on('mousedown', (e) => {
				if ($(e.target).is('input')) return;
				e.preventDefault();
				this.pick(i);
			});
		});

		const r = anchor.getBoundingClientRect();
		const height = lines.length * 38 + 12;
		$el.css({
			left: Math.max(8, Math.min(r.left, window.innerWidth - this.WIDTH - 8)),
			...(r.bottom + height <= window.innerHeight
				? { top: r.bottom + 4 }
				: { bottom: window.innerHeight - r.top + 4 }),
		});
		this.popup = { $el, lines, index: 0, cdt: row.doctype, cdn: row.name, anchor, frm };
		this.highlight();
	},

	close() {
		if (this.popup) this.popup.$el.remove();
		this.popup = null;
	},

	highlight() {
		this.popup.$el.find('.pp-rate-picker-line').removeClass('active').eq(this.popup.index).addClass('active');
	},

	move(step) {
		const p = this.popup;
		p.index = (p.index + step + p.lines.length) % p.lines.length;
		this.highlight();
		const input = p.$el.find('.pp-rate-picker-custom')[0];
		if (p.lines[p.index].custom) {
			input.focus();
			// After focus settles, or the grid's focus handling drops the selection and
			// typing prepends to the seeded rate instead of replacing it.
			setTimeout(() => input.select(), 0);
		} else if (input && document.activeElement === input) {
			$(p.anchor).trigger('focus');
		}
	},

	async pick(i) {
		const { lines, cdt, cdn, frm, anchor } = this.popup;
		const line = lines[i];
		const rate = line.custom ? flt(this.popup.$el.find('.pp-rate-picker-custom').val()) : line.rate;
		this.close();
		if (frm.doc.docstatus !== 0) return;

		if (!line.custom) {
			// A list price replaces the row's price outright: list price = picked price, no
			// margin, no discount. ERPNext's own rate handler then derives the rest.
			const row = locals[cdt][cdn];
			Object.assign(row, {
				price_list_rate: rate,
				margin_type: '',
				margin_rate_or_amount: 0,
				discount_percentage: 0,
				discount_amount: 0,
			});
			if (flt(row.rate) === rate) {
				// No change event for an unchanged rate: run the handler ourselves.
				await frm.script_manager.trigger('rate', cdt, cdn);
				frm.dirty();
				frm.refresh_field('items');
				return;
			}
		}
		await frappe.model.set_value(cdt, cdn, 'rate', rate);
		this.refocus(anchor);
	},

	on_keydown(e) {
		const t = e.target;
		if (!t.matches) return;
		const in_rate = t.matches(this.RATE_INPUT);
		const in_custom = t.classList.contains('pp-rate-picker-custom');
		if (!this.popup) {
			if (in_rate && e.key === 'ArrowDown' && e.altKey && this.row_for(t)) {
				e.preventDefault();
				e.stopImmediatePropagation();
				this.open(t, t);
			}
			return;
		}
		// Opened from a read-only cell, nothing has focus: keys arrive on the body.
		const unfocused = t === document.body || t === this.popup.anchor;
		if (!in_rate && !in_custom && !unfocused) return;
		const swallow = () => {
			e.preventDefault();
			e.stopImmediatePropagation();
		};
		if (e.key === 'ArrowDown') {
			swallow();
			this.move(1);
		} else if (e.key === 'ArrowUp') {
			swallow();
			this.move(-1);
		} else if (e.key === 'Enter') {
			swallow();
			this.pick(this.popup.index);
		} else if (e.key === 'Escape') {
			swallow();
			const anchor = this.popup.anchor;
			this.close();
			this.refocus(anchor);
		} else if (e.key === 'Tab') {
			this.close();
		} else if (in_rate && e.key.length === 1) {
			this.close(); // typing in the field is your own price
		}
	},

	// Put focus back in the row's rate field without reopening the dropdown. Opened from a
	// cell, the anchor is not focusable, so find the row's input.
	refocus(anchor) {
		const input =
			anchor && anchor.matches && anchor.matches('input')
				? anchor
				: $(anchor).closest('.grid-row').find('input[data-fieldname="rate"]:not(:disabled)')[0];
		if (!input || document.activeElement === input) return;
		this.skip_focus = input;
		input.focus();
	},

	on_mousedown(e) {
		const t = e.target;
		if (this.popup && !this.popup.$el[0].contains(t) && t !== this.popup.anchor) this.close();
		if (!t.closest) return;
		if (t.matches(this.RATE_INPUT) && !t.disabled) {
			// Its focusin opens the dropdown - except when it already has focus (a pick
			// leaves it focused), so reopen here.
			if (document.activeElement === t && !this.popup) this.open(t, t);
			return;
		}
		const cell = t.closest(this.RATE_CELL);
		if (!cell || (this.popup && this.popup.anchor === cell)) return;
		// Let the grid make the row editable first: clicking a row that is not yet in edit
		// mode draws its inputs after this event. Never open from here when the rate is
		// editable - only focus it, and its focusin opens - or a late open could land after
		// the user has started typing.
		setTimeout(() => {
			const input = cell.querySelector('input[data-fieldname="rate"]');
			if (input && !input.disabled && $(input).is(':visible')) {
				if (document.activeElement !== input) input.focus();
			} else {
				this.open(cell, null); // read-only rate: price lists only
			}
		}, 80);
	},

	setup() {
		document.addEventListener('keydown', (e) => this.on_keydown(e), true);
		document.addEventListener('mousedown', (e) => this.on_mousedown(e), true);
		$(document).on('focusin', this.RATE_INPUT, (e) => {
			if (this.skip_focus === e.target) {
				this.skip_focus = null;
				return;
			}
			if (!e.target.disabled) this.open(e.target, e.target);
		});
		$(document).on('focusout', `${this.RATE_INPUT}, .pp-rate-picker-custom`, () => {
			setTimeout(() => {
				const p = this.popup;
				if (p && !p.$el[0].contains(document.activeElement) && document.activeElement !== p.anchor) {
					this.close();
				}
			}, 150);
		});
		// A fixed popup would drift away from its cell.
		window.addEventListener('scroll', () => this.close(), true);
		window.addEventListener('resize', () => this.close());
		$(document).on('page-change', () => {
			this.close();
			this.cache.clear();
		});

		for (const doctype of this.DOCTYPES) {
			frappe.ui.form.on(doctype, {
				refresh: (frm) => {
					CecypoPowerPack.Settings.isEnabled('enable_rate_price_picker', (enabled) => {
						frm.__pp_rate_price_picker = !!enabled;
					});
				},
			});
		}
	},
};

cecypo_powerpack.rate_price_picker.setup();
