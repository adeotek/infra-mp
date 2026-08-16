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
    });
  }

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

    // Clicking the backdrop (outside the dialog box) closes it.
    modal.addEventListener('click', function (e) {
      if (e.target === modal) modal.close();
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
})();
