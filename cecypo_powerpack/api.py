# Copyright (c) 2024, Cecypo.Tech and contributors
# For license information, please see license.txt

"""
API Module for Cecypo PowerPack

Whitelisted methods accessible via:
- frappe.call() from JavaScript
- REST API: /api/method/cecypo_powerpack.api.<method_name>
"""

import frappe
from frappe import _


@frappe.whitelist()
def get_system_health() -> dict:
    """
    Get system health status and statistics.

    Returns:
        dict: System health information
    """
    return {
        "status": "healthy",
        "timestamp": frappe.utils.now(),
        "user": frappe.session.user
    }


@frappe.whitelist()
def debug_powerpack_settings() -> dict:
    """
    Debug endpoint to check PowerPack Settings.

    Returns:
        dict: Debug information
    """
    from cecypo_powerpack.utils import get_powerpack_settings, is_feature_enabled

    try:
        settings = get_powerpack_settings()
        return {
            "success": True,
            "settings": settings,
            "enable_quotation_tweaks_value": settings.get('enable_quotation_tweaks'),
            "enable_quotation_tweaks_type": str(type(settings.get('enable_quotation_tweaks'))),
            "is_quotation_tweaks_enabled": is_feature_enabled('enable_quotation_tweaks'),
            "is_pos_powerup_enabled": is_feature_enabled('enable_pos_powerup')
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "traceback": frappe.get_traceback()
        }


@frappe.whitelist()
def run_custom_report(report_name: str, filters: dict = None) -> list:
    """
    Run a custom report with given filters.

    Args:
        report_name: Name of the report
        filters: Report filters

    Returns:
        list: Report data
    """
    if not frappe.has_permission("Report", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    # TODO: Implement custom report logic
    return []


@frappe.whitelist()
def get_item_info_for_quotation(item_code: str, customer: str = None, warehouse: str = None) -> dict:
    """
    Get comprehensive item information for quotation tweaks.

    Args:
        item_code: Item code
        customer: Customer name (optional)
        warehouse: Warehouse name (optional)

    Returns:
        dict: Item information including stock, rates, and sales history
    """
    if not item_code:
        return {}

    result = {
        "item_code": item_code,
        "actual_qty": None,
        "reserved_qty": None,
        "available_qty": None,
        "valuation_rate": None,
        "last_purchase_rate": None,
        "last_purchase_date": None,
        "last_sale_to_customer_rate": None,
        "last_sale_to_customer_date": None,
        "last_sale_rate": None,
        "last_sale_date": None
    }

    # Get current stock and valuation rate with detailed breakdown
    if warehouse:
        stock_data = frappe.db.sql("""
            SELECT actual_qty, reserved_qty, projected_qty, valuation_rate
            FROM `tabBin`
            WHERE item_code = %s AND warehouse = %s
            LIMIT 1
        """, (item_code, warehouse), as_dict=True)

        if stock_data:
            result["actual_qty"] = stock_data[0].get("actual_qty")
            result["reserved_qty"] = stock_data[0].get("reserved_qty")
            result["available_qty"] = stock_data[0].get("projected_qty")
            result["valuation_rate"] = stock_data[0].get("valuation_rate")
    else:
        # Get total stock across all warehouses
        total_stock = frappe.db.sql("""
            SELECT
                SUM(actual_qty) as total_actual_qty,
                SUM(reserved_qty) as total_reserved_qty,
                SUM(projected_qty) as total_projected_qty,
                AVG(valuation_rate) as avg_rate
            FROM `tabBin`
            WHERE item_code = %s
        """, (item_code,), as_dict=True)

        if total_stock:
            result["actual_qty"] = total_stock[0].get("total_actual_qty")
            result["reserved_qty"] = total_stock[0].get("total_reserved_qty")
            result["available_qty"] = total_stock[0].get("total_projected_qty")
            result["valuation_rate"] = total_stock[0].get("avg_rate")

    # Get last purchase rate and date
    last_purchase = frappe.db.sql("""
        SELECT pri.rate, pi.posting_date
        FROM `tabPurchase Invoice Item` pri
        INNER JOIN `tabPurchase Invoice` pi ON pri.parent = pi.name
        WHERE pri.item_code = %s AND pi.docstatus = 1
        ORDER BY pi.posting_date DESC, pi.creation DESC
        LIMIT 1
    """, (item_code,), as_dict=True)

    if last_purchase:
        result["last_purchase_rate"] = last_purchase[0].get("rate")
        result["last_purchase_date"] = last_purchase[0].get("posting_date")

    # Get last sale to specific customer
    if customer:
        last_sale_to_customer = frappe.db.sql("""
            SELECT sii.rate, si.posting_date
            FROM `tabSales Invoice Item` sii
            INNER JOIN `tabSales Invoice` si ON sii.parent = si.name
            WHERE sii.item_code = %s AND si.customer = %s AND si.docstatus = 1
            ORDER BY si.posting_date DESC, si.creation DESC
            LIMIT 1
        """, (item_code, customer), as_dict=True)

        if last_sale_to_customer:
            result["last_sale_to_customer_rate"] = last_sale_to_customer[0].get("rate")
            result["last_sale_to_customer_date"] = last_sale_to_customer[0].get("posting_date")

    # Get last sale to anyone
    last_sale = frappe.db.sql("""
        SELECT sii.rate, si.posting_date, si.customer
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si ON sii.parent = si.name
        WHERE sii.item_code = %s AND si.docstatus = 1
        ORDER BY si.posting_date DESC, si.creation DESC
        LIMIT 1
    """, (item_code,), as_dict=True)

    if last_sale:
        result["last_sale_rate"] = last_sale[0].get("rate")
        result["last_sale_date"] = last_sale[0].get("posting_date")

    return result
