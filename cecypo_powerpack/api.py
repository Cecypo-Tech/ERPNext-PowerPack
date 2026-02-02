# Copyright (c) 2026, Cecypo.Tech and contributors
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
            "enable_quotation_powerup_value": settings.get('enable_quotation_powerup'),
            "enable_quotation_powerup_type": str(type(settings.get('enable_quotation_powerup'))),
            "is_quotation_powerup_enabled": is_feature_enabled('enable_quotation_powerup'),
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


@frappe.whitelist()
def get_bulk_item_details(items, price_list: str, warehouse: str = None, customer: str = None,
                          tax_category: str = None, taxes_and_charges: str = None,
                          optimized: bool = True, doctype: str = 'Sales Order') -> dict:
    """
    Get bulk item details for bulk selection in sales documents.

    Args:
        items: List of item codes (or pipe-delimited string)
        price_list: Selling price list name
        warehouse: Warehouse name (optional for Quotation)
        customer: Customer name (optional)
        tax_category: Tax category (optional, will be fetched from customer if not provided)
        taxes_and_charges: Tax template name (for included_in_print_rate calculation)
        optimized: Use optimized batch queries (default: True)
        doctype: DocType name (Sales Order, Sales Invoice, Quotation)

    Returns:
        dict: Contains 'items' (list), 'total_items' (int), 'tax_category' (str), 'tax_rate' (float)
    """
    from cecypo_powerpack.utils import is_feature_enabled

    # Check if feature is enabled based on doctype
    feature_map = {
        'Sales Order': 'enable_sales_order_bulk_selection',
        'Sales Invoice': 'enable_sales_invoice_bulk_selection',
        'Quotation': 'enable_quotation_bulk_selection'
    }

    feature_name = feature_map.get(doctype, 'enable_sales_order_bulk_selection')
    if not is_feature_enabled(feature_name):
        frappe.throw(_("Bulk Selection feature is not enabled for {0} in PowerPack Settings").format(doctype))

    # Parse items input
    if isinstance(items, str):
        items = items.strip()
        if items.startswith('[') and items.endswith(']'):
            items = items[1:-1]
        if not items:
            items = []
        else:
            items = [item.strip().strip('"').strip("'").strip()
                    for item in items.split(',') if item.strip()]
    elif not isinstance(items, list):
        items = []

    if not items:
        frappe.throw(_("No items provided"))

    if not price_list:
        frappe.throw(_("Price List is required"))

    # Warehouse is optional for Quotation
    if warehouse and not frappe.db.exists('Warehouse', warehouse):
        frappe.throw(_("Warehouse {0} does not exist").format(warehouse))

    if not frappe.db.exists('Price List', price_list):
        frappe.throw(_("Price List {0} does not exist").format(price_list))

    # Get tax category from customer if not provided
    if not tax_category and customer:
        tax_category = frappe.db.get_value('Customer', customer, 'tax_category')

    # Calculate tax rate for included_in_print_rate taxes
    tax_rate = 0.0
    if taxes_and_charges:
        tax_rate = _get_included_tax_rate(taxes_and_charges)

    # Convert string 'true'/'false' to boolean
    if isinstance(optimized, str):
        optimized = optimized.lower() == 'true'

    try:
        if optimized:
            # Optimized batch fetch
            result = _get_bulk_items_optimized(items, price_list, warehouse, tax_category, tax_rate)
        else:
            # Standard iteration
            result = _get_bulk_items_standard(items, price_list, warehouse, tax_category, tax_rate)

        result['tax_category'] = tax_category or ''
        result['tax_rate'] = tax_rate
        return result

    except Exception as e:
        frappe.log_error(
            message=str(e),
            title="Bulk Item Details Critical Error"
        )
        frappe.throw(_("Error loading item details: {0}").format(str(e)))


