/* InfraMP UI behaviours: theme switching, sidebar collapse, user menu, modal. */
(function () {
  'use strict';

  var THEME_KEY = 'inframp-theme';
  var SIDEBAR_KEY = 'inframp-sidebar';

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

    headers.forEach(function (th) {
      if (th.classList.contains('no-sort')) return;
      th.classList.add('sortable');
      var indicator = document.createElement('span');
      indicator.className = 'sort-indicator';
      indicator.innerHTML = '<i class="fa-solid fa-sort" aria-hidden="true"></i>';
      th.appendChild(indicator);

      th.addEventListener('click', function () {
        var column = Array.prototype.indexOf.call(th.parentNode.children, th);
        var direction;
        if (th.classList.contains('sorted-asc')) {
          direction = 'desc';
        } else if (th.classList.contains('sorted-desc')) {
          direction = 'none';
        } else {
          direction = 'asc';
        }
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
        moveRows(function (a, b) {
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
        });
      });
    });
  }

  document.querySelectorAll('table[data-sortable]').forEach(initSortableTable);

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
