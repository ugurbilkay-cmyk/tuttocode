'use strict';
const { JSDOM } = require('jsdom');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.join(__dirname, '..');
const code = fs.readFileSync(path.join(root, 'static/station.js'), 'utf8');

function page(name) {
  const html = fs.readFileSync(path.join(root, `output/station-dom-fixtures/${name}.html`), 'utf8');
  const dom = new JSDOM(html, { url: 'http://localhost:8767/admin/new', runScripts: 'outside-only' });
  const { window } = dom;
  const opened = [];
  window.HTMLDialogElement.prototype.showModal = function () { this.open = true; opened.push(this.id); };
  window.HTMLDialogElement.prototype.close = function () { this.open = false; };
  // Only the template's own configuration script and our station code execute.
  const config = [...window.document.scripts].find(s => s.textContent.startsWith('window.stationPhotoId='));
  window.eval(config.textContent);
  window.eval(code);
  return { window, document: window.document, opened, close: () => window.close() };
}

const studio = page('new');
const { window: w, document: d } = studio;
const form = d.getElementById('photo-form');
const field = name => form.elements.namedItem(name);
assert.equal(field('use_ai').checked, false);
assert.equal(Number(field('enhancer_skin').value), 0);
assert.equal(d.getElementById('enhancement-options').open, false);
field('replace_bg').checked = true;
field('even_bg').checked = true;
field('use_ai').checked = true;
field('ai_consent').checked = true;
const beforeBackground = field('background_engine').value;
for (const [key, skin, denoise] of [['natural', 20, 15], ['balanced', 35, 25], ['strong', 45, 35]]) {
  d.querySelector(`[data-enhance-preset="${key}"]`).click();
  assert.equal(Number(field('enhancer_skin').value), skin);
  assert.equal(Number(field('enhancer_denoise').value), denoise);
  assert.equal(d.querySelector(`[data-enhance-preset="${key}"]`).getAttribute('aria-pressed'), 'true');
  assert.equal(field('replace_bg').checked, true);
  assert.equal(field('even_bg').checked, true);
  assert.equal(field('background_engine').value, beforeBackground);
  assert.equal(field('use_ai').checked, true);
  assert.equal(field('ai_consent').checked, true);
}
d.getElementById('no-enhancement').click();
assert.equal(Number(field('enhancer_skin').value), 0);
assert.equal(Number(field('enhancer_denoise').value), 0);
assert.equal(field('auto_adjust').checked, false);
assert.equal(field('replace_bg').checked, true);
assert.equal(field('even_bg').checked, true);
assert.equal(field('use_ai').checked, true);
assert.equal(field('ai_consent').checked, true);
field('zoom').value = '.84'; field('x').value = '-17'; field('angle').value = '-3';
d.querySelector('[data-country="united-kingdom-online-renewal"]').click();
assert.equal(field('country_id').value, 'united-kingdom-online-renewal');
assert.equal(field('zoom').value, '1'); assert.equal(field('x').value, '0'); assert.equal(field('angle').value, '0');
assert.match(d.getElementById('format-note').textContent, /5:7.*800 × 1120/);
assert.equal(d.getElementById('photo-stage').style.getPropertyValue('--photo-ratio'), '50/70');
assert.ok(field('print_template_id').value);
d.querySelector('[data-country="united-kingdom-passport"]').click();
assert.match(d.getElementById('format-note').textContent, /35 × 45 mm/);
assert.equal(d.getElementById('photo-stage').style.getPropertyValue('--photo-ratio'), '35/45');
studio.close();

const loaded = page('photo');
loaded.document.querySelector('[data-enhance-preset="balanced"]').click();
assert.equal(loaded.document.getElementById('pending-changes').hidden, false);
assert.equal(loaded.document.getElementById('print-button').disabled, true);
assert.equal(loaded.document.querySelector('a[href$="/save.jpg"]').getAttribute('aria-disabled'), 'true');
loaded.document.getElementById('open-openai').click();
assert.ok(loaded.opened.includes('openai-dialog'));
loaded.document.getElementById('close-openai').click();
assert.equal(loaded.document.getElementById('openai-dialog').open, false);
loaded.close();

const ready = page('ready');
assert.ok(ready.opened.includes('openai-dialog'), 'Pending AI preview must remain discoverable after reload');
ready.close();
const readonly = page('readonly');
assert.equal(readonly.document.querySelector('[data-enhance-preset]'), null);
readonly.close();
console.log('Studio DOM interactions pass: three real levels, isolated background/OpenAI choices, UK format switch, dirty-state output and AI review.');
