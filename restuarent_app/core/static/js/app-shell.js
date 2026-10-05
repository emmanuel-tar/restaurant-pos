/* ==========================================================================
   Sidebar toggle.

   - Desktop: switches between expanded (260px) and collapsed (76px, icons only)
   - Mobile (<=992px): slides the sidebar in/out as a drawer
   - The choice is remembered in localStorage, and applied before first paint by
     the inline snippet in base.html, so the layout never flashes.
   ========================================================================== */
(function () {
  'use strict';

  var STORAGE_KEY = 'pos.sidebar';
  var MOBILE_QUERY = '(max-width: 992px)';
  var root = document.documentElement;
  var backdrop = document.querySelector('.app-sidebar__backdrop');

  function isMobile() {
    return window.matchMedia(MOBILE_QUERY).matches;
  }

  function isCollapsed() {
    return root.getAttribute('data-sidebar') === 'collapsed';
  }

  function apply(state) {
    root.setAttribute('data-sidebar', state);
    try {
      localStorage.setItem(STORAGE_KEY, state);
    } catch (e) {
      /* private browsing / storage disabled - the toggle still works */
    }
    document.dispatchEvent(new CustomEvent('sidebar:toggled', { detail: { state: state } }));
  }

  function toggle() {
    if (isMobile()) {
      var open = root.getAttribute('data-sidebar') === 'mobile-open';
      apply(open ? 'expanded' : 'mobile-open');
      return;
    }
    apply(isCollapsed() ? 'expanded' : 'collapsed');
  }

  // Any sidebar link closes the drawer on mobile.
  document.addEventListener('click', function (event) {
    var link = event.target.closest('.app-sidebar__link');
    if (link && isMobile() && root.getAttribute('data-sidebar') === 'mobile-open') {
      apply('expanded');
    }
  });

  if (backdrop) {
    backdrop.addEventListener('click', function () {
      apply('expanded');
    });
  }

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && root.getAttribute('data-sidebar') === 'mobile-open') {
      apply('expanded');
    }
  });

  document.addEventListener('DOMContentLoaded', function () {
    var toggleButton = document.querySelector('.app-topbar__toggle');
    if (toggleButton) {
      toggleButton.addEventListener('click', toggle);
    }

    // Leaving the mobile breakpoint must not leave the drawer "open" forever.
    window.matchMedia(MOBILE_QUERY).addEventListener('change', function () {
      if (!isMobile() && root.getAttribute('data-sidebar') === 'mobile-open') {
        apply(isCollapsed() ? 'collapsed' : 'expanded');
      }
    });

    // ── Live clock in the topbar ──────────────────────────────────────────
    var clock = document.querySelector('.app-topbar__clock');
    if (clock) {
      var tick = function () {
        var now = new Date();
        clock.textContent = now.toLocaleDateString(undefined, {
          day: '2-digit',
          month: 'short'
        }) + '  ' + now.toLocaleTimeString(undefined, {
          hour: '2-digit',
          minute: '2-digit'
        });
      };
      tick();
      setInterval(tick, 30000);
    }
  });
})();