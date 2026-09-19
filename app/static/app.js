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

  // Transient toast (bottom-right); variant: '' | 'success' | 'error'.
  function showToast(message, variant) {
    var toast = document.getElementById('toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'toast';
      toast.className = 'toast';
      toast.setAttribute('role', 'status');
      document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.className = 'toast' + (variant ? ' toast-' + variant : '');
    toast.classList.add('show');
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(function () {
      toast.classList.remove('show');
    }, 4000);
  }

  function csrfHeader() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : '';
  }

  // Every HTMX request carries the CSRF token header (fragments have no
  // <head>, so the token comes from the hosting document's meta tag).
  document.body.addEventListener('htmx:configRequest', function (e) {
    var token = csrfHeader();
    if (token) e.detail.headers['X-CSRF-Token'] = token;
  });

  // Modal/entity forms return 400 + error fragments; htmx 2 discards 4xx
  // responses by default, which made validation errors invisible. Allow
  // 4xx swaps into fragment targets.
  document.body.addEventListener('htmx:beforeSwap', function (e) {
    if (e.detail.xhr && e.detail.xhr.status >= 400 && e.detail.xhr.status < 500) {
      e.detail.shouldSwap = true;
    }
  });

  // 5xx responses are not swapped; surface them instead of failing silently.
  document.body.addEventListener('htmx:responseError', function () {
    showToast('Something went wrong. Please try again.');
  });

  // Global busy indicator: a progress hairline under the topbar.
  var busyCount = 0;
  document.body.addEventListener('htmx:beforeRequest', function () {
    busyCount += 1;
    document.body.classList.add('htmx-busy');
  });
  document.body.addEventListener('htmx:afterRequest', function () {
    busyCount = Math.max(0, busyCount - 1);
    if (!busyCount) document.body.classList.remove('htmx-busy');
  });

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
      // The double-arrow points at the direction the sidebar will move:
      // right when collapsed (expand back), left when expanded (collapse).
      var icon = sidebarToggle.querySelector('i');
      if (icon) {
        icon.className = collapsed ? 'fa-solid fa-angles-right' : 'fa-solid fa-angles-left';
      }
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
    function setMenuOpen(open) {
      userMenu.classList.toggle('open', open);
      userMenuBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    }
    userMenuBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      setMenuOpen(!userMenu.classList.contains('open'));
    });
    document.addEventListener('click', function (e) {
      if (!userMenu.contains(e.target)) setMenuOpen(false);
      if (e.target.closest('.dropdown-item')) setMenuOpen(false);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') setMenuOpen(false);
    });
    // Arrow-key navigation inside the menu (role="menu").
    userMenu.addEventListener('keydown', function (e) {
      if (!userMenu.classList.contains('open')) return;
      var items = Array.prototype.filter.call(
        userMenu.querySelectorAll('[role="menuitem"]'),
        function (el) { return !el.disabled; }
      );
      if (!items.length) return;
      var index = items.indexOf(document.activeElement);
      var next = null;
      if (e.key === 'ArrowDown') next = items[(index + 1) % items.length];
      else if (e.key === 'ArrowUp') next = items[(index - 1 + items.length) % items.length];
      else if (e.key === 'Home') next = items[0];
      else if (e.key === 'End') next = items[items.length - 1];
      else if (e.key === 'Tab') setMenuOpen(false);
      if (next) {
        e.preventDefault();
        next.focus();
      }
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
      // Point the dialog's accessible name at the fragment's heading.
      if (e.detail.target && e.detail.target.id === 'modal-body') {
        var heading = modalBody.querySelector('h1');
        if (heading) {
          if (!heading.id) heading.id = 'modal-title';
          modal.setAttribute('aria-labelledby', 'modal-title');
        } else {
          modal.removeAttribute('aria-labelledby');
        }
      }
    });

    var closeBtn = document.getElementById('modal-close');
    if (closeBtn) closeBtn.addEventListener('click', function () { modal.close(); });

    // Escape closes the modal (native cancel).

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
  // final order is persisted on dragend via fetch. ▲/▼ buttons in the handle
  // column provide a keyboard-accessible alternative.
  function postReorder(table, ids) {
    var reorderUrl = table.getAttribute('data-reorder-url');
    if (!reorderUrl) return;
    fetch(reorderUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-CSRF-Token': csrfHeader()
      },
      body: 'order=' + encodeURIComponent(ids.join(','))
    }).then(function (resp) {
      if (!resp.ok) {
        showToast('Reordering failed — the previous order was restored.');
        // Restore the DOM to the data-sort-index order.
        var rows = Array.prototype.slice.call(table.querySelectorAll('tr[draggable]'));
        rows.sort(function (a, b) {
          return parseInt(a.getAttribute('data-sort-index'), 10)
            - parseInt(b.getAttribute('data-sort-index'), 10);
        });
        rows.forEach(function (tr) { tr.parentNode.appendChild(tr); });
      }
    });
  }

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
      postReorder(table, ids);
    });

    // Keyboard reordering: ▲/▼ buttons move a row one position and persist.
    table.addEventListener('click', function (e) {
      var btn = e.target.closest('.row-move');
      if (!btn) return;
      var tr = btn.closest('tr[draggable]');
      if (!tr) return;
      var sibling = btn.getAttribute('data-move') === 'up'
        ? tr.previousElementSibling
        : tr.nextElementSibling;
      if (!sibling || !sibling.hasAttribute('draggable')) return;
      if (btn.getAttribute('data-move') === 'up') {
        tr.parentNode.insertBefore(tr, sibling);
      } else {
        tr.parentNode.insertBefore(sibling, tr);
      }
      var rows = table.querySelectorAll('tr[draggable]');
      var ids = Array.prototype.map.call(rows, function (r) { return r.getAttribute('data-id'); });
      postReorder(table, ids);
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
      th.setAttribute('tabindex', '0');
      th.setAttribute('role', 'button');
      var indicator = document.createElement('span');
      indicator.className = 'sort-indicator';
      indicator.innerHTML = '<i class="fa-solid fa-sort" aria-hidden="true"></i>';
      th.appendChild(indicator);

      function toggleSort() {
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
      }

      th.addEventListener('click', toggleSort);
      // Keyboard: Enter/Space cycles like the mouse.
      th.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          toggleSort();
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

  // Copy-to-clipboard buttons (attributes with "With copy button" + record
  // form fields). Source: the enclosing control (.field-copy) or the cell's
  // value span (.cell-value) in grids.
  function fallbackCopy(text, done) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
      done();
    } catch (e) {
      /* clipboard unavailable — stay quiet */
    }
    document.body.removeChild(ta);
  }

  // Form-field copy buttons are rendered hidden while the field is empty (there
  // is nothing to copy) and revealed as soon as the control holds a value, so a
  // new record's button appears while typing instead of only after a reload.
  function syncFieldCopy(control) {
    var wrap = control.closest('.field-copy');
    if (!wrap) return;
    var btn = wrap.querySelector('.copy-btn');
    if (btn) btn.classList.toggle('hidden', control.value.trim() === '');
  }
  ['input', 'change'].forEach(function (type) {
    document.body.addEventListener(type, function (e) {
      var el = e.target;
      if (!el || !el.matches || !el.matches('input, textarea, select')) return;
      if (el.closest('.field-copy')) syncFieldCopy(el);
    });
  });

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.copy-btn');
    if (!btn) return;
    var wrap = btn.closest('.field-copy');
    var text = '';
    if (wrap) {
      var ctl = wrap.querySelector('input, textarea, select');
      text = ctl ? ctl.value : '';
    } else {
      var cell = btn.closest('td');
      var val = cell && cell.querySelector('.cell-value');
      text = val ? val.textContent.trim() : '';
    }
    if (!text) return;
    var notify = function () {
      showToast('Value copied to clipboard', 'success');
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(notify, function () {
        fallbackCopy(text, notify);
      });
    } else {
      fallbackCopy(text, notify);
    }
  });

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

    // The zone is a <label for="file-input">: the native picker opens without
    // JS, so no click handler here (a JS click would open the dialog twice).
    // Enter/Space emulate the label click for keyboard users.
    zone.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        input.click();
      }
    });
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
  });
  // The view body re-inits on afterSettle, NOT afterSwap: htmx's settle phase
  // (~20ms after the swap) reconciles attributes between swapped elements
  // with matching ids, stripping inline styles set during afterSwap.
  document.body.addEventListener('htmx:afterSettle', function (e) {
    var target = e.detail && e.detail.target;
    if (target && target.id === 'view-detail-body') {
      target.querySelectorAll('table[data-sortable]').forEach(initSortableTable);
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

  // Dashboard widget form: the sum-field select lists the numeric attributes
  // of the selected entity (the entity -> numeric fields map is embedded in
  // the page as JSON, so switching entities needs no round-trip).
  function initWidgetForm() {
    var entitySel = document.getElementById('widget-entity');
    var fieldSel = document.getElementById('widget-field');
    var dataEl = document.getElementById('numeric-fields');
    if (!entitySel || !fieldSel || !dataEl) return;
    var entities = [];
    try { entities = JSON.parse(dataEl.textContent || '[]') || []; } catch (e) { return; }

    function rebuild() {
      var current = fieldSel.value;
      var match = null;
      entities.forEach(function (entity) {
        if (String(entity.id) === entitySel.value) match = entity;
      });
      var fields = (match && match.fields) || [];
      fieldSel.innerHTML = '';
      var placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = fields.length ? '— field —' : '— no numeric fields —';
      fieldSel.appendChild(placeholder);
      fields.forEach(function (f) {
        var option = document.createElement('option');
        option.value = f.slug;
        option.textContent = f.name;
        if (f.slug === current) option.selected = true;
        fieldSel.appendChild(option);
      });
    }

    entitySel.addEventListener('change', rebuild);
    if (entitySel.value) rebuild();
  }
  initWidgetForm();

  // Sticky horizontal scrollbar: when a grid is wider than the viewport AND
  // extends below the fold, its own scrollbar sits at the end of the content
  // and cannot be reached without scrolling the page to the bottom. A proxy
  // element mirrors the wrap's horizontal scroll and stays pinned to the
  // bottom of the visible area; it hides once the natural scrollbar is on
  // screen (grid bottom above the viewport bottom) or the grid is not wider
  // than its container.
  var stickyScrollbars = [];

  function initStickyScrollbar(wrap) {
    if (wrap.dataset.stickyScrollInit) return;
    wrap.dataset.stickyScrollInit = '1';
    var proxy = document.createElement('div');
    proxy.className = 'sticky-scrollbar';
    proxy.setAttribute('aria-hidden', 'true');
    var inner = document.createElement('div');
    inner.className = 'sticky-scrollbar-inner';
    proxy.appendChild(inner);
    document.body.appendChild(proxy);
    wrap.addEventListener('scroll', function () {
      if (proxy.scrollLeft !== wrap.scrollLeft) proxy.scrollLeft = wrap.scrollLeft;
    });
    proxy.addEventListener('scroll', function () {
      if (wrap.scrollLeft !== proxy.scrollLeft) wrap.scrollLeft = proxy.scrollLeft;
    });
    stickyScrollbars.push({ wrap: wrap, proxy: proxy, inner: inner });
  }

  function updateStickyScrollbars() {
    var viewport = window.innerHeight || document.documentElement.clientHeight;
    for (var i = stickyScrollbars.length - 1; i >= 0; i--) {
      var entry = stickyScrollbars[i];
      if (!entry.wrap.isConnected) {
        // The grid was replaced by an htmx swap: drop the stale proxy.
        entry.proxy.remove();
        stickyScrollbars.splice(i, 1);
        continue;
      }
      var wrap = entry.wrap;
      var rect = wrap.getBoundingClientRect();
      var overflows = wrap.scrollWidth > wrap.clientWidth + 1;
      var belowFold = rect.top < viewport && rect.bottom > viewport + 1;
      if (!overflows || !belowFold) {
        entry.proxy.classList.remove('visible');
        continue;
      }
      entry.proxy.style.left = rect.left + 'px';
      entry.proxy.style.width = rect.width + 'px';
      entry.inner.style.width = wrap.scrollWidth + 'px';
      entry.proxy.classList.add('visible');
      if (entry.proxy.scrollLeft !== wrap.scrollLeft) {
        entry.proxy.scrollLeft = wrap.scrollLeft;
      }
    }
  }

  var stickyFrame = null;
  function scheduleStickyUpdate() {
    if (stickyFrame) return;
    stickyFrame = window.requestAnimationFrame(function () {
      stickyFrame = null;
      updateStickyScrollbars();
    });
  }

  function initStickyScrollbars(root) {
    (root || document).querySelectorAll('.table-wrap').forEach(initStickyScrollbar);
    scheduleStickyUpdate();
  }

  initStickyScrollbars(document);
  window.addEventListener('scroll', scheduleStickyUpdate, { passive: true });
  window.addEventListener('resize', scheduleStickyUpdate, { passive: true });
  // Swapped-in grids (view detail, modal fragments) get their own proxy.
  document.body.addEventListener('htmx:afterSettle', function (e) {
    var target = e.detail && e.detail.target;
    initStickyScrollbars(target && target.querySelectorAll ? target : document);
  });

  // API token user filter (admin page): client-side row filter on the user
  // column, persisted in the shared UI state.
  function applyTokenFilter(select) {
    var table = document.getElementById('tokens-table');
    if (!table) return;
    var value = select.value;
    table.querySelectorAll('tbody tr').forEach(function (row) {
      row.style.display = !value || row.getAttribute('data-user-id') === value ? '' : 'none';
    });
    try {
      var ui = JSON.parse(localStorage.getItem('inframp-ui-state') || 'null') || {};
      ui.tokenFilter = value;
      localStorage.setItem('inframp-ui-state', JSON.stringify(ui));
    } catch (e) { /* ignore */ }
  }
  var tokenFilter = document.getElementById('token-user-filter');
  if (tokenFilter) {
    try {
      var savedUi = JSON.parse(localStorage.getItem('inframp-ui-state') || 'null') || {};
      var savedFilter = savedUi.tokenFilter || '';
      var match = tokenFilter.querySelector('option[value="' + savedFilter + '"]');
      if (match) tokenFilter.value = savedFilter;
    } catch (e) { /* ignore */ }
    applyTokenFilter(tokenFilter);
    tokenFilter.addEventListener('change', function () {
      applyTokenFilter(tokenFilter);
    });
  }

  // Copy buttons (API token reveal): write the target element's text to the
  // clipboard, with a fallback for browsers without the async clipboard API.
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.copy-btn');
    if (!btn) return;
    var target = document.getElementById(btn.getAttribute('data-copy-target'));
    if (!target) return;
    var text = target.textContent.trim();
    function done() {
      btn.innerHTML = '<i class="fa-solid fa-check" aria-hidden="true"></i> Copied';
      btn.classList.add('copied');
    }
    function fallback() {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand('copy');
        done();
      } catch (err) { /* ignore */ }
      document.body.removeChild(ta);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, fallback);
    } else {
      fallback();
    }
  });

  // Mobile sidebar drawer: hamburger toggles the off-canvas menu; the
  // backdrop click or any sidebar link closes it. Escape closes it and
  // returns focus to the hamburger.
  var mobileMenuBtn = document.getElementById('mobile-menu-btn');
  var sidebarBackdrop = document.getElementById('sidebar-backdrop');
  function setMobileSidebar(open) {
    document.body.classList.toggle('sidebar-open', open);
    if (mobileMenuBtn) {
      mobileMenuBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
      mobileMenuBtn.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
      mobileMenuBtn.setAttribute('title', open ? 'Close menu' : 'Open menu');
    }
    if (open) {
      var firstLink = document.querySelector('.sidebar a[href]');
      if (firstLink) firstLink.focus();
    } else if (mobileMenuBtn) {
      mobileMenuBtn.focus();
    }
  }
  if (mobileMenuBtn) {
    mobileMenuBtn.addEventListener('click', function () {
      setMobileSidebar(!document.body.classList.contains('sidebar-open'));
    });
  }
  if (sidebarBackdrop) {
    sidebarBackdrop.addEventListener('click', function () { setMobileSidebar(false); });
  }
  document.addEventListener('click', function (e) {
    if (!document.body.classList.contains('sidebar-open')) return;
    var link = e.target.closest && e.target.closest('.sidebar a');
    if (link) setMobileSidebar(false);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && document.body.classList.contains('sidebar-open')) {
      setMobileSidebar(false);
    }
  });

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
        // Reset the select so its (named) value never double-submits.
        select.selectedIndex = 0;
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

  // Flash messages: dismiss button and URL cleanup (the ?flash= query param
  // is stripped so reloads don't re-show stale messages).
  document.addEventListener('click', function (e) {
    var closeBtn = e.target.closest('.flash-close');
    if (closeBtn) {
      closeBtn.closest('.flash').remove();
    }
  });
  if (window.location.search.indexOf('flash=') !== -1) {
    var cleanUrl = window.location.pathname;
    try { window.history.replaceState(null, '', cleanUrl); } catch (err) { /* ignore */ }
  }
})();
