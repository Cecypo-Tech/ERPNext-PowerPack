/**
 * Cecypo PowerPack - Global Client Scripts
 * 
 * Include in hooks.py:
 * app_include_js = "/assets/cecypo_powerpack/js/cecypo_powerpack.js"
 */

window.CecypoPowerPack = window.CecypoPowerPack || {};

$(document).ready(function () {
    console.log("Cecypo PowerPack loaded");
});

/**
 * Show system health status
 */
CecypoPowerPack.checkHealth = function () {
    frappe.call({
        method: "cecypo_powerpack.api.get_system_health",
        callback: function (r) {
            if (r.message) {
                frappe.msgprint({
                    title: __("System Health"),
                    indicator: r.message.status === "healthy" ? "green" : "red",
                    message: `Status: ${r.message.status}<br>Time: ${r.message.timestamp}`
                });
            }
        }
    });
};
