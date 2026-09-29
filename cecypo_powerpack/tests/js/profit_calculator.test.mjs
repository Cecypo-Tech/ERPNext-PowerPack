// Unit tests for public/js/profit_calculator.js. Run: node --test <this file>
// (test_profit_calculator_js.py runs it under `bench run-tests`.)
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(
	new URL("../../public/js/profit_calculator.js", import.meta.url),
	"utf8",
);
const sandbox = {
	frappe: {
		provide(ns) {
			let o = sandbox;
			for (const part of ns.split(".")) o = o[part] = o[part] || {};
		},
	},
};
vm.createContext(sandbox);
vm.runInContext(source, sandbox);
const calc = sandbox.cecypo_powerpack.profit_calculator;

const close = (actual, expected, places = 2) =>
	assert.ok(Math.abs(actual - expected) < 10 ** -places, `${actual} ≉ ${expected}`);

// POS-01217 / F049 on dev: 610 incl. 16% VAT, net 525.86, cost 400.
const VAT_INCLUSIVE = [{ included_in_print_rate: 1, rate: 16 }];
const VAT_EXCLUSIVE = [{ included_in_print_rate: 0, rate: 16 }];

test("margin on a tax-inclusive row is profit over the net price", () => {
	const doc = { taxes: VAT_INCLUSIVE, conversion_rate: 1 };
	const row = { rate: 610, net_rate: 525.86, base_net_rate: 525.86, conversion_factor: 1 };
	const r = calc.row_profit(row, doc, 400);
	close(r.margin, 23.93);
	close(r.markup, 31.47);
	close(r.profit, 125.86);
});

test("the same sale shows the same margin whatever the tax template", () => {
	const row = { rate: 525.86, net_rate: 525.86, base_net_rate: 525.86, conversion_factor: 1 };
	const excl = calc.row_profit(row, { taxes: VAT_EXCLUSIVE, conversion_rate: 1 }, 400);
	const incl = calc.row_profit(
		{ ...row, rate: 610 },
		{ taxes: VAT_INCLUSIVE, conversion_rate: 1 },
		400,
	);
	close(excl.margin, incl.margin);
});

test("cost is per stock UOM: a Box of 12 costs 12 units", () => {
	const doc = { taxes: [], conversion_rate: 1 };
	const row = { rate: 1200, net_rate: 1200, base_net_rate: 1200, conversion_factor: 12 };
	const r = calc.row_profit(row, doc, 90);
	close(r.cost, 1080);
	close(r.margin, 10);
});

test("foreign-currency rows compare in company currency", () => {
	const doc = { taxes: [], conversion_rate: 130 };
	// base_net_rate not yet computed: net_rate × conversion_rate
	const row = { rate: 10, net_rate: 10, conversion_factor: 1 };
	const r = calc.row_profit(row, doc, 1000);
	close(r.net, 1300);
	close(r.margin, 23.08);
});

test("a document discount is in the row margin (net_rate, not rate)", () => {
	const doc = { taxes: [], conversion_rate: 1, discount_amount: 10 };
	const row = { rate: 100, net_rate: 90, base_net_rate: 90, conversion_factor: 1 };
	close(calc.row_profit(row, doc, 60).margin, 33.33);
});

test("a fresh inclusive row without net_rate strips tax from rate", () => {
	const doc = {
		taxes: VAT_INCLUSIVE, conversion_rate: 1, net_total: 100, total_taxes_and_charges: 16,
	};
	close(calc.row_net_rate_base({ rate: 116, conversion_factor: 1 }, doc), 100);
});

test("no cost gives no margin rather than 100%", () => {
	const r = calc.row_profit({ base_net_rate: 50 }, { taxes: [] }, null);
	assert.equal(r.margin, null);
	assert.equal(r.cost, null);
});

test("zero price gives no margin rather than a division by zero", () => {
	const r = calc.row_profit({ base_net_rate: 0, rate: 0 }, { taxes: [] }, 10);
	assert.equal(r.margin, null);
	close(r.profit, -10);
});

test("document profit leaves uncosted rows out of both sides", () => {
	const doc = {
		taxes: [],
		conversion_rate: 1,
		items: [
			{ name: "a", item_code: "A", qty: 2, conversion_factor: 1, base_net_amount: 200 },
			{ name: "b", item_code: "BOX", qty: 1, conversion_factor: 12, base_net_amount: 1200 },
			{ name: "c", item_code: "SVC", qty: 1, conversion_factor: 1, base_net_amount: 500 },
			{ name: "d", item_code: "", qty: 1 },
			{ name: "e", item_code: "SVC", qty: 1, conversion_factor: 1, base_net_amount: 100 },
		],
	};
	const r = calc.doc_profit(doc, { a: 60, b: 90, c: null, e: null });
	close(r.revenue, 1400);
	close(r.cost, 120 + 1080);
	close(r.profit, 200);
	close(r.margin, 14.29);
	close(r.markup, 16.67);
	assert.equal(r.costed, 2);
	assert.equal(r.total, 4);
	// listed once however many rows it is on
	assert.deepEqual([...r.uncosted], ["SVC"]);
});

test("document profit with nothing costed has no margin", () => {
	const doc = { items: [{ name: "a", item_code: "A", qty: 1, base_net_amount: 10 }] };
	const r = calc.doc_profit(doc, {});
	assert.equal(r.margin, null);
	assert.equal(r.markup, null);
	assert.equal(r.costed, 0);
});

test("reference values are restated in the row's UOM, currency and tax basis", () => {
	const doc = { taxes: VAT_INCLUSIVE, conversion_rate: 2 };
	const row = { rate: 116, net_rate: 100, conversion_factor: 6 };
	// 10 per stock unit → 60 per row UOM → 30 in doc currency → 34.8 incl. 16%
	close(calc.to_row_display(10, row, doc, true), 34.8);
	close(calc.to_row_display(10, row, doc, false), 30);
	assert.equal(calc.to_row_display(null, row, doc, true), null);
});

test("exclusive documents never add tax to reference values", () => {
	const doc = { taxes: VAT_EXCLUSIVE, conversion_rate: 1 };
	close(calc.to_row_display(10, { rate: 10, net_rate: 10 }, doc, true), 10);
});

test("bands follow settings and keep a deliberate zero", () => {
	assert.equal(calc.band(-1, {}).cls, "profit-loss");
	assert.equal(calc.band(5, {}).cls, "profit-low");
	assert.equal(calc.band(15, {}).cls, "profit-medium");
	assert.equal(calc.band(25, {}).cls, "profit-good");
	assert.equal(calc.band(30, {}).cls, "profit-excellent");
	const s = { sales_margin_low_below: 0, sales_margin_medium_below: 5, sales_margin_good_below: 8 };
	assert.equal(calc.band(0, s).cls, "profit-medium");
	assert.equal(calc.band(7, s).cls, "profit-good");
	assert.equal(calc.band(8, s).cls, "profit-excellent");
});

test("helpers used by bulk_selection.js keep their contract", () => {
	const frm = { doc: { taxes: VAT_INCLUSIVE, net_total: 100, total_taxes_and_charges: 16 } };
	assert.equal(calc.is_tax_inclusive(frm), true);
	close(calc.calculate_doc_tax_rate(frm), 0.16);
	assert.equal(calc.is_tax_inclusive({ doc: {} }), false);
});
