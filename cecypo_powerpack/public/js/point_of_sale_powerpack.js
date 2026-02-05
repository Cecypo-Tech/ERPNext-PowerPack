(function() {
    let powerPackInitialized = false;
    let currentViewMode = localStorage.getItem('pos_powerpack_view_mode') || 'thumbnail';
    let originalRenderItemList = null;
    let originalGetItems = null;

    // Keyboard Navigation State
    let selectedItemIndex = -1;  // -1 = no selection
    let keyboardNavEnabled = false;

    // Configurable Columns State
    let columnConfig = {
        cost: false
    }; // Will be loaded from PowerPack Settings during initialization

    // Enhanced search enabled flag
    let enhancedSearchEnabled = true;

    // POS search fields from POS Profile
    let posSearchFields = [];

    // Cost permission check
    let canSeeCost = false;

    // Polling watcher - checks every 500ms like Mpesa implementation
    function watchForPOSReady() {
        if (initPowerPack()) {
            return;
        }
        setTimeout(watchForPOSReady, 500);
    }

    function initPowerPack() {
        if (typeof cur_pos === 'undefined' || !cur_pos.item_selector) {
            return false;
        }

        const posProfile = cur_pos.frm?.doc?.pos_profile;
        if (!posProfile) return false;

        // Check if PowerPack enabled via PowerPack Settings
        frappe.call({
            method: 'frappe.client.get_single_value',
            args: {
                doctype: 'PowerPack Settings',
                field: 'enable_pos_powerup'
            },
            callback: (r) => {
                if (r.message) {
                    loadPowerPackSettings();
                }
            }
        });

        return true;
    }

    function loadPowerPackSettings() {
        frappe.call({
            method: 'frappe.client.get',
            args: {
                doctype: 'PowerPack Settings',
                name: 'PowerPack Settings'
            },
            callback: (r) => {
                if (r.message) {
                    const settings = r.message;

                    // Load default view mode
                    if (settings.pos_default_view) {
                        const savedView = localStorage.getItem('pos_powerpack_view_mode');
                        if (!savedView) {
                            currentViewMode = settings.pos_default_view.toLowerCase();
                            localStorage.setItem('pos_powerpack_view_mode', currentViewMode);
                        }
                    }

                    // Load column configuration
                    columnConfig = {
                        cost: settings.pos_show_cost_price || false
                    };

                    // Load enhanced search setting
                    enhancedSearchEnabled = settings.pos_enable_custom_search || false;

                    // Check cost permission
                    canSeeCost = hasCostPermission();

                    // Load POS Profile search fields
                    loadPOSSearchFields();

                    // Enable features
                    enablePowerPackFeatures();
                }
            }
        });
    }

    function loadPOSSearchFields() {
        // Fetch POS Settings to get search fields (child table)
        frappe.call({
            method: 'frappe.client.get',
            args: {
                doctype: 'POS Settings',
                name: 'POS Settings'
            },
            callback: (r) => {
                if (r.message && r.message.pos_search_fields && Array.isArray(r.message.pos_search_fields)) {
                    // Extract fieldnames from child table
                    posSearchFields = r.message.pos_search_fields
                        .map(row => row.fieldname)
                        .filter(f => f && f.length > 0);

                    console.log('PowerPack: Loaded POS search fields from POS Settings:', posSearchFields);
                } else {
                    console.log('PowerPack: No POS search fields configured in POS Settings');
                }
            },
            error: (r) => {
                console.log('PowerPack: Could not load POS Settings');
            }
        });
    }

    function hasCostPermission() {
        const costRoles = [
            "System Manager",
            "Stock Manager",
            "Accounts Manager",
            "Sales Master Manager",
            "Administrator"
        ];
        return costRoles.some(role => frappe.user_roles.includes(role));
    }

    function enablePowerPackFeatures() {
        if (powerPackInitialized) return;

        injectViewToggleButtons();
        overrideRenderItemList();
        if (enhancedSearchEnabled) {
            enhanceSearchLogic();
        }
        enableBarcodeVisualFeedback();
        applyInitialView();

        powerPackInitialized = true;
    }

    function injectViewToggleButtons() {
        // Add buttons to the POS page's standard actions area (top right)
        // This is the most reliable location that's always visible
        const $standardActions = cur_pos.page.wrapper.find('.page-head .standard-actions');

        if ($standardActions.length === 0) {
            console.error('PowerPack: Could not find standard actions container');
            return;
        }

        // Create custom actions group
        const buttonsHtml = `
            <div class="powerpack-custom-actions">
                <button class="btn btn-sm btn-default view-toggle-btn ${currentViewMode === 'thumbnail' ? 'active' : ''}"
                        data-view="thumbnail" title="${__('Thumbnail View')}">
                    <i class="fa fa-th-large"></i>
                </button>
                <button class="btn btn-sm btn-default view-toggle-btn ${currentViewMode === 'compact' ? 'active' : ''}"
                        data-view="compact" title="${__('Compact Table View')}">
                    <i class="fa fa-list"></i>
                </button>
                <span class="powerpack-keyboard-hint" title="${__('Keyboard: ↑↓ Navigate | Enter Add | Esc Clear')}">
                    <i class="fa fa-keyboard-o text-muted"></i>
                </span>
            </div>
        `;

        // Prepend to standard actions so buttons appear before other action buttons
        $standardActions.prepend(buttonsHtml);

        $('.view-toggle-btn').on('click', function() {
            switchView($(this).data('view'));
        });
    }

    function applyInitialView() {
        // Apply the view mode styling immediately
        const $container = cur_pos.item_selector.$items_container;
        if (currentViewMode === 'compact') {
            $container.addClass('powerpack-compact-view').removeClass('powerpack-thumbnail-view');
        } else {
            $container.addClass('powerpack-thumbnail-view').removeClass('powerpack-compact-view');
        }
    }

    function switchView(viewMode) {
        currentViewMode = viewMode;
        localStorage.setItem('pos_powerpack_view_mode', viewMode);

        $('.view-toggle-btn').removeClass('active');
        $(`.view-toggle-btn[data-view="${viewMode}"]`).addClass('active');

        const $container = cur_pos.item_selector.$items_container;

        if (viewMode === 'compact') {
            $container.addClass('powerpack-compact-view').removeClass('powerpack-thumbnail-view');
            applyColumnConfig($container);
            enableKeyboardNavigation();
        } else {
            $container.addClass('powerpack-thumbnail-view').removeClass('powerpack-compact-view');
            disableKeyboardNavigation();
        }

        // Re-render current items with new view
        const items = cur_pos.item_selector.items || [];
        renderItemsInCurrentView(items);
    }

    // Override render_item_list to maintain view consistency
    function overrideRenderItemList() {
        originalRenderItemList = cur_pos.item_selector.render_item_list.bind(cur_pos.item_selector);

        cur_pos.item_selector.render_item_list = function(items) {
            // Store items
            this.items = items;

            // Render according to current view mode
            renderItemsInCurrentView(items);
        };
    }

    function renderItemsInCurrentView(items) {
        if (currentViewMode === 'compact') {
            renderItemsCompactView(items);
        } else {
            renderItemsThumbnailView(items);
        }
    }

    function renderItemsThumbnailView(items) {
        // Use original ERPNext rendering for thumbnail view
        if (originalRenderItemList) {
            originalRenderItemList(items);
        }
    }

    function fetchValuationRates(items) {
        if (!items || items.length === 0) return;

        // Get warehouse from POS - check multiple possible locations
        let warehouse = null;

        if (cur_pos.frm?.doc?.warehouse) {
            warehouse = cur_pos.frm.doc.warehouse;
        } else if (cur_pos.frm?.doc?.set_warehouse) {
            warehouse = cur_pos.frm.doc.set_warehouse;
        } else if (cur_pos.pos_profile?.warehouse) {
            warehouse = cur_pos.pos_profile.warehouse;
        } else if (cur_pos.frm?.doc?.pos_profile) {
            // Fetch warehouse from POS Profile
            frappe.db.get_value('POS Profile', cur_pos.frm.doc.pos_profile, 'warehouse')
                .then(r => {
                    if (r.message?.warehouse) {
                        fetchValuationRatesWithWarehouse(items, r.message.warehouse);
                    } else {
                        updateCostPriceDisplay({});
                    }
                });
            return;
        }

        if (!warehouse) {
            updateCostPriceDisplay({});
            return;
        }

        fetchValuationRatesWithWarehouse(items, warehouse);
    }

    function fetchValuationRatesWithWarehouse(items, warehouse) {
        // Get item codes
        const item_codes = items.map(item => item.item_code).filter(Boolean);
        if (item_codes.length === 0) {
            updateCostPriceDisplay({});
            return;
        }

        // Fetch valuation rates from Bin
        frappe.call({
            method: 'frappe.client.get_list',
            args: {
                doctype: 'Bin',
                filters: [
                    ['item_code', 'in', item_codes],
                    ['warehouse', '=', warehouse]
                ],
                fields: ['item_code', 'valuation_rate'],
                limit_page_length: 0
            },
            callback: (r) => {
                const valuationMap = {};

                if (r.message && r.message.length > 0) {
                    r.message.forEach(entry => {
                        if (entry.valuation_rate && entry.valuation_rate > 0) {
                            valuationMap[entry.item_code] = entry.valuation_rate;
                        }
                    });
                }

                updateCostPriceDisplay(valuationMap);
            },
            error: (r) => {
                updateCostPriceDisplay({});
            }
        });
    }

    function updateCostPriceDisplay(valuationMap) {
        $('.compact-item-cost').each(function() {
            const $costCol = $(this);
            const itemCode = unescape($costCol.data('item-code'));

            if (valuationMap[itemCode] && valuationMap[itemCode] > 0) {
                const valuationRate = valuationMap[itemCode];
                const precision = flt(valuationRate, 2) % 1 != 0 ? 2 : 0;
                $costCol.html(format_number(valuationRate, null, precision));
            } else {
                $costCol.html('—');
            }
        });
    }

    function renderItemsCompactView(items) {
        const $container = cur_pos.item_selector.$items_container;
        $container.html('');

        if (!items || items.length === 0) {
            $container.html('<div class="text-muted text-center" style="padding: 20px;">No items found</div>');
            return;
        }

        items.forEach(item => {
            $container.append(getCompactItemHtml(item));
        });

        bindCompactViewEvents();

        // Fetch valuation rates if cost column is enabled
        if (columnConfig.cost && canSeeCost) {
            fetchValuationRates(items);
        }
    }

    function getCompactItemHtml(item) {
        const { item_image, actual_qty, price_list_rate, uom, item_code } = item;
        const precision = flt(price_list_rate, 2) % 1 != 0 ? 2 : 0;

        // Stock indicator color
        const indicator_color = item.is_stock_item
            ? (actual_qty > 10 ? 'green' : actual_qty <= 0 ? 'red' : 'orange')
            : '';

        // Format qty display
        let qty_display = actual_qty;
        if (item.is_stock_item && Math.round(actual_qty) > 999) {
            qty_display = (Math.round(actual_qty) / 1000).toFixed(1) + 'K';
        }

        // Cost price column (only if enabled and user has permission)
        // Initial display - will be updated by fetchValuationRates
        const cost_column = (columnConfig.cost && canSeeCost)
            ? `<div class="compact-item-cost" data-item-code="${escape(item_code)}">
                —
               </div>`
            : '';

        return `
            <div class="powerpack-compact-item"
                 data-item-code="${escape(item_code)}"
                 data-serial-no="${escape(item.serial_no || '')}"
                 data-batch-no="${escape(item.batch_no || '')}"
                 data-uom="${escape(uom)}"
                 data-rate="${escape(price_list_rate || 0)}"
                 data-stock-uom="${escape(item.stock_uom)}">

                <div class="compact-item-image" data-image="${item_image || ''}">
                    ${item_image
                        ? `<img src="${item_image}" alt="${item.item_name}"
                                onerror="this.style.display='none'" />`
                        : `<div class="compact-item-abbr">${frappe.get_abbr(item.item_name)}</div>`
                    }
                </div>

                <div class="compact-item-details">
                    <div class="compact-item-name">${item.item_name}</div>
                    <div class="compact-item-code text-muted">${item_code}</div>
                </div>

                <div class="compact-item-stock">
                    ${qty_display ? `<span class="indicator-pill ${indicator_color}">${qty_display}</span>` : ''}
                </div>

                ${cost_column}

                <div class="compact-item-price">
                    ${format_number(price_list_rate, null, precision)} / ${uom}
                </div>

                <div class="compact-item-info">
                    <i class="fa fa-info-circle text-muted" title="${__('View Details')}"></i>
                </div>
            </div>
        `;
    }

    function bindCompactViewEvents() {
        selectedItemIndex = -1;  // Reset on re-render

        // Item click - add to cart
        $('.powerpack-compact-item').off('click').on('click', function(e) {
            if ($(e.target).closest('.compact-item-image').length) {
                return; // Don't add to cart if clicking image
            }
            if ($(e.target).closest('.compact-item-info').length) {
                return; // Don't add to cart if clicking info icon
            }

            const $item = $(this);
            cur_pos.item_selector.events.item_selected({
                field: 'qty',
                value: '+1',
                item: {
                    item_code: unescape($item.attr('data-item-code')),
                    batch_no: unescape($item.attr('data-batch-no')),
                    serial_no: unescape($item.attr('data-serial-no')),
                    uom: unescape($item.attr('data-uom')),
                    rate: unescape($item.attr('data-rate')),
                    stock_uom: unescape($item.attr('data-stock-uom'))
                }
            });
        });

        // Right-click for custom quantity
        $('.powerpack-compact-item').off('contextmenu').on('contextmenu', function(e) {
            e.preventDefault();
            const $item = $(this);
            showQuantityDialog($item);
        });

        // Info icon click
        $('.compact-item-info').off('click').on('click', function(e) {
            e.stopPropagation();
            const $item = $(this).closest('.powerpack-compact-item');
            const itemCode = unescape($item.attr('data-item-code'));
            showItemDetailsPanel(itemCode);
        });

        // Image click - open lightbox
        $('.compact-item-image').off('click').on('click', function(e) {
            e.stopPropagation();
            const imageUrl = $(this).data('image');
            if (imageUrl) {
                showImageLightbox(imageUrl);
            }
        });
    }

    function showImageLightbox(imageUrl) {
        const dialog = new frappe.ui.Dialog({
            title: __('Item Image'),
            size: 'large',
            fields: [{
                fieldtype: 'HTML',
                fieldname: 'image_preview',
                options: `<div style="text-align: center; padding: 20px;">
                    <img src="${imageUrl}" style="max-width: 100%; max-height: 70vh; height: auto;" />
                </div>`
            }]
        });

        dialog.show();
        dialog.$wrapper.find('.modal-dialog').css('max-width', '90vw');
    }

    // =========================================
    // Enhancement 1: Keyboard Navigation
    // =========================================

    function enableKeyboardNavigation() {
        if (keyboardNavEnabled) return;
        keyboardNavEnabled = true;
        $(document).on('keydown.powerpack-nav', handleKeyboardNavigation);
    }

    function disableKeyboardNavigation() {
        if (!keyboardNavEnabled) return;
        keyboardNavEnabled = false;
        selectedItemIndex = -1;
        clearItemSelection();
        $(document).off('keydown.powerpack-nav');
    }

    function handleKeyboardNavigation(e) {
        if (!keyboardNavEnabled || currentViewMode !== 'compact') return;

        const $items = $('.powerpack-compact-item');
        if ($items.length === 0) return;

        const key = e.key;
        if (!['ArrowUp', 'ArrowDown', 'Enter', 'Escape'].includes(key)) return;

        e.preventDefault();  // Prevent page scroll

        switch(key) {
            case 'ArrowDown':
                navigateDown($items);
                break;
            case 'ArrowUp':
                navigateUp($items);
                break;
            case 'Enter':
                selectCurrentItem();
                break;
            case 'Escape':
                clearItemSelection();
                break;
        }
    }

    function navigateDown($items) {
        selectedItemIndex++;
        if (selectedItemIndex >= $items.length) {
            selectedItemIndex = $items.length - 1;  // Clamp at end
        }
        highlightSelectedItem($items);
    }

    function navigateUp($items) {
        selectedItemIndex--;
        if (selectedItemIndex < 0) {
            selectedItemIndex = 0;  // Clamp at start
        }
        highlightSelectedItem($items);
    }

    function highlightSelectedItem($items) {
        $items.removeClass('powerpack-item-selected');

        if (selectedItemIndex >= 0 && selectedItemIndex < $items.length) {
            const $selected = $items.eq(selectedItemIndex);
            $selected.addClass('powerpack-item-selected');

            // Smooth scroll to keep in view
            $selected[0].scrollIntoView({
                behavior: 'smooth',
                block: 'nearest'
            });
        }
    }

    function selectCurrentItem() {
        const $items = $('.powerpack-compact-item');
        if (selectedItemIndex >= 0 && selectedItemIndex < $items.length) {
            const $item = $items.eq(selectedItemIndex);

            // Add to cart
            cur_pos.item_selector.events.item_selected({
                field: 'qty',
                value: '+1',
                item: {
                    item_code: unescape($item.attr('data-item-code')),
                    batch_no: unescape($item.attr('data-batch-no')),
                    serial_no: unescape($item.attr('data-serial-no')),
                    uom: unescape($item.attr('data-uom')),
                    rate: unescape($item.attr('data-rate')),
                    stock_uom: unescape($item.attr('data-stock-uom'))
                }
            });

            // Visual feedback flash
            $item.addClass('powerpack-item-added');
            setTimeout(() => $item.removeClass('powerpack-item-added'), 300);
        }
    }

    function clearItemSelection() {
        selectedItemIndex = -1;
        $('.powerpack-compact-item').removeClass('powerpack-item-selected');
    }

    // =========================================
    // Enhancement 2: Configurable Columns
    // =========================================

    function applyColumnConfig($container) {
        // Remove all hide classes first
        $container.removeClass('hide-column-cost');

        // Apply based on config
        if (!columnConfig.cost || !canSeeCost) $container.addClass('hide-column-cost');
    }


    // =========================================
    // Enhancement 3: Right-Click Quick Quantity
    // =========================================

    function showQuantityDialog($item) {
        const itemCode = unescape($item.attr('data-item-code'));
        const itemName = $item.find('.compact-item-name').text();

        frappe.prompt({
            label: __('Quantity for {0}', [itemName]),
            fieldname: 'qty',
            fieldtype: 'Int',
            default: 1,
            reqd: 1
        }, (values) => {
            if (values.qty && values.qty > 0) {
                cur_pos.item_selector.events.item_selected({
                    field: 'qty',
                    value: values.qty,
                    item: {
                        item_code: unescape($item.attr('data-item-code')),
                        batch_no: unescape($item.attr('data-batch-no')),
                        serial_no: unescape($item.attr('data-serial-no')),
                        uom: unescape($item.attr('data-uom')),
                        rate: unescape($item.attr('data-rate')),
                        stock_uom: unescape($item.attr('data-stock-uom'))
                    }
                });
            } else {
                frappe.show_alert({
                    message: __('Please enter a valid quantity'),
                    indicator: 'orange'
                }, 3);
            }
        }, __('Add to Cart'));
    }

    // =========================================
    // Enhancement 4: Item Details Preview Panel
    // =========================================

    function showItemDetailsPanel(itemCode) {
        // Show loading indicator
        frappe.show_alert({
            message: __('Loading item details...'),
            indicator: 'blue'
        }, 2);

        // Fetch full item details
        frappe.call({
            method: 'frappe.client.get',
            args: {
                doctype: 'Item',
                name: itemCode
            },
            callback: (r) => {
                if (r.message) {
                    renderItemDetailsPanel(r.message);
                }
            }
        });
    }

    function renderItemDetailsPanel(item) {
        // Remove existing panel if any
        $('.powerpack-details-panel').remove();

        // Build HTML
        const panelHtml = `
            <div class="powerpack-details-panel">
                <div class="panel-overlay"></div>
                <div class="panel-content">
                    <div class="panel-header">
                        <h4>${item.item_name}</h4>
                        <button class="btn btn-sm panel-close">
                            <i class="fa fa-times"></i>
                        </button>
                    </div>
                    <div class="panel-body">
                        ${item.image ? `
                            <div class="detail-section">
                                <img src="${item.image}" alt="${item.item_name}"
                                     style="max-width: 100%; max-height: 200px; object-fit: contain;">
                            </div>
                        ` : ''}

                        ${item.description ? `
                            <div class="detail-section">
                                <label class="detail-label">${__('Description')}</label>
                                <div class="detail-value">${item.description}</div>
                            </div>
                        ` : ''}

                        <div class="detail-section">
                            <label class="detail-label">${__('Item Code')}</label>
                            <div class="detail-value">${item.item_code}</div>
                        </div>

                        <div class="detail-section">
                            <label class="detail-label">${__('Item Group')}</label>
                            <div class="detail-value">${item.item_group}</div>
                        </div>

                        <div class="detail-section">
                            <label class="detail-label">${__('Stock UOM')}</label>
                            <div class="detail-value">${item.stock_uom}</div>
                        </div>

                        ${item.brand ? `
                            <div class="detail-section">
                                <label class="detail-label">${__('Brand')}</label>
                                <div class="detail-value">${item.brand}</div>
                            </div>
                        ` : ''}

                        ${item.attributes && item.attributes.length > 0 ? `
                            <div class="detail-section">
                                <label class="detail-label">${__('Attributes')}</label>
                                ${item.attributes.map(attr => `
                                    <div class="detail-value">
                                        <strong>${attr.attribute}:</strong> ${attr.attribute_value}
                                    </div>
                                `).join('')}
                            </div>
                        ` : ''}

                        <div class="detail-section">
                            <label class="detail-label">${__('Stock by Warehouse')}</label>
                            <button class="btn btn-sm btn-default load-stock-btn"
                                    data-item-code="${item.item_code}">
                                ${__('Load Stock Details')}
                            </button>
                            <div class="stock-details-container"></div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        $('body').append(panelHtml);

        // Slide in animation
        setTimeout(() => {
            $('.powerpack-details-panel').addClass('active');
        }, 10);

        // Bind close events
        $('.panel-close, .panel-overlay').on('click', closeItemDetailsPanel);

        // Bind load stock button
        $('.load-stock-btn').on('click', function() {
            const itemCode = $(this).data('item-code');
            loadStockByWarehouse(itemCode);
        });
    }

    function closeItemDetailsPanel() {
        $('.powerpack-details-panel').removeClass('active');
        setTimeout(() => {
            $('.powerpack-details-panel').remove();
        }, 300);
    }

    function loadStockByWarehouse(itemCode) {
        $('.load-stock-btn').prop('disabled', true).html(__('Loading...'));

        frappe.call({
            method: 'erpnext.stock.dashboard.item_dashboard.get_data',
            args: {
                item_code: itemCode
            },
            callback: (r) => {
                if (r.message) {
                    const stockHtml = r.message.map(warehouse => `
                        <div class="stock-warehouse-row">
                            <span class="warehouse-name">${warehouse.warehouse}</span>
                            <span class="warehouse-qty ${warehouse.actual_qty > 0 ? 'text-success' : 'text-muted'}">
                                ${warehouse.actual_qty} ${warehouse.stock_uom}
                            </span>
                        </div>
                    `).join('');

                    $('.stock-details-container').html(stockHtml || '<p class="text-muted">No stock data available</p>');
                }
                $('.load-stock-btn').hide();
            }
        });
    }

    // =========================================
    // Enhancement 5: Barcode Visual Feedback
    // =========================================

    function enableBarcodeVisualFeedback() {
        // Override item selection after barcode scan
        const originalItemSelected = cur_pos.item_selector.events.item_selected;
        cur_pos.item_selector.events.item_selected = function(args) {
            // Call original
            originalItemSelected.call(this, args);

            // Provide visual feedback
            if (args.field === 'barcode' || args.field === 'serial_no') {
                highlightScannedItem(args.item.item_code);
            }
        };
    }

    function highlightScannedItem(itemCode) {
        // Find item in current view
        const $item = $(`.powerpack-compact-item[data-item-code="${itemCode}"]`);

        if ($item.length > 0) {
            // Scroll to item
            $item[0].scrollIntoView({
                behavior: 'smooth',
                block: 'center'
            });

            // Flash highlight
            $item.addClass('powerpack-barcode-scanned');
            setTimeout(() => {
                $item.removeClass('powerpack-barcode-scanned');
            }, 1000);

            // Optional: Audio feedback
            if (window.AudioContext || window.webkitAudioContext) {
                playBeep();
            }
        }
    }

    function playBeep() {
        try {
            const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            const oscillator = audioCtx.createOscillator();
            const gainNode = audioCtx.createGain();

            oscillator.connect(gainNode);
            gainNode.connect(audioCtx.destination);

            oscillator.frequency.value = 800;
            oscillator.type = 'sine';

            gainNode.gain.setValueAtTime(0.3, audioCtx.currentTime);
            gainNode.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.1);

            oscillator.start(audioCtx.currentTime);
            oscillator.stop(audioCtx.currentTime + 0.1);
        } catch (e) {
            // Silently fail if audio not supported
        }
    }

    function enhanceSearchLogic() {
        // Check if the item selector exists
        if (!cur_pos.item_selector || !cur_pos.item_selector.$component) {
            return;
        }

        // Wait a moment for POS to fully initialize
        setTimeout(() => {
            try {
                // Create a new prominent search box at the top
                createPowerPackSearchBox();
            } catch (error) {
                console.error('PowerPack: Error setting up enhanced search', error);
            }
        }, 1000);
    }

    function createPowerPackSearchBox() {
        // Check if already created
        if ($('.powerpack-search-box').length > 0) {
            return;
        }

        // Find the items container
        const $itemsContainer = cur_pos.item_selector.$component;
        if (!$itemsContainer.length) {
            return;
        }

        // Create enhanced search box HTML
        const searchBoxHtml = `
            <div class="powerpack-search-box">
                <div class="powerpack-search-input-wrapper">
                    <input type="text"
                           class="powerpack-search-input form-control"
                           placeholder="Enhanced Search (use % for wildcard, e.g., sam%tv or type multiple words)"
                           autocomplete="off">
                    <button class="powerpack-search-clear-btn" style="display: none;">
                        <i class="fa fa-times"></i>
                    </button>
                </div>
            </div>
            <style>
                .powerpack-search-box {
                    padding: 10px;
                    background: var(--fg-color);
                    border-bottom: 2px solid var(--primary);
                    position: sticky;
                    top: 0;
                    z-index: 100;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }

                .powerpack-search-input-wrapper {
                    position: relative;
                }

                .powerpack-search-input {
                    width: 100%;
                    padding: 8px 35px 8px 12px;
                    font-size: 14px;
                    border: 2px solid var(--border-color);
                    border-radius: 6px;
                    transition: all 0.2s;
                }

                .powerpack-search-input:focus {
                    border-color: var(--primary);
                    box-shadow: 0 0 0 3px rgba(var(--primary-rgb), 0.1);
                    outline: none;
                }

                .powerpack-search-clear-btn {
                    position: absolute;
                    right: 8px;
                    top: 50%;
                    transform: translateY(-50%);
                    background: none;
                    border: none;
                    color: var(--text-muted);
                    cursor: pointer;
                    padding: 4px 8px;
                    border-radius: 4px;
                    transition: all 0.2s;
                }

                .powerpack-search-clear-btn:hover {
                    background: var(--gray-100);
                    color: var(--text-color);
                }

                .powerpack-search-hint {
                    font-size: 11px;
                    color: var(--text-muted);
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }

                .powerpack-search-hint code {
                    background: var(--gray-100);
                    padding: 2px 6px;
                    border-radius: 3px;
                    font-size: 10px;
                    color: var(--primary);
                }
            </style>
        `;

        // Insert at the top of items container
        $itemsContainer.prepend(searchBoxHtml);

        const $searchInput = $('.powerpack-search-input');
        const $clearBtn = $('.powerpack-search-clear-btn');

        // Cache all items when POS loads
        let allItemsCache = [];

        // Get initial items
        setTimeout(() => {
            fetchAndCacheAllItems();
        }, 500);

        // Search input handler
        let searchTimeout;
        $searchInput.on('input', function() {
            const searchTerm = $(this).val().trim();

            // Toggle clear button
            $clearBtn.toggle(searchTerm.length > 0);

            // Debounce search
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                performEnhancedSearch(searchTerm);
            }, 300);
        });

        // Clear button handler
        $clearBtn.on('click', function() {
            $searchInput.val('').trigger('input').focus();
        });

        // ESC key to clear
        $searchInput.on('keydown', function(e) {
            if (e.key === 'Escape') {
                $searchInput.val('').trigger('input');
            }
        });

        // Focus search on Ctrl+K
        $(document).on('keydown.powerpack-search', function(e) {
            if (e.ctrlKey && e.key === 'k') {
                e.preventDefault();
                $searchInput.focus();
            }
        });

        function fetchAndCacheAllItems() {
            // Call POS get_items to fetch and cache all items
            if (cur_pos.item_selector.get_items) {
                cur_pos.item_selector.get_items(0).then((r) => {
                    if (r && r.message && r.message.items) {
                        allItemsCache = r.message.items;
                    }
                });
            }
        }

        function performEnhancedSearch(searchTerm) {
            if (!searchTerm) {
                // No search - show all items
                if (allItemsCache.length > 0) {
                    cur_pos.item_selector.render_item_list(allItemsCache);
                } else {
                    fetchAndCacheAllItems();
                }
                return;
            }

            // Apply enhanced search
            if (allItemsCache.length > 0) {
                const filtered = getSortedFilteredData(allItemsCache, searchTerm);
                cur_pos.item_selector.render_item_list(filtered);
            } else {
                fetchAndCacheAllItems();
            }
        }
    }

    function wildcard_to_regex(pattern) {
        // Convert wildcard pattern to regex
        // Escape special regex chars, then replace % with .*
        const escaped = pattern
            .split('%')
            .map(s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
            .join('.*');
        return new RegExp(escaped, 'i');
    }

    function getSortedFilteredData(items, search_term) {
        // Validate inputs
        if (!items || !Array.isArray(items) || items.length === 0) {
            return items || [];
        }

        if (!search_term || typeof search_term !== 'string') {
            return items;
        }

        const search_lower = search_term.toLowerCase();

        // Check if using wildcard pattern (%)
        const hasWildcard = search_term.includes('%');

        let scoredItems;

        if (hasWildcard) {
            // Wildcard search using regex (matching bulk_selection logic)
            const pattern_local = wildcard_to_regex(search_lower);

            scoredItems = items.map(item => {
                const item_code_lower = (item.item_code || '').toLowerCase();
                const item_name_lower = (item.item_name || '').toLowerCase();

                // Build combined string with POS search fields
                let combined = item_code_lower + ' ' + item_name_lower;

                // Add POS search fields to combined string
                if (posSearchFields && posSearchFields.length > 0) {
                    posSearchFields.forEach(field => {
                        const fieldValue = (item[field] || '').toString().toLowerCase();
                        if (fieldValue) {
                            combined += ' ' + fieldValue;
                        }
                    });
                }

                let score = 0;

                if (pattern_local.test(combined)) {
                    score += 10;

                    // Boost for item_code match
                    if (pattern_local.test(item_code_lower)) {
                        score += 30;
                    }

                    // Check POS search fields for matches
                    if (posSearchFields && posSearchFields.length > 0) {
                        posSearchFields.forEach(field => {
                            const fieldValue = (item[field] || '').toString().toLowerCase();
                            if (fieldValue && pattern_local.test(fieldValue)) {
                                score += 20; // Boost for POS search field match
                            }
                        });
                    }

                    // Boost for exact match
                    const clean_search = search_term.replace(/%/g, '').toLowerCase();
                    if (item_code_lower === clean_search) {
                        score += 100;
                    }

                    // Boost for start-of-string
                    if (item_code_lower.startsWith(clean_search)) {
                        score += 50;
                    }
                }

                return { item, score };
            });
        } else {
            // Natural multi-word search mode (matching bulk_selection logic)
            const tokens = search_lower.split(/\s+/).filter(t => t.length > 0);

            scoredItems = items.map(item => {
                const item_code_lower = (item.item_code || '').toLowerCase();
                const item_name_lower = (item.item_name || '').toLowerCase();

                // Build combined string with POS search fields
                let combined = item_code_lower + ' ' + item_name_lower;

                // Add POS search fields to combined string
                if (posSearchFields && posSearchFields.length > 0) {
                    posSearchFields.forEach(field => {
                        const fieldValue = (item[field] || '').toString().toLowerCase();
                        if (fieldValue) {
                            combined += ' ' + fieldValue;
                        }
                    });
                }

                // Check if ALL tokens match somewhere
                const all_match = tokens.every(token => combined.includes(token));

                let score = 0;

                if (all_match) {
                    tokens.forEach(token => {
                        // Exact match in item_code (highest priority)
                        if (item_code_lower === token) score += 100;
                        // Item code starts with token
                        else if (item_code_lower.startsWith(token)) score += 50;
                        // Token in item_code
                        else if (item_code_lower.includes(token)) score += 30;

                        // Exact word match in item_name
                        const name_words = item_name_lower.split(/\s+/);
                        if (name_words.includes(token)) score += 25;
                        // Item name starts with token
                        else if (item_name_lower.startsWith(token)) score += 15;
                        // Token in item_name
                        else if (item_name_lower.includes(token)) score += 10;

                        // Check POS search fields for matches
                        if (posSearchFields && posSearchFields.length > 0) {
                            posSearchFields.forEach(field => {
                                const fieldValue = (item[field] || '').toString().toLowerCase();
                                if (fieldValue) {
                                    // Exact match in POS search field
                                    if (fieldValue === token) score += 40;
                                    // Starts with token
                                    else if (fieldValue.startsWith(token)) score += 20;
                                    // Contains token
                                    else if (fieldValue.includes(token)) score += 12;
                                }
                            });
                        }
                    });

                    // Bonus for shorter item codes (more specific matches)
                    score += Math.max(0, 20 - item_code_lower.length);
                }

                return { item, score };
            });
        }

        // Filter items with score > 0 and sort by score descending
        return scoredItems
            .filter(x => x.score > 0)
            .sort((a, b) => b.score - a.score)
            .map(x => x.item);
    }

    // Start watching for POS ready
    watchForPOSReady();
})();
