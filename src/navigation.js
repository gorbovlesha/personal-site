(() => {
  'use strict';
  const header = document.querySelector('.header');
  const toggle = document.querySelector('#menu-toggle');
  const nav = document.querySelector('#primary-navigation');
  const mobile = window.matchMedia('(max-width: 650px)');
  const firstLink = nav.querySelector('a');

  function setOpen(open) {
    toggle.setAttribute('aria-expanded', String(open));
    toggle.textContent = open ? 'Закрыть' : 'Меню';
    nav.hidden = mobile.matches && !open;
  }

  function syncLayout() {
    const active = document.activeElement;
    toggle.hidden = !mobile.matches;
    setOpen(false);
    if (mobile.matches && nav.contains(active)) toggle.focus();
    else if (!mobile.matches && active === toggle) firstLink.focus();
  }

  toggle.addEventListener('click', () => {
    setOpen(toggle.getAttribute('aria-expanded') !== 'true');
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && mobile.matches && !nav.hidden) {
      setOpen(false);
      toggle.focus();
    }
  });
  document.addEventListener('click', (event) => {
    if (mobile.matches && !nav.hidden && !header.contains(event.target)) {
      const hadFocus = nav.contains(document.activeElement);
      setOpen(false);
      if (hadFocus) toggle.focus();
    }
  });
  nav.addEventListener('click', (event) => {
    const link = event.target.closest('a');
    if (!link || !mobile.matches || event.defaultPrevented || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    setOpen(false);
    const target = document.querySelector(link.getAttribute('href'));
    if (target) target.focus({ preventScroll: true });
  });
  mobile.addEventListener('change', syncLayout);
  header.classList.add('nav-ready');
  syncLayout();
})();
