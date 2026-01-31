(function() {
    console.log('🟢 PowerPack by Cecypo.Tech: Loading...');

    let powerPackInitialized = false;
    let currentViewMode = localStorage.getItem('pos_powerpack_view_mode') || 'thumbnail';
    let originalRenderItemList = null;
    let originalGetItems = null;

    // Keyboard Navigation State
    let selectedItemIndex = -1;  // -1 = no selection
    let keyboardNavEnabled = false;

    // Configurable Columns State
    let columnConfig = {
        image: true,
        code: true,
        stock: true,
        price: true
    }; // Will be loaded from POS Profile during initialization

    // Bulk Mode State
    let bulkModeActive = false;
    let bulkSelections = {};  // { item_code: qty }

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

        // Check if PowerPack enabled via API call
        frappe.call({
            method: 'frappe.client.get_value',
            args: {
                doctype: 'POS Profile',
                filters: { name: posProfile },
                fieldname: 'enable_powerpack_by_cecypo'
            },
            callback: (r) => {
                if (r.message?.enable_powerpack_by_cecypo) {
                    enablePowerPackFeatures();
                }
            }
        });

        return true;
    }

    function enablePowerPackFeatures() {
        if (powerPackInitialized) return;

        injectViewToggleButtons();
        overrideRenderItemList();
        enhanceSearchLogic();
        loadColumnConfig();
        enableBarcodeVisualFeedback();
        applyInitialView();

        powerPackInitialized = true;
        console.log('✅ PowerPack features enabled');
    }

    function injectViewToggleButtons() {
        const $filterSection = cur_pos.item_selector.$component.find('.filter-section');

        $filterSection.find('.label').after(`
            <div class="powerpack-view-toggle">
                <button class="btn btn-sm view-toggle-btn ${currentViewMode === 'thumbnail' ? 'active' : ''}"
                        data-view="thumbnail" title="${__('Thumbnail View')}">
                    <i class="fa fa-th-large"></i>
                </button>
                <button class="btn btn-sm view-toggle-btn ${currentViewMode === 'compact' ? 'active' : ''}"
                        data-view="compact" title="${__('Compact Table View')}">
                    <i class="fa fa-list"></i>
                </button>
                <button class="btn btn-sm powerpack-settings-btn" title="${__('Column Settings')}">
                    <i class="fa fa-cog"></i>
                </button>
                <button class="btn btn-sm powerpack-bulk-toggle-btn" title="${__('Bulk Add Mode')}">
                    <i class="fa fa-check-square-o"></i> ${__('Bulk')}
                </button>
                <div class="powerpack-keyboard-hint" title="${__('Keyboard: ↑↓ Navigate | Enter Add | Esc Clear')}">
                    <i class="fa fa-keyboard-o text-muted"></i>
                </div>
            </div>
        `);

        $('.view-toggle-btn').on('click', function() {
            switchView($(this).data('view'));
        });

        $('.powerpack-settings-btn').on('click', function() {
            showColumnSettingsDialog();
        });

        $('.powerpack-bulk-toggle-btn').on('click', function() {
            toggleBulkMode();
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

                <div class="compact-item-price">
                    ${format_currency(price_list_rate, item.currency, precision)} / ${uom}
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
        $container.removeClass('hide-column-image hide-column-code hide-column-stock hide-column-price');

        // Apply based on config
        if (!columnConfig.image) $container.addClass('hide-column-image');
        if (!columnConfig.code) $container.addClass('hide-column-code');
        if (!columnConfig.stock) $container.addClass('hide-column-stock');
        if (!columnConfig.price) $container.addClass('hide-column-price');
    }

    function loadColumnConfig() {
        // Load column config from POS Profile
        const posProfile = cur_pos.frm?.doc?.pos_profile;
        if (!posProfile) return;

        frappe.call({
            method: 'frappe.client.get_value',
            args: {
                doctype: 'POS Profile',
                filters: { name: posProfile },
                fieldname: 'powerpack_column_config'
            },
            callback: (r) => {
                if (r.message?.powerpack_column_config) {
                    try {
                        columnConfig = JSON.parse(r.message.powerpack_column_config);
                    } catch (e) {
                        console.error('Failed to parse column config:', e);
                        // Use defaults
                    }
                }

                // Apply config to current view
                if (currentViewMode === 'compact') {
                    const $container = cur_pos.item_selector.$items_container;
                    applyColumnConfig($container);
                }
            }
        });
    }

    function saveColumnConfig() {
        const posProfile = cur_pos.frm?.doc?.pos_profile;
        if (!posProfile) return Promise.reject('No POS Profile');

        return frappe.call({
            method: 'frappe.client.set_value',
            args: {
                doctype: 'POS Profile',
                name: posProfile,
                fieldname: 'powerpack_column_config',
                value: JSON.stringify(columnConfig)
            }
        });
    }

    function showColumnSettingsDialog() {
        const dialog = new frappe.ui.Dialog({
            title: __('Compact View Column Settings'),
            fields: [
                {
                    fieldtype: 'HTML',
                    fieldname: 'help',
                    options: '<p class="text-muted small">' +
                             __('Choose which columns to display in compact view') +
                             '</p>'
                },
                {
                    fieldtype: 'Check',
                    fieldname: 'show_image',
                    label: __('Show Image'),
                    default: columnConfig.image ? 1 : 0
                },
                {
                    fieldtype: 'Check',
                    fieldname: 'show_code',
                    label: __('Show Item Code'),
                    default: columnConfig.code ? 1 : 0
                },
                {
                    fieldtype: 'Check',
                    fieldname: 'show_stock',
                    label: __('Show Stock'),
                    default: columnConfig.stock ? 1 : 0
                },
                {
                    fieldtype: 'Check',
                    fieldname: 'show_price',
                    label: __('Show Price'),
                    default: columnConfig.price ? 1 : 0
                },
                {
                    fieldtype: 'HTML',
                    fieldname: 'note',
                    options: '<p class="text-muted small" style="margin-top: 10px;">' +
                             '<i class="fa fa-info-circle"></i> ' +
                             __('Item Name is always visible') +
                             '</p>'
                }
            ],
            primary_action_label: __('Apply'),
            primary_action: (values) => {
                columnConfig = {
                    image: values.show_image ? true : false,
                    code: values.show_code ? true : false,
                    stock: values.show_stock ? true : false,
                    price: values.show_price ? true : false
                };

                // Save to POS Profile
                saveColumnConfig().then(() => {
                    const $container = cur_pos.item_selector.$items_container;
                    applyColumnConfig($container);

                    dialog.hide();

                    frappe.show_alert({
                        message: __('Column settings saved'),
                        indicator: 'green'
                    }, 3);
                }).catch((err) => {
                    frappe.show_alert({
                        message: __('Failed to save settings'),
                        indicator: 'red'
                    }, 3);
                    console.error('Save error:', err);
                });
            },
            secondary_action_label: __('Reset to Default'),
            secondary_action: () => {
                dialog.set_value('show_image', 1);
                dialog.set_value('show_code', 1);
                dialog.set_value('show_stock', 1);
                dialog.set_value('show_price', 1);
            }
        });

        dialog.show();
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

    // =========================================
    // Enhancement 6: Bulk Add Mode
    // =========================================

    function toggleBulkMode() {
        bulkModeActive = !bulkModeActive;

        if (bulkModeActive) {
            enableBulkMode();
        } else {
            disableBulkMode();
        }
    }

    function enableBulkMode() {
        // Update button
        $('.powerpack-bulk-toggle-btn').addClass('active');

        // Add bulk class to container
        const $container = cur_pos.item_selector.$items_container;
        $container.addClass('powerpack-bulk-mode');

        // Inject checkboxes
        injectBulkCheckboxes();

        // Show bulk action bar
        showBulkActionBar();

        // Disable keyboard nav
        disableKeyboardNavigation();

        frappe.show_alert({
            message: __('Bulk mode activated. Select items to add.'),
            indicator: 'blue'
        }, 3);
    }

    function disableBulkMode() {
        $('.powerpack-bulk-toggle-btn').removeClass('active');

        const $container = cur_pos.item_selector.$items_container;
        $container.removeClass('powerpack-bulk-mode');

        // Remove checkboxes
        $('.bulk-checkbox-wrapper').remove();

        // Hide action bar
        $('.powerpack-bulk-action-bar').remove();

        // Clear selections
        bulkSelections = {};

        // Re-enable keyboard nav if in compact view
        if (currentViewMode === 'compact') {
            enableKeyboardNavigation();
        }
    }

    function injectBulkCheckboxes() {
        $('.powerpack-compact-item').each(function() {
            const $item = $(this);
            const itemCode = unescape($item.attr('data-item-code'));

            const checkboxHtml = `
                <div class="bulk-checkbox-wrapper">
                    <input type="checkbox" class="bulk-item-checkbox"
                           data-item-code="${itemCode}"
                           ${bulkSelections[itemCode] ? 'checked' : ''}>
                </div>
            `;

            $item.prepend(checkboxHtml);
        });

        // Bind checkbox events
        $('.bulk-item-checkbox').on('change', function() {
            const itemCode = $(this).data('item-code');
            handleBulkCheckboxChange(itemCode, $(this).is(':checked'));
        });
    }

    function handleBulkCheckboxChange(itemCode, isChecked) {
        if (isChecked) {
            // Prompt for quantity
            frappe.prompt({
                label: __('Quantity'),
                fieldname: 'qty',
                fieldtype: 'Int',
                default: 1,
                reqd: 1
            }, (values) => {
                if (values.qty > 0) {
                    bulkSelections[itemCode] = values.qty;
                    updateBulkCounter();
                } else {
                    // Uncheck if invalid
                    $(`.bulk-item-checkbox[data-item-code="${itemCode}"]`).prop('checked', false);
                }
            }, __('Set Quantity'));
        } else {
            // Remove from selections
            delete bulkSelections[itemCode];
            updateBulkCounter();
        }
    }

    function showBulkActionBar() {
        const barHtml = `
            <div class="powerpack-bulk-action-bar">
                <div class="bulk-counter">
                    <span class="bulk-count">0</span> ${__('items selected')}
                </div>
                <div class="bulk-actions">
                    <button class="btn btn-default btn-sm bulk-clear-btn">
                        ${__('Clear All')}
                    </button>
                    <button class="btn btn-primary btn-sm bulk-add-btn">
                        <i class="fa fa-shopping-cart"></i> ${__('Add All to Cart')}
                    </button>
                </div>
            </div>
        `;

        $('.pos-view').append(barHtml);

        // Bind actions
        $('.bulk-clear-btn').on('click', clearBulkSelections);
        $('.bulk-add-btn').on('click', bulkAddToCart);
    }

    function updateBulkCounter() {
        const count = Object.keys(bulkSelections).length;
        $('.bulk-count').text(count);

        if (count > 0) {
            $('.bulk-add-btn').prop('disabled', false);
        } else {
            $('.bulk-add-btn').prop('disabled', true);
        }
    }

    function clearBulkSelections() {
        bulkSelections = {};
        $('.bulk-item-checkbox').prop('checked', false);
        updateBulkCounter();
    }

    function bulkAddToCart() {
        const itemCount = Object.keys(bulkSelections).length;

        if (itemCount === 0) {
            frappe.show_alert({
                message: __('No items selected'),
                indicator: 'orange'
            }, 3);
            return;
        }

        // Add each item to cart
        let addedCount = 0;
        for (const [itemCode, qty] of Object.entries(bulkSelections)) {
            const $item = $(`.powerpack-compact-item[data-item-code="${itemCode}"]`);

            if ($item.length > 0) {
                cur_pos.item_selector.events.item_selected({
                    field: 'qty',
                    value: qty,
                    item: {
                        item_code: itemCode,
                        batch_no: unescape($item.attr('data-batch-no')),
                        serial_no: unescape($item.attr('data-serial-no')),
                        uom: unescape($item.attr('data-uom')),
                        rate: unescape($item.attr('data-rate')),
                        stock_uom: unescape($item.attr('data-stock-uom'))
                    }
                });
                addedCount++;
            }
        }

        // Show success
        frappe.show_alert({
            message: __('{0} items added to cart', [addedCount]),
            indicator: 'green'
        }, 3);

        // Clear and exit bulk mode
        clearBulkSelections();
        disableBulkMode();
    }

    function enhanceSearchLogic() {
        // Store original get_items method
        originalGetItems = cur_pos.item_selector.get_items.bind(cur_pos.item_selector);

        // Override get_items to implement enhanced search
        cur_pos.item_selector.get_items = function(opts = {}) {
            const search_term = (opts.search_term || '').trim();

            // If no search term, use original method
            if (!search_term) {
                return originalGetItems(opts);
            }

            // Apply enhanced search with scoring
            return originalGetItems({ search_term: '' }).then(({ message }) => {
                const allItems = message.items || [];
                const filteredItems = getSortedFilteredData(allItems, search_term);

                return {
                    message: {
                        items: filteredItems,
                        serial_no: message.serial_no,
                        batch_no: message.batch_no,
                        barcode: message.barcode
                    }
                };
            });
        };
    }

    function getSortedFilteredData(items, search_term) {
        if (!search_term) return items;

        const search_lower = search_term.toLowerCase();
        const tokens = search_lower.split(/\s+/).filter(t => t.length > 0);

        // Check if using wildcard pattern (%)
        const hasWildcard = search_term.includes('%');

        let scoredItems;

        if (hasWildcard) {
            // Wildcard search using regex
            const pattern = search_lower
                .split('%')
                .map(s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
                .join('.*');
            const regex = new RegExp(pattern, 'i');

            scoredItems = items.map(item => {
                const item_code_lower = (item.item_code || '').toLowerCase();
                const item_name_lower = (item.item_name || '').toLowerCase();
                const combined = item_code_lower + ' ' + item_name_lower;

                let score = 0;

                if (regex.test(combined)) {
                    score += 10;

                    // Boost for item_code match
                    if (regex.test(item_code_lower)) {
                        score += 30;
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
            // Token-based fuzzy search (always enabled)
            scoredItems = items.map(item => {
                const item_code = (item.item_code || '').toLowerCase();
                const item_name = (item.item_name || '').toLowerCase();
                const combined = item_code + ' ' + item_name;

                let score = 0;

                // Exact match gets highest priority
                if (item_code === search_lower || item_name === search_lower) {
                    score += 1000;
                }

                // Starts with search term
                if (item_code.startsWith(search_lower)) {
                    score += 500;
                } else if (item_name.startsWith(search_lower)) {
                    score += 400;
                }

                // Contains search term
                if (item_code.includes(search_lower)) {
                    score += 200;
                } else if (item_name.includes(search_lower)) {
                    score += 100;
                }

                // Token-based matching for multi-word searches
                let tokensMatched = 0;
                tokens.forEach(token => {
                    if (item_code.includes(token)) {
                        score += 50;
                        tokensMatched++;
                    }
                    if (item_name.includes(token)) {
                        score += 30;
                        tokensMatched++;
                    }
                });

                // Bonus for matching all tokens
                if (tokensMatched === tokens.length * 2) {
                    score += 150;
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
