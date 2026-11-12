(() => {
  'use strict';
  const content = window.SITE_CONTENT;
  if (!content) return;
  const $ = (selector) => document.querySelector(selector);
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const safeUrl = (value) => {
    try { const url = new URL(value); return ['https:', 'http:', 'mailto:'].includes(url.protocol) ? url.href : null; }
    catch { return null; }
  };
  $('#hero-name').textContent = content.name;
  $('#hero-positioning').textContent = content.positioning;
  $('#hero-description').textContent = content.description;
  $('#about-text').textContent = content.about;
  $('#year').textContent = new Date().getFullYear();
  content.interests.forEach((interest) => $('#interests').append(element('span', '', interest)));
  const dialog = $('#detail-dialog');
  function openDetail(item, label) {
    $('#dialog-title').textContent = item.title;
    $('#dialog-label').textContent = label;
    $('#dialog-body').replaceChildren(element('p', '', item.body));
    const link = $('#dialog-link');
    const url = safeUrl(item.url);
    link.hidden = !url;
    if (url) { link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; }
    else link.removeAttribute('href');
    dialog.showModal();
  }
  const illustrations = {
    dashboard:'<div class="mini-window"><div class="mini-bar"><i></i><i></i><i></i></div><div class="mini-title">Хороший день, чтобы начать ↗</div><div class="mini-columns"><span></span><div class="mini-chart"><i></i><i></i><i></i><i></i></div></div></div>',
    map:'<div class="map-grid"></div><div class="map-route"></div><span class="map-pin">Вы здесь ✳</span>',
    notebook:'<div class="notebook"><span>мысли<br>на потом.</span><small>FIELD NOTES / 01</small></div>'
  };
  content.projects.forEach((project, index) => {
    const card = element('button', 'project-card');
    card.type = 'button';
    card.setAttribute('aria-haspopup', 'dialog');
    const visual = element('div', 'project-visual visual-' + project.visual);
    visual.setAttribute('aria-hidden', 'true');
    visual.innerHTML = illustrations[project.visual] || '';
    visual.append(element('span', 'project-number', '0' + (index + 1)));
    const meta = element('div', 'project-meta');
    meta.append(element('h3', '', project.title), element('span', 'badge', project.category));
    card.append(visual, meta, element('p', '', project.description));
    card.addEventListener('click', () => openDetail(project, 'ПРИМЕР ПРОЕКТА / 0' + (index + 1)));
    $('#project-list').append(card);
  });
  content.now.forEach((item) => {
    const row = element('div', 'now-item');
    const icon = element('span', 'now-icon', item.icon);
    icon.setAttribute('aria-hidden', 'true');
    const text = element('div');
    text.append(element('small', '', item.label), element('p', '', item.text));
    row.append(icon, text);
    $('#now-list').append(row);
  });
  content.notes.forEach((note) => {
    const row = element('button', 'note-row');
    row.type = 'button';
    row.setAttribute('aria-haspopup', 'dialog');
    const arrow = element('span', 'note-arrow', '↗');
    arrow.setAttribute('aria-hidden', 'true');
    row.append(element('span', 'note-date', note.date), element('span', 'note-title', note.title), element('span', 'note-category', note.category), arrow);
    row.addEventListener('click', () => openDetail(note, 'ДЕМОНСТРАЦИОННАЯ ЗАМЕТКА / ' + note.category.toUpperCase()));
    $('#note-list').append(row);
  });
  const contacts = content.contacts.filter((contact) => safeUrl(contact.url));
  if (contacts.length) {
    $('#contact-actions').replaceChildren();
    contacts.forEach((contact) => {
      const link = element('a', 'button', contact.label + ' ↗');
      link.href = safeUrl(contact.url);
      if (!link.href.startsWith('mailto:')) { link.target = '_blank'; link.rel = 'noopener noreferrer'; }
      $('#contact-actions').append(link);
    });
  }
  $('#close-dialog').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', (event) => {
    const rect = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dialog.close();
  });
})();
