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


@frappe.whitelist()
def fetch_item_prices(item_codes_str: str, buying_price_list: str, selling_price_list: str) -> list:
    """
    Fetch item prices for bulk price editor.

    Args:
        item_codes_str: Pipe-delimited string of item codes (e.g., "ITEM001|||ITEM002|||ITEM003")
        buying_price_list: Name of the buying price list
        selling_price_list: Name of the selling price list

    Returns:
        list: List of dictionaries containing item code, name, cost price, and sell price
    """
    if not item_codes_str or not buying_price_list or not selling_price_list:
        return []

    # Split item codes
    item_codes = item_codes_str.split('|||')

    results = []
    for item_code in item_codes:
        if not item_code:
            continue

        # Get item details
        item = frappe.get_cached_value('Item', item_code, ['item_code', 'item_name'], as_dict=True)
        if not item:
            continue

        # Get buying price (cost)
        cost_price = frappe.db.get_value(
            'Item Price',
            {
                'item_code': item_code,
                'price_list': buying_price_list
            },
            'price_list_rate'
        ) or 0

        # Get selling price
        sell_price = frappe.db.get_value(
            'Item Price',
            {
                'item_code': item_code,
                'price_list': selling_price_list
            },
            'price_list_rate'
        ) or 0

        results.append({
            'item_code': item.get('item_code'),
            'item_name': item.get('item_name'),
            'cost_price': cost_price,
            'sell_price': sell_price
        })

    return results


@frappe.whitelist()
def save_item_prices(items_str: str, selling_price_list: str) -> dict:
    """
    Save bulk updated item prices.

    Args:
        items_str: Pipe-delimited string of "item_code::price" pairs (e.g., "ITEM001::100.50|||ITEM002::200.00")
        selling_price_list: Name of the selling price list

    Returns:
        dict: Contains updated_count
    """
    if not items_str or not selling_price_list:
        frappe.throw(_("Missing required parameters"))

    # Split items
    items_data = items_str.split('|||')
    updated_count = 0

    for item_data in items_data:
        if not item_data or '::' not in item_data:
            continue

        try:
            item_code, price = item_data.split('::', 1)
            price = float(price)

            # Check if Item Price exists
            existing_price = frappe.db.exists(
                'Item Price',
                {
                    'item_code': item_code,
                    'price_list': selling_price_list
                }
            )

            if existing_price:
                # Update existing
                doc = frappe.get_doc('Item Price', existing_price)
                doc.price_list_rate = price
                doc.save(ignore_permissions=False)
            else:
                # Create new
                doc = frappe.get_doc({
                    'doctype': 'Item Price',
                    'item_code': item_code,
                    'price_list': selling_price_list,
                    'price_list_rate': price
                })
                doc.insert(ignore_permissions=False)

            updated_count += 1

        except Exception as e:
            frappe.log_error(f"Error updating price for {item_code}: {str(e)}", "Bulk Price Update Error")
            continue

    frappe.db.commit()

    return {
        'updated_count': updated_count
    }


@frappe.whitelist()
def check_duplicate_tax_id(doctype: str, tax_id: str, current_name: str = None) -> dict:
    """
    Check if a tax ID exists more than twice in Customer or Supplier records.

    Args:
        doctype: Either 'Customer' or 'Supplier'
        tax_id: The tax ID to check
        current_name: Current document name (to exclude from duplicates)

    Returns:
        dict: Contains 'has_duplicates' (bool) and 'duplicates' (list)
    """
    if not tax_id or doctype not in ['Customer', 'Supplier']:
        return {"has_duplicates": False, "duplicates": []}

    # Build filters
    filters = [
        [doctype, 'tax_id', '=', tax_id]
    ]

    # Exclude current document if editing
    if current_name:
        filters.append([doctype, 'name', '!=', current_name])

    # Get all records with the same tax_id
    duplicates = frappe.get_all(
        doctype,
        filters=filters,
        fields=['name', 'customer_name' if doctype == 'Customer' else 'supplier_name', 'creation'],
        order_by='creation desc'
    )

    # Format the results
    formatted_duplicates = []
    for dup in duplicates:
        formatted_duplicates.append({
            'name': dup.get('name'),
            'display_name': dup.get('customer_name') if doctype == 'Customer' else dup.get('supplier_name'),
            'creation': dup.get('creation')
        })

    # Check if tax_id exists more than twice (including current document)
    # If current_name is provided, duplicates count + 1 (current) > 2
    # If new document, duplicates count >= 2
    total_count = len(duplicates) + (1 if current_name else 1)
    has_duplicates = total_count > 1

    return {
        "has_duplicates": has_duplicates,
        "duplicates": formatted_duplicates,
        "total_count": total_count
    }