def _get_included_tax_rate(taxes_and_charges):
    """
    Calculate total tax rate for taxes with included_in_print_rate=1

    Args:
        taxes_and_charges: Tax template name (Sales Taxes and Charges Template)

    Returns:
        float: Total tax percentage
    """
    if not taxes_and_charges:
        return 0.0

    try:
        # Get the tax template
        tax_template = frappe.get_cached_doc('Sales Taxes and Charges Template', taxes_and_charges)

        total_tax_rate = 0.0
        for tax in tax_template.taxes:
            # Only include taxes with included_in_print_rate=1
            if tax.included_in_print_rate:
                total_tax_rate += (tax.rate or 0)

        return total_tax_rate

    except Exception as e:
        frappe.log_error(
            message=f"Error calculating tax rate for {taxes_and_charges}: {str(e)}",
            title="Tax Rate Calculation Error"
        )
        return 0.0


def _get_bulk_items_optimized(items, price_list, warehouse, tax_category, tax_rate=0.0):
    """Optimized batch fetch for bulk items"""
    # Batch fetch all items at once
    item_docs = frappe.db.get_all(
        'Item',
        filters={
            'name': ['in', items],
            'disabled': 0,
            'is_sales_item': 1
        },
        fields=['name', 'item_name', 'description', 'stock_uom', 'image', 'valuation_rate']
    )

    if not item_docs:
        return {'items': [], 'total_items': 0}

    item_codes = [item['name'] for item in item_docs]

    # Batch fetch prices
    prices = {}
    price_data = frappe.db.get_all(
        'Item Price',
        filters={
            'item_code': ['in', item_codes],
            'price_list': price_list,
            'selling': 1
        },
        fields=['item_code', 'price_list_rate']
    )
    for p in price_data:
        prices[p['item_code']] = p['price_list_rate']

    # Batch fetch stock and valuation from Bin
    stock = {}
    bin_valuation = {}
    if warehouse:
        bin_data = frappe.db.get_all(
            'Bin',
            filters={
                'item_code': ['in', item_codes],
                'warehouse': warehouse
            },
            fields=['item_code', 'actual_qty', 'valuation_rate']
        )
        for b in bin_data:
            stock[b['item_code']] = b['actual_qty']
            if b.get('valuation_rate'):
                bin_valuation[b['item_code']] = b['valuation_rate']

    # Batch fetch item tax templates
    item_taxes_map = {}
    tax_data = frappe.db.get_all(
        'Item Tax',
        filters={
            'parent': ['in', item_codes],
            'parenttype': 'Item'
        },
        fields=['parent', 'item_tax_template', 'tax_category'],
        order_by='idx'
    )
    for t in tax_data:
        if t['parent'] not in item_taxes_map:
            item_taxes_map[t['parent']] = []
        item_taxes_map[t['parent']].append({
            'item_tax_template': t['item_tax_template'],
            'tax_category': t['tax_category']
        })

    # Combine all data
    result = []
    for item in item_docs:
        item_code = item['name']
        item_tax_template = _get_item_tax_template_for_category(
            item_code,
            tax_category,
            item_taxes_map
        )

        # Use bin valuation if available, otherwise item valuation
        valuation = bin_valuation.get(item_code) or item.get('valuation_rate', 0) or 0

        # Apply tax adjustment to valuation rate if taxes are included in print rate
        if tax_rate > 0 and valuation > 0:
            valuation = valuation * (1 + tax_rate / 100)

        result.append({
            'item_code': item_code,
            'item_name': item.get('item_name') or item_code,
            'description': item.get('description') or item.get('item_name') or item_code,
            'stock_uom': item.get('stock_uom') or 'Nos',
            'image': _get_item_image_url(item.get('image')),
            'valuation_rate': float(valuation),
            'price_list_rate': float(prices.get(item_code, 0)),
            'actual_qty': float(stock.get(item_code, 0)),
            'item_tax_template': item_tax_template or ''
        })

    result.sort(key=lambda x: x['item_code'])

    return {
        'items': result,
        'total_items': len(result)
    }


