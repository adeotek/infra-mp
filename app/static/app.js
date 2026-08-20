/* InfraMP UI behaviours: theme switching, sidebar collapse, user menu, modal. */
(function () {
  'use strict';

  var THEME_KEY = 'inframp-theme';
  var SIDEBAR_KEY = 'inframp-sidebar';
  var UI_STATE_KEY = 'inframp-ui-state';
  var MAX_GRID_ENTRIES = 60;

  // --------------------------------------------------------------------------
  // UI state: one JSON blob in localStorage, parsed once (the <head> script
  // stashes it on window to avoid a second parse). Holds the menu section
  // toggles and per-grid sort/filter state. Writes are debounced; the grid
  // map is bounded so it cannot grow without limit.
  // --------------------------------------------------------------------------
  var uiState = window.__inframpUIState || (function () {
    try { return JSON.parse(localStorage.getItem(UI_STATE_KEY) || 'null') || {}; } catch (e) { return {}; }
  })();
  if (!uiState.sections) uiState.sections = {};
  if (!uiState.grids) uiState.grids = {};
  var uiSaveTimer = null;

  function saveUIState() {
    if (uiSaveTimer) return;
    uiSaveTimer = setTimeout(function () {
      uiSaveTimer = null;
      try { localStorage.setItem(UI_STATE_KEY, JSON.stringify(uiState)); } catch (e) { /* ignore */ }
    }, 200);
  }

  function gridStateFor(key) {
    return (uiState.grids && uiState.grids[key]) || null;
  }

  function updateGridState(key, patch) {
    var entry = uiState.grids[key] || {};
    var k;
    for (k in patch) {
      if (patch[k] === null || patch[k] === undefined) delete entry[k];
      else entry[k] = patch[k];
    }
    var hasKeys = false;
    for (k in entry) { hasKeys = true; break; }
    if (!hasKeys) {
      delete uiState.grids[key];
    } else {
      uiState.grids[key] = entry;
      var keys = Object.keys(uiState.grids);
      while (keys.length > MAX_GRID_ENTRIES) delete uiState.grids[keys.shift()];
    }
    saveUIState();
  }

  // Theme toggle (dark is the default, applied early in <head>).
  var themeToggle = document.getElementById('theme-toggle');
  if (themeToggle) {
    themeToggle.addEventListener('click', function () {
      var current = document.documentElement.getAttribute('data-theme') || 'dark';
      var next = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* ignore */ }
    });
  }

  // Sidebar collapse toggle. The button's tooltip/aria-label reflect the action
  // it will perform (collapse vs expand), synced with any persisted state.
  var sidebarToggle = document.getElementById('sidebar-toggle');
  if (sidebarToggle) {
    var updateToggleLabel = function () {
      var collapsed = document.documentElement.classList.contains('sidebar-collapsed');
      var label = collapsed ? 'Expand menu' : 'Collapse menu';
      sidebarToggle.setAttribute('title', label);
      sidebarToggle.setAttribute('aria-label', label);
    };
    updateToggleLabel();
    sidebarToggle.addEventListener('click', function () {
      var collapsed = document.documentElement.classList.toggle('sidebar-collapsed');
      try { localStorage.setItem(SIDEBAR_KEY, collapsed ? 'collapsed' : 'expanded'); } catch (e) { /* ignore */ }
      updateToggleLabel();
      closeAllOverlays();
    });
  }

  // Sidebar section collapse: clicking a level-1 section title toggles its
  // child items (expanded sidebar). State persists in the UI blob; the
  // collapse itself is applied via html-level classes from the <head> script.
  document.querySelectorAll('.nav-section-title[data-section]').forEach(function (title) {
    var key = title.getAttribute('data-section');
    var htmlClass = 'sect-' + key + '-collapsed';

    function syncAria() {
      title.setAttribute(
        'aria-expanded',
        document.documentElement.classList.contains(htmlClass) ? 'false' : 'true'
      );
    }
    syncAria();

    function toggleSection() {
      var collapsed = document.documentElement.classList.toggle(htmlClass);
      uiState.sections[key] = !collapsed;
      saveUIState();
      syncAria();
    }

    title.addEventListener('click', toggleSection);
    title.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        toggleSection();
      }
    });
  });

  // Collapsed sidebar: overlay menus for the level-1 sections. The overlays
  // are position:fixed so they escape the scrollable .side-nav clipping
  // context; coordinates are computed from the hovered section on open.
  function openSectionOverlay(section) {
    var overlay = section.querySelector('.nav-section-items');
    if (!overlay || section.classList.contains('overlay-open')) return;
    section.classList.add('overlay-open');
    var rect = section.getBoundingClientRect();
    overlay.style.left = rect.right + 'px';
    var top = Math.min(rect.top, window.innerHeight - overlay.offsetHeight - 12);
    overlay.style.top = Math.max(top, 8) + 'px';
  }

  function closeAllOverlays() {
    document.querySelectorAll('.nav-section.overlay-open').forEach(function (section) {
      section.classList.remove('overlay-open');
    });
  }

  document.addEventListener('mouseover', function (e) {
    var section = e.target.closest('.sidebar-collapsed .nav-section');
    if (section) openSectionOverlay(section);
  });
  document.addEventListener('mouseout', function (e) {
    var section = e.target.closest('.sidebar-collapsed .nav-section');
    if (!section) return;
    if (section.contains(e.relatedTarget)) return;
    section.classList.remove('overlay-open');
  });

  // User menu dropdown.
  var userMenu = document.getElementById('user-menu');
  var userMenuBtn = document.getElementById('user-menu-btn');
  if (userMenu && userMenuBtn) {
    userMenuBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      userMenu.classList.toggle('open');
    });
    document.addEventListener('click', function (e) {
      if (!userMenu.contains(e.target)) userMenu.classList.remove('open');
      if (e.target.closest('.dropdown-item')) userMenu.classList.remove('open');
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') userMenu.classList.remove('open');
    });
  }

  // Confirmation dialog: forms marked data-confirm open an in-page modal
  // instead of the browser's confirm(). Cancel/Esc aborts; Confirm submits.
  var confirmDialog = document.getElementById('confirm-dialog');
  if (confirmDialog) {
    var confirmMessage = document.getElementById('confirm-message');
    var confirmOk = document.getElementById('confirm-ok');
    var confirmCancel = document.getElementById('confirm-cancel');
    var confirmClose = document.getElementById('confirm-close');
    var pendingConfirmForm = null;

    function closeConfirm() {
      pendingConfirmForm = null;
      confirmDialog.close();
    }

    document.body.addEventListener('submit', function (e) {
      var form = e.target.closest('form[data-confirm]');
      if (!form) return;
      e.preventDefault();
      pendingConfirmForm = form;
      confirmMessage.textContent = form.getAttribute('data-confirm');
      confirmDialog.showModal();
      if (confirmCancel) confirmCancel.focus();
    });

    confirmOk.addEventListener('click', function () {
      var form = pendingConfirmForm;
      pendingConfirmForm = null;
      confirmDialog.close();
      // Programmatic submit does not re-fire the submit event, so the
      // interceptor above cannot loop.
      if (form) form.submit();
    });
    if (confirmCancel) confirmCancel.addEventListener('click', closeConfirm);
    if (confirmClose) confirmClose.addEventListener('click', closeConfirm);
    confirmDialog.addEventListener('cancel', function () {
      // Esc closes the dialog without submitting anything.
      pendingConfirmForm = null;
    });
  }

  // Modal dialog: opens when HTMX swaps a form fragment into #modal-body.
  var modal = document.getElementById('modal');
  if (modal) {
    var modalBody = document.getElementById('modal-body');

    document.body.addEventListener('htmx:afterSwap', function (e) {
      if (e.detail.target && e.detail.target.id === 'modal-body' && !modal.open) {
        modal.showModal();
      }
    });

    var closeBtn = document.getElementById('modal-close');
    if (closeBtn) closeBtn.addEventListener('click', function () { modal.close(); });

    // Keep the modal open on Escape (and any native cancel request).
    modal.addEventListener('cancel', function (e) {
      e.preventDefault();
    });

    // Any element marked data-modal-close (e.g. a Cancel link) closes the modal;
    // on a full page with no open modal it behaves like a normal link/button.
    document.body.addEventListener('click', function (e) {
      var el = e.target.closest('[data-modal-close]');
      if (el && modal.open) {
        e.preventDefault();
        modal.close();
      }
    });

    // Clear the body on close so stale content doesn't flash on the next open.
    modal.addEventListener('close', function () {
      if (modalBody) modalBody.innerHTML = '';
    });
  }

  // Drag-and-drop row reordering (any table with data-reorder-url: entity
  // attributes, dashboard widgets). Rows are reordered live on dragover; the
  // final order is persisted on dragend via fetch.
  function initReorderTable(table) {
    var dragRow = null;
    var reorderUrl = table.getAttribute('data-reorder-url');

    table.addEventListener('dragstart', function (e) {
      var tr = e.target.closest('tr[draggable]');
      if (!tr) return;
      dragRow = tr;
      tr.classList.add('dragging');
      if (e.dataTransfer) {
        e.dataTransfer.effectAllowed = 'move';
        // Required by Firefox to start the drag.
        e.dataTransfer.setData('text/plain', tr.getAttribute('data-id'));
      }
    });

    table.addEventListener('dragover', function (e) {
      if (!dragRow) return;
      e.preventDefault();
      var tr = e.target.closest('tr[draggable]');
      if (!tr || tr === dragRow) return;
      var rect = tr.getBoundingClientRect();
      var after = (e.clientY - rect.top) > (rect.height / 2);
      if (after) {
        tr.insertAdjacentElement('afterend', dragRow);
      } else {
        tr.insertAdjacentElement('beforebegin', dragRow);
      }
    });

    table.addEventListener('drop', function (e) { e.preventDefault(); });

    table.addEventListener('dragend', function () {
      if (!dragRow) return;
      dragRow.classList.remove('dragging');
      var rows = table.querySelectorAll('tr[draggable]');
      var ids = Array.prototype.map.call(
        rows,
        function (tr) { return tr.getAttribute('data-id'); }
      );
      // Keep the sortable "restore original order" index in sync with the
      // newly persisted order.
      Array.prototype.forEach.call(rows, function (tr, index) {
        tr.setAttribute('data-sort-index', String(index));
      });
      dragRow = null;
      if (!reorderUrl) return;
      fetch(reorderUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 'order=' + encodeURIComponent(ids.join(','))
      }).then(function (resp) {
        if (!resp.ok) window.location.reload();
      });
    });
  }

  document.querySelectorAll('table[data-reorder-url]').forEach(initReorderTable);

  // Sortable tables: clicking a header cycles None -> Ascending -> Descending
  // -> None. Icons in the header show the active state. Headers marked
  // "no-sort" (actions / drag-handle columns) are skipped.
  function sortKey(text) {
    var t = String(text == null ? '' : text).trim().replace(/\s+/g, ' ');
    var m = t.match(/^(-?[\d][\d.,]*)(.*)$/);
    if (m) {
      var num = parseFloat(m[1].replace(/,/g, ''));
      if (!isNaN(num) && (m[2] === '' || /^\s*\D/.test(m[2]))) {
        return { num: num, text: t.toLowerCase() };
      }
    }
    return { num: null, text: t.toLowerCase() };
  }

  function initSortableTable(table) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var gridKey = table.getAttribute('data-grid-key') || null;
    var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
    // The initial DOM order is the "None" state.
    rows.forEach(function (tr, index) {
      tr.setAttribute('data-sort-index', String(index));
    });
    var headers = Array.prototype.slice.call(table.querySelectorAll('thead th'));

    function moveRows(comparator) {
      rows.slice().sort(comparator).forEach(function (tr) {
        tbody.appendChild(tr);
      });
    }

    function resetHeaders() {
      headers.forEach(function (h) {
        h.classList.remove('sorted-asc', 'sorted-desc');
        h.removeAttribute('aria-sort');
        var icon = h.querySelector('.sort-indicator i');
        if (icon) icon.className = 'fa-solid fa-sort';
      });
    }

    function comparatorFor(th, direction) {
      var column = Array.prototype.indexOf.call(th.parentNode.children, th);
      return function (a, b) {
        var ka = sortKey(a.children[column] ? a.children[column].textContent : '');
        var kb = sortKey(b.children[column] ? b.children[column].textContent : '');
        var cmp;
        if (ka.num !== null && kb.num !== null && ka.num !== kb.num) {
          cmp = ka.num - kb.num;
        } else {
          cmp = ka.text < kb.text ? -1 : ka.text > kb.text ? 1 : 0;
        }
        if (cmp === 0) {
          var ia = parseInt(a.getAttribute('data-sort-index'), 10);
          var ib = parseInt(b.getAttribute('data-sort-index'), 10);
          cmp = ia - ib;
        }
        return direction === 'desc' ? -cmp : cmp;
      };
    }

    function applySort(th, direction) {
      resetHeaders();
      if (direction === 'none') {
        moveRows(function (a, b) {
          var ia = parseInt(a.getAttribute('data-sort-index'), 10);
          var ib = parseInt(b.getAttribute('data-sort-index'), 10);
          return ia - ib;
        });
        return;
      }
      th.classList.add(direction === 'asc' ? 'sorted-asc' : 'sorted-desc');
      th.setAttribute('aria-sort', direction === 'asc' ? 'ascending' : 'descending');
      var icon = th.querySelector('.sort-indicator i');
      if (icon) {
        icon.className = 'fa-solid ' + (direction === 'asc' ? 'fa-sort-up' : 'fa-sort-down');
      }
      moveRows(comparatorFor(th, direction));
    }

    headers.forEach(function (th) {
      if (th.classList.contains('no-sort')) return;
      th.classList.add('sortable');
      var indicator = document.createElement('span');
      indicator.className = 'sort-indicator';
      indicator.innerHTML = '<i class="fa-solid fa-sort" aria-hidden="true"></i>';
      th.appendChild(indicator);

      th.addEventListener('click', function () {
        var direction;
        if (th.classList.contains('sorted-asc')) {
          direction = 'desc';
        } else if (th.classList.contains('sorted-desc')) {
          direction = 'none';
        } else {
          direction = 'asc';
        }
        applySort(th, direction);
        if (gridKey) {
          updateGridState(
            gridKey,
            direction === 'none'
              ? { label: null, dir: null }
              : { label: th.textContent.trim(), dir: direction }
          );
        }
      });
    });

    // Restore the persisted sort for this grid (read once on page load).
    if (gridKey) {
      var saved = gridStateFor(gridKey);
      if (saved && saved.label && (saved.dir === 'asc' || saved.dir === 'desc')) {
        for (var i = 0; i < headers.length; i++) {
          if (headers[i].textContent.trim() === saved.label) {
            applySort(headers[i], saved.dir);
            break;
          }
        }
      }
    }
  }

  document.querySelectorAll('table[data-sortable]').forEach(initSortableTable);

  // Drag & drop upload zones (CSV import modal + backup restore). Delegated
  // so zones also initialize after HTMX swaps a fragment into the modal.
  var DROP_ACCEPTS = {
    csv: { pattern: /\.csv$/i, mime: 'text/csv', label: 'Only CSV files are supported' },
    zip: { pattern: /\.zip$/i, mime: 'application/zip', label: 'Only ZIP files are supported' }
  };

  function initDropZone(zone) {
    if (!zone || zone.dataset.dzInit) return;
    zone.dataset.dzInit = '1';
    var spec = DROP_ACCEPTS[zone.dataset.accept || 'csv'] || DROP_ACCEPTS.csv;
    var input = document.getElementById(zone.dataset.input || 'import-file');
    var title = document.getElementById(zone.dataset.title || 'drop-zone-title');
    if (!input || !title) return;

    function showFile(name) {
      title.textContent = name;
      zone.classList.add('has-file');
      zone.classList.remove('dz-error');
    }
    function setFiles(files) {
      if (!files || !files.length) return;
      var file = files[0];
      if (!spec.pattern.test(file.name) && file.type !== spec.mime) {
        zone.classList.remove('drag-over', 'has-file');
        zone.classList.add('dz-error');
        title.textContent = spec.label;
        input.value = '';
        return;
      }
      var dt = new DataTransfer();
      dt.items.add(file);
      input.files = dt.files;
      showFile(file.name);
    }

    zone.addEventListener('click', function () { input.click(); });
    input.addEventListener('change', function () { setFiles(input.files); });
    ['dragenter', 'dragover'].forEach(function (eventName) {
      zone.addEventListener(eventName, function (e) {
        e.preventDefault();
        zone.classList.add('drag-over');
      });
    });
    ['dragleave', 'drop'].forEach(function (eventName) {
      zone.addEventListener(eventName, function (e) {
        e.preventDefault();
        zone.classList.remove('drag-over');
      });
    });
    zone.addEventListener('drop', function (e) {
      setFiles(e.dataTransfer && e.dataTransfer.files);
    });
  }

  document.querySelectorAll('.drop-zone').forEach(initDropZone);
  document.body.addEventListener('htmx:afterSwap', function (e) {
    var target = e.detail && e.detail.target;
    if (target && target.id === 'modal-body') {
      target.querySelectorAll('.drop-zone').forEach(initDropZone);
    }
    if (target && target.id === 'view-detail-body') {
      initAdvancedFilter(target);
    }
  });

  // Advanced filter builder (view detail): the column select drives the
  // comparison options and the value widget, based on the column type.
  var OP_LABELS = {
    eq: 'equals',
    neq: 'does not equal',
    contains: 'contains',
    not_contains: 'does not contain',
    gt: 'greater than',
    gte: 'greater or equal',
    lt: 'less than',
    lte: 'less or equal'
  };
  var OPS_BY_TYPE = {
    text: ['eq', 'neq', 'contains', 'not_contains'],
    integer: ['eq', 'neq', 'gt', 'gte', 'lt', 'lte'],
    float: ['eq', 'neq', 'gt', 'gte', 'lt', 'lte'],
    date: ['eq', 'neq', 'gt', 'gte', 'lt', 'lte'],
    datetime: ['eq', 'neq', 'gt', 'gte', 'lt', 'lte'],
    boolean: ['eq', 'neq'],
    enum: ['eq', 'neq'],
    reference: ['eq', 'neq', 'contains', 'not_contains']
  };

  function initAdvancedFilter(scope) {
    var col = scope.querySelector('#af-col');
    var op = scope.querySelector('#af-op');
    var value = scope.querySelector('#af-value');
    if (!col || !op || !value) return;

    function rebuild() {
      var selected = col.options[col.selectedIndex];
      var type = selected ? (selected.getAttribute('data-type') || 'text') : 'text';
      var isQuick = col.value === 'quick';
      var many = selected && selected.getAttribute('data-many') === '1';

      if (isQuick) {
        op.style.display = 'none';
      } else {
        var ops = OPS_BY_TYPE[type] || OPS_BY_TYPE.text;
        if (type === 'reference' && many) ops = ['contains', 'not_contains'];
        op.innerHTML = '';
        ops.forEach(function (o) {
          var el = document.createElement('option');
          el.value = o;
          el.textContent = OP_LABELS[o] || o;
          op.appendChild(el);
        });
        op.style.display = '';
      }

      var next;
      if (type === 'boolean') {
        next = document.createElement('select');
        [['true', 'Yes'], ['false', 'No']].forEach(function (pair) {
          var el = document.createElement('option');
          el.value = pair[0];
          el.textContent = pair[1];
          next.appendChild(el);
        });
      } else if (type === 'enum') {
        next = document.createElement('select');
        var choices = [];
        try { choices = JSON.parse(selected.getAttribute('data-choices') || '[]'); } catch (e) {}
        choices.forEach(function (c) {
          var el = document.createElement('option');
          el.value = c;
          el.textContent = c;
          next.appendChild(el);
        });
      } else {
        next = document.createElement('input');
        if (type === 'integer' || type === 'float') next.type = 'number';
        else if (type === 'date') next.type = 'date';
        else next.type = 'text';
        next.placeholder = 'filter value';
      }
      next.name = 'value';
      next.id = 'af-value';
      next.autocomplete = 'off';
      value.replaceWith(next);
      value = next;
    }

    col.addEventListener('change', rebuild);
    rebuild();
  }
  initAdvancedFilter(document);

  // Quick search: client-side row filter (records pages). A row matches when
  // any of its cells contains the term (case-insensitive). Works alongside
  // column sorting: hidden rows stay hidden through re-sorts.
  document.querySelectorAll('.quick-search[data-filter-table]').forEach(function (box) {
    var table = document.getElementById(box.getAttribute('data-filter-table'));
    if (!table) return;
    var gridKey = table.getAttribute('data-grid-key') || null;
    var input = box.querySelector('input[type="text"]');
    var applyBtn = box.querySelector('[data-apply]');
    var clearBtn = box.querySelector('[data-clear]');
    var countEl = box.querySelector('.quick-search-count');
    var rows = table.querySelectorAll('tbody tr');

    function applyFilter() {
      var term = (input ? input.value : '').trim().toLowerCase();
      var shown = 0;
      rows.forEach(function (tr) {
        var match = !term || tr.textContent.toLowerCase().indexOf(term) !== -1;
        tr.hidden = !match;
        if (match) shown += 1;
      });
      if (countEl) countEl.textContent = term ? shown + ' of ' + rows.length + ' shown' : '';
      if (clearBtn) clearBtn.classList.toggle('hidden', !term);
      if (gridKey) updateGridState(gridKey, { filter: term || null });
    }

    if (applyBtn) applyBtn.addEventListener('click', applyFilter);
    if (clearBtn) {
      clearBtn.addEventListener('click', function () {
        if (input) input.value = '';
        applyFilter();
      });
    }
    if (input) {
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          applyFilter();
        }
      });
    }

    // Restore the persisted filter (read once on page load).
    if (gridKey) {
      var saved = gridStateFor(gridKey);
      if (saved && saved.filter) {
        if (input) input.value = saved.filter;
        applyFilter();
      }
    }
  });

  // Multi-value reference field: single select + "Add" + removable chip list.
  function appendRefChip(wrap, value, label) {
    var ul = wrap.querySelector('.multi-ref-list');
    var li = document.createElement('li');
    li.className = 'chip';
    var span = document.createElement('span');
    span.className = 'chip-label';
    span.textContent = label;
    var input = document.createElement('input');
    input.type = 'hidden';
    input.name = wrap.getAttribute('data-field');
    input.value = value;
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'chip-remove';
    btn.setAttribute('data-remove', '');
    btn.setAttribute('aria-label', 'Remove');
    btn.textContent = '\u00d7';
    li.appendChild(span);
    li.appendChild(input);
    li.appendChild(btn);
    ul.appendChild(li);
  }

  function sortRefOptions(select) {
    var options = Array.prototype.slice.call(select.options)
      .filter(function (o) { return o.value !== ''; })
      .sort(function (a, b) { return a.textContent.localeCompare(b.textContent); });
    options.forEach(function (o) { select.add(o); });
  }

  document.body.addEventListener('click', function (e) {
    var addBtn = e.target.closest('[data-add]');
    if (addBtn) {
      var wrap = addBtn.closest('.multi-ref');
      var select = wrap.querySelector('[data-source]');
      var opt = select.options[select.selectedIndex];
      if (opt && opt.value) {
        appendRefChip(wrap, opt.value, opt.textContent);
        opt.remove();
      }
      return;
    }
    var removeBtn = e.target.closest('[data-remove]');
    if (removeBtn) {
      var wrap = removeBtn.closest('.multi-ref');
      var chip = removeBtn.closest('.chip');
      var select = wrap.querySelector('[data-source]');
      var option = document.createElement('option');
      option.value = chip.querySelector('input[type="hidden"]').value;
      option.textContent = chip.querySelector('.chip-label').textContent;
      select.add(option);
      sortRefOptions(select);
      chip.remove();
    }
  });
})();
