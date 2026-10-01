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

	popup: null, // { $el, lines, index, cdt, cdn, anchor, frm, can_pick, set_list_price }
	loading: null, // row name being fetched: the click and the focus that follows both ask
	skip_focus: null,
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
		// Only the form's own items grid: the Taxes grid has a `rate` column too.
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
			has_pricing_rule: row.pricing_rules ? 1 : 0,
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

	// Whether a pick may change this row's rate at all: a draft, and write permission at the
	// rate's permlevel - without it frappe resets the rate on save, so a pick would not stick.
	// A rate that is only read-only (fixed price) still allows choosing among the lists.
	can_pick(frm) {
		const df = frm.fields_dict.items.grid.get_docfield('rate');
		return (
			frm.doc.docstatus === 0 &&
			!!df &&
			frappe.perm.has_perm(frm.doctype, df.permlevel || 0, 'write', frm.doc)
		);
	},

	// Custom Price: only where the user could type a rate. Decided from the document, not the
	// grid's DOM, which may be mid-redraw.
	rate_editable(frm) {
		const df = frm.fields_dict.items.grid.get_docfield('rate');
		return this.can_pick(frm) && !df.read_only;
	},

	async open(el, editable_input) {
		const ctx = this.row_for(el);
		if (!ctx) return;
		const { frm, row } = ctx;
		if ((this.popup && this.popup.cdn === row.name) || this.loading === row.name) return;
		this.close();

		// If the user types while prices load, the dropdown must not open over their figure.
		const typed_before = editable_input ? editable_input.value : null;
		this.loading = row.name;
		let data;
		try {
			data = await this.fetch(this.args(frm, row));
		} catch (e) {
			return;
		} finally {
			this.loading = null;
		}
		if (editable_input && (document.activeElement !== editable_input || editable_input.value !== typed_before)) {
			return;
		}

		const can_pick = this.can_pick(frm);
		const lines = data.options.map((o) => ({ ...o, label: o.price_list }));
		if (this.rate_editable(frm)) {
			lines.push({ label: __('Custom Price'), rate: flt(row.rate), custom: true });
		}
		if (!lines.length) return;
		this.render(frm, row, lines, editable_input || el, can_pick, data.set_list_price);
	},

	render(frm, row, lines, anchor, can_pick, set_list_price) {
		const $el = $('<div class="pp-rate-picker" role="listbox"></div>').appendTo(document.body);
		$el.toggleClass('pp-rate-picker-readonly', !can_pick);
		const rate_precision = precision('rate', row);
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
				// In the user's number format: flt() reads it back with the same grouping,
				// where a raw 600.5 would read as 6005 under #.###,##.
				$line.find('input')
					.val(format_number(line.rate, null, rate_precision))
					.on('focus', () => {
						if (this.popup) {
							this.popup.index = i;
							this.highlight();
						}
					});
			} else {
				$line.find('.pp-rate-picker-value').html(format_currency(line.rate, frm.doc.currency));
				if (line.below_floor) {
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

		this.popup = {
			$el, lines, index: 0, cdt: row.doctype, cdn: row.name, anchor, frm, can_pick, set_list_price,
		};
		this.position();
		this.highlight();
	},

	// Pinned under (or above) the anchor; kept there while the page or grid scrolls.
	position() {
		const p = this.popup;
		if (!p) return;
		if (!document.body.contains(p.anchor)) return this.close();
		const r = p.anchor.getBoundingClientRect();
		if (r.bottom < 0 || r.top > window.innerHeight) return this.close();
		const height = p.$el.outerHeight();
		const below = r.bottom + height + 4 <= window.innerHeight || r.top < height + 4;
		p.$el.css({
			left: Math.max(8, Math.min(r.left, window.innerWidth - this.WIDTH - 8)),
			top: below ? r.bottom + 4 : 'auto',
			bottom: below ? 'auto' : window.innerHeight - r.top + 4,
		});
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
		const $line = p.$el.find('.pp-rate-picker-line').eq(p.index);
		$line[0].scrollIntoView({ block: 'nearest' });
		const input = p.$el.find('.pp-rate-picker-custom')[0];
		if (p.lines[p.index].custom) {
			input.focus();
			// After focus settles, or the grid's focus handling drops the selection and
			// typing prepends to the seeded rate instead of replacing it.
			setTimeout(() => input.select(), 0);
		} else if (input && document.activeElement === input) {
			this.refocus(p.anchor);
		}
	},

	async pick(i) {
		const { lines, cdt, cdn, frm, anchor, can_pick, set_list_price } = this.popup;
		const line = lines[i];
		let rate = line.rate;
		if (line.custom) {
			const typed = this.popup.$el.find('.pp-rate-picker-custom').val().trim();
			if (!typed || isNaN(flt(typed))) {
				this.close();
				this.refocus(anchor);
				return;
			}
			rate = flt(typed);
		}
		if (!can_pick) return; // the lines are for reference only
		this.close();

		const row = locals[cdt][cdn];
		if (!line.custom && set_list_price) {
			// A list price replaces the row's price outright: list price = picked price, no
			// margin, no discount. ERPNext's rate handler finds nothing to derive.
			Object.assign(row, {
				price_list_rate: rate,
				rate_with_margin: rate,
				margin_type: '',
				margin_rate_or_amount: 0,
				discount_percentage: 0,
				discount_amount: 0,
			});
		}
		if (flt(row.rate) === rate) {
			// No change event for an unchanged rate: run the handler ourselves.
			await frm.script_manager.trigger('rate', cdt, cdn);
			frm.dirty();
			frm.refresh_field('items');
		} else {
			// Without set_list_price (Stock Settings would write the list price back to the
			// document's own list on save) a list pick is just a rate, as if typed.
			await frappe.model.set_value(cdt, cdn, 'rate', rate);
		}
		this.refocus(anchor);
	},

	// Put focus back in the row's rate field without reopening the dropdown. Opened from a
	// cell, the anchor is not focusable, so find the row's input.
	refocus(anchor) {
		const input =
			anchor && anchor.matches && anchor.matches('input') && document.body.contains(anchor)
				? anchor
				: $(anchor).closest('.grid-row').find('input[data-fieldname="rate"]:not(:disabled)')[0];
		if (!input || document.activeElement === input) return;
		this.skip_focus = input;
		input.focus();
		// If focus did not land (input hidden mid-redraw), do not skip a later real focus.
		setTimeout(() => {
			if (this.skip_focus === input) this.skip_focus = null;
		}, 0);
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
			// Enter in the Custom Price box means that box, wherever the highlight is.
			const custom = this.popup.lines.findIndex((l) => l.custom);
			this.pick(in_custom && custom >= 0 ? custom : this.popup.index);
		} else if (e.key === 'Escape') {
			swallow();
			const anchor = this.popup.anchor;
			this.close();
			this.refocus(anchor);
		} else if (e.key === 'Tab') {
			this.close();
		}
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
		if (!cell || !this.row_for(cell) || (this.popup && this.popup.anchor === cell)) return;
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
		// Any edit of the field itself - typing, Backspace, paste - is the user's own price.
		$(document).on('input', this.RATE_INPUT, () => this.close());
		$(document).on('focusout', `${this.RATE_INPUT}, .pp-rate-picker-custom`, () => {
			setTimeout(() => {
				const p = this.popup;
				if (p && !p.$el[0].contains(document.activeElement) && document.activeElement !== p.anchor) {
					this.close();
				}
			}, 150);
		});
		// Follow the cell rather than close: focusing a cell scrolls it into view, and a
		// phone's keyboard resizes the window.
		window.addEventListener(
			'scroll',
			(e) => {
				if (this.popup && !this.popup.$el[0].contains(e.target)) this.position();
			},
			true
		);
		window.addEventListener('resize', () => this.position());
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
