// Validate the actual browser content file without third-party dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const context = vm.createContext({ window: {} });
const filename = path.join(__dirname, '..', 'src', 'content.js');
vm.runInContext(fs.readFileSync(filename, 'utf8'), context, { filename, timeout: 1000 });
const content = context.window.SITE_CONTENT;
assert.ok(content && typeof content === 'object', 'window.SITE_CONTENT is required');

function text(value, field) {
  assert.equal(typeof value, 'string', `${field} must be a string`);
  assert.ok(value.trim(), `${field} must not be empty`);
}
function list(value, field) {
  assert.ok(Array.isArray(value), `${field} must be an array`);
}
function url(value, field, optional = false) {
  if (optional && (value === undefined || value === '')) return;
  text(value, field);
  const parsed = new URL(value);
  assert.ok(['https:', 'http:', 'mailto:'].includes(parsed.protocol), `${field} uses an unsupported protocol`);
}

for (const field of ['name', 'description', 'about']) text(content[field], field);
for (const field of ['interests', 'projects', 'skills', 'experience', 'contacts']) list(content[field], field);
content.interests.forEach((item, i) => text(item, `interests[${i}]`));
content.projects.forEach((item, i) => {
  for (const field of ['title', 'category', 'description', 'body']) text(item[field], `projects[${i}].${field}`);
  assert.ok(['dashboard', 'map', 'notebook'].includes(item.visual), `projects[${i}].visual is unknown`);
  url(item.url, `projects[${i}].url`, true);
});
content.skills.forEach((item, i) => {
  for (const field of ['title', 'text']) text(item[field], `skills[${i}].${field}`);
});
content.experience.forEach((item, i) => {
  for (const field of ['period', 'title', 'text']) text(item[field], `experience[${i}].${field}`);
});
content.contacts.forEach((item, i) => {
  text(item.label, `contacts[${i}].label`);
  url(item.url, `contacts[${i}].url`);
});
console.log('OK: SITE_CONTENT schema and URL protocols');
