// cecypo_powerpack/cecypo_powerpack/page/powerpack_permissions/powerpack_permissions.js
// Copyright (c) 2026, Cecypo.Tech and contributors
// For license information, please see license.txt

/**
 * PowerPack Permission Manager.
 *
 * Every role permission rule on the site in one virtualized table. Nothing is written
 * until Commit, which sends the whole change set to
 * cecypo_powerpack.permission_manager.commit_changes in one round trip.
 *
 * This file is loaded by frappe's page loader, not by the app bundle, so it is a
 * classic script: top-level names here ARE global. Keep everything on the class.
 */

frappe.pages["powerpack-permissions"].on_page_load = (wrapper) => {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("PowerPack Permission Manager"),
		single_column: true,
	});
	frappe.breadcrumbs.add("Setup");
	wrapper.permission_manager = new frappe.PowerPackPermissionManager(wrapper, page);
};

frappe.PowerPackPermissionManager = class PowerPackPermissionManager {
	constructor(wrapper, page) {
		this.wrapper = wrapper;
		this.page = page;
		this.$body = $('<div class="pp-perm"></div>').appendTo(this.page.main);
		this.load();
	}

	load() {
		this.$body.html(`<div class="pp-perm-empty">${__("Loading permission rules…")}</div>`);
	}
};