def _get_bulk_items_standard(items, price_list, warehouse, tax_category, tax_rate=0.0):
    """Standard iteration for bulk items"""
    result = []

    for item_code in items:
        if not item_code:
            continue

        if not frappe.db.exists('Item', item_code):
            continue

        try:
            item_doc = frappe.get_cached_doc('Item', item_code)

            if item_doc.disabled or not item_doc.is_sales_item:
                continue

            # Get valuation - prefer bin valuation for the warehouse
            valuation_rate = _get_valuation_rate(item_code, warehouse)
            price_list_rate = _get_item_price(item_code, price_list)
            actual_qty = _get_stock_qty(item_code, warehouse) if warehouse else 0

            # Apply tax adjustment to valuation rate if taxes are included in print rate
            if tax_rate > 0 and valuation_rate > 0:
                valuation_rate = valuation_rate * (1 + tax_rate / 100)

            # Get item tax template
            item_tax_template = None
            if item_doc.taxes:
                if tax_category:
                    for tax in item_doc.taxes:
                        if tax.tax_category == tax_category:
                            item_tax_template = tax.item_tax_template
                            break

                if not item_tax_template:
                    for tax in item_doc.taxes:
                        if not tax.tax_category:
                            item_tax_template = tax.item_tax_template
                            break

                if not item_tax_template and item_doc.taxes:
                    item_tax_template = item_doc.taxes[0].item_tax_template

            result.append({
                'item_code': item_code,
                'item_name': item_doc.item_name or item_code,
                'description': item_doc.description or item_doc.item_name or item_code,
                'stock_uom': item_doc.stock_uom or 'Nos',
                'image': _get_item_image_url(item_doc.image),
                'valuation_rate': float(valuation_rate),
                'price_list_rate': float(price_list_rate),
                'actual_qty': float(actual_qty),
                'item_tax_template': item_tax_template or ''
            })

        except Exception as e:
            frappe.log_error(
                message=f"Error fetching details for {item_code}: {str(e)}",
                title="Bulk Item Details Error"
            )
            continue

    result.sort(key=lambda x: x.get('item_code', ''))

    return {
        'items': result,
        'total_items': len(result)
    }


def _get_item_image_url(image):
    """Helper to get valid image URL"""
    if not image:
        return None

    if image.startswith(('http://', 'https://', '/files/')):
        return image

    return None


def _get_valuation_rate(item_code, warehouse=None):
    """Get valuation rate - try warehouse-specific first, then item default"""
    # Try warehouse-specific valuation first
    if warehouse:
        rate = frappe.db.get_value(
            'Bin',
            {
                'item_code': item_code,
                'warehouse': warehouse
            },
            'valuation_rate'
        )
        if rate:
            return rate

    # Fall back to item's valuation rate
    try:
        rate = frappe.db.get_value('Item', item_code, 'valuation_rate')
        return rate if rate else 0
    except (frappe.DoesNotExistError, AttributeError, TypeError):
        return 0


def _get_item_price(item_code, price_list):
    """Get item price with error handling"""
    try:
        price = frappe.db.get_value(
            'Item Price',
            {
                'item_code': item_code,
                'price_list': price_list,
                'selling': 1
            },
            'price_list_rate'
        )
        return price if price else 0
    except (frappe.DoesNotExistError, AttributeError, TypeError):
        return 0


def _get_stock_qty(item_code, warehouse):
    """Get stock quantity with error handling"""
    if not warehouse:
        return 0

    try:
        qty = frappe.db.get_value(
            'Bin',
            {
                'item_code': item_code,
                'warehouse': warehouse
            },
            'actual_qty'
        )
        return qty if qty else 0
    except (frappe.DoesNotExistError, AttributeError, TypeError):
        return 0


def _get_item_tax_template_for_category(item_code, tax_category, item_taxes_map):
    """
    Get the appropriate Item Tax Template based on tax category.
    Returns template matching tax_category, or default (no category) if not found.
    """
    templates = item_taxes_map.get(item_code, [])

    if not templates:
        return None

    # First, try to find exact match for tax category
    if tax_category:
        for t in templates:
            if t.get('tax_category') == tax_category:
                return t.get('item_tax_template')

    # Fall back to template with no tax category (default)
    for t in templates:
        if not t.get('tax_category'):
            return t.get('item_tax_template')

    # If nothing matches, return first available
    return templates[0].get('item_tax_template') if templates else None
