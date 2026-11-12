// Exercise app.js with a minimal DOM: content must stay literal text.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');

class Element {
  constructor(tag) { this.tagName = tag; this.children = []; }
  append(...children) { this.children.push(...children); }
  addEventListener() {}
  set innerHTML(_) { throw new Error('Profile content must not be parsed as HTML'); }
}

function render(professional) {
  const nodes = new Map();
  // Only existing HTML IDs are queryable, so missing render targets fail too.
  for (const match of fs.readFileSync(path.join(root, 'src/index.html'), 'utf8').matchAll(/id="([^"]+)"/g)) {
    nodes.set('#' + match[1], new Element('div'));
  }
  const context = vm.createContext({
    document: {
      createElement: (tag) => new Element(tag),
      querySelector: (selector) => nodes.get(selector)
    },
    window: { SITE_CONTENT: {
      name: 'Пример', description: 'Описание', about: 'Обо мне',
      interests: [], projects: [], now: [], notes: [], contacts: [], professional
    } }
  });
  vm.runInContext(fs.readFileSync(path.join(root, 'src/app.js'), 'utf8'), context);
  return nodes;
}

const literal = '<img src=x onerror=alert(1)> & текст';
const profile = {
  specialization: literal, summary: 'Другое описание', stack: ['CSS', literal],
  experience: [
    { period: 'Сейчас', role: literal, context: 'Команда', description: 'Личный вклад' },
    { period: 'Ранее', role: 'Другая роль', context: literal, description: 'Результат' }
  ]
};
const nodes = render(profile);
assert.equal(nodes.get('#specialization').textContent, literal);
assert.equal(nodes.get('#professional-summary').textContent, profile.summary);
assert.deepEqual(nodes.get('#stack-list').children.map((node) => [node.tagName, node.textContent]), [
  ['li', 'CSS'], ['li', literal]
]);
const experience = nodes.get('#experience-list').children;
assert.equal(experience.length, 2);
profile.experience.forEach((entry, i) => {
  assert.equal(experience[i].tagName, 'li');
  assert.deepEqual(experience[i].children.map((node) => node.textContent), [
    entry.period, entry.role, entry.context, entry.description
  ]);
});
const empty = render({ ...profile, stack: [], experience: [] });
assert.equal(empty.get('#stack-list').children.length, 0);
assert.equal(empty.get('#experience-list').children.length, 0);
assert.equal(empty.get('#specialization').textContent, literal);
console.log('OK: profile renders literal text, ordered entries and empty lists');
