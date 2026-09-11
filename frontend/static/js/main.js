/* Navigation only. No authentication, verification, analytics, or API requests. */
(() => {
  const toggle = document.querySelector('.menu-toggle');
  const navigation = document.querySelector('#navigation');
  if (!toggle || !navigation) return;
  document.documentElement.classList.add('js-enabled');
  toggle.hidden = false;
  const closeMenu = () => {
    navigation.classList.remove('is-open');
    toggle.setAttribute('aria-expanded', 'false');
  };
  toggle.addEventListener('click', () => {
    const open = toggle.getAttribute('aria-expanded') !== 'true';
    toggle.setAttribute('aria-expanded', String(open));
    navigation.classList.toggle('is-open', open);
  });
  navigation.addEventListener('click', (event) => {
    if (!event.target.closest('a')) return;
    const mobile = window.matchMedia('(max-width: 760px)').matches;
    closeMenu();
    if (mobile) toggle.focus({ preventScroll: true });
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') {
      closeMenu();
      toggle.focus();
    }
  });
  document.addEventListener('click', (event) => {
    if (!event.target.closest('.nav-bar')) closeMenu();
  });
  window.matchMedia('(max-width: 760px)').addEventListener('change', closeMenu);
})();
