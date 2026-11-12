// Exercise the real navigation script with DOM events; no dependencies required.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup(isMobile) {
  let document;
  function node(parent = null) {
    return {
      parent, hidden: false, attributes: {}, handlers: {}, classList: { add() {} },
      setAttribute(key, value) { this.attributes[key] = value; },
      getAttribute(key) { return this.attributes[key]; },
      addEventListener(type, handler) { this.handlers[type] = handler; },
      emit(type, event = {}) { this.handlers[type]?.(event); },
      contains(child) { return child === this || Boolean(child?.parent && this.contains(child.parent)); },
      focus() { document.activeElement = this; },
    };
  }
  const header = node();
  const toggle = node(header);
  const nav = node(header);
  const link = node(nav);
  link.setAttribute('href', '#projects');
  link.closest = () => link;
  nav.querySelector = () => link;
  const section = node();
  document = node();
  const nodes = { '.header': header, '#menu-toggle': toggle, '#primary-navigation': nav, '#projects': section };
  document.querySelector = (selector) => nodes[selector];
  const mobile = node();
  mobile.matches = isMobile;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../src/navigation.js'), 'utf8'), {
    document, window: { matchMedia: () => mobile },
  });
  return { document, toggle, nav, link, section, mobile };
}

{
  const { document, toggle, nav } = setup(true);
  assert.equal(toggle.hidden, false);
  assert.equal(nav.hidden, true);
  toggle.emit('click');
  assert.equal(nav.hidden, false);
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  document.emit('keydown', { key: 'Escape' });
  assert.equal(nav.hidden, true);
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  assert.equal(document.activeElement, toggle);
  toggle.emit('click');
  toggle.emit('click');
  assert.equal(nav.hidden, true);
}
{
  const { document, toggle, nav, link, section } = setup(true);
  toggle.emit('click');
  link.focus();
  nav.emit('click', { target: link });
  assert.equal(nav.hidden, true);
  assert.equal(document.activeElement, section);
  toggle.emit('click');
  nav.emit('click', { target: link, ctrlKey: true });
  assert.equal(nav.hidden, false, 'modified clicks retain browser behavior');
}
{
  const { document, toggle, nav, link } = setup(true);
  toggle.emit('click');
  link.focus();
  document.emit('click', { target: {} });
  assert.equal(nav.hidden, true);
  assert.equal(document.activeElement, toggle);
}
{
  const { document, toggle, nav, link, mobile } = setup(false);
  assert.equal(toggle.hidden, true);
  assert.equal(nav.hidden, false);
  link.focus();
  mobile.matches = true;
  mobile.emit('change');
  assert.equal(nav.hidden, true);
  assert.equal(document.activeElement, toggle);
  mobile.matches = false;
  mobile.emit('change');
  assert.equal(nav.hidden, false);
  assert.equal(toggle.hidden, true);
  assert.equal(document.activeElement, link);
}
console.log('OK: navigation toggle, Escape, anchor focus, outside click and viewport changes');
