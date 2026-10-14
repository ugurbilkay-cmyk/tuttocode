'use strict';
const {JSDOM} = require('jsdom');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.join(__dirname, '..');
const code = fs.readFileSync(path.join(root, 'static/test_queue.js'), 'utf8');
function page(name) {
  const dom = new JSDOM(fs.readFileSync(path.join(root, `output/test-queue-dom-fixtures/${name}.html`), 'utf8'),
    {url:'http://localhost:8767/admin/tests', runScripts:'outside-only'});
  dom.window.fetch = () => {throw new Error('The queue must make no remote requests');};
  dom.window.eval(code);
  return dom;
}
const selection = page('selection');
const d = selection.window.document;
const form = d.getElementById('test-queue-form');
assert.equal(form.elements.keep_snapshots.checked, false);
const noSelection = new selection.window.Event('submit', {bubbles:true,cancelable:true});
form.dispatchEvent(noSelection);
assert.equal(noSelection.defaultPrevented, true);
for (const [requested,expected] of [[5,5],[10,10],[20,10],[200,10],[0,0]]) {
  d.querySelector(`[data-select-count="${requested}"]`).click();
  assert.equal([...form.elements.photo_ids].filter(input=>input.checked).length, expected);
  assert.equal(d.getElementById('queue-selection-count').textContent, `${expected} selected`);
}
d.querySelector('[data-select-count="5"]').click();
form.dispatchEvent(new selection.window.Event('submit', {bubbles:true,cancelable:true}));
assert.equal(d.getElementById('queue-building').hidden, false);
assert.equal(form.querySelector('button[type=submit]').disabled, true);
selection.window.close();

const sample = page('case');
const c = sample.window.document;
assert.equal(c.querySelector('[name=gov_status]').value, 'not_checked');
assert.equal(c.querySelector('[name=synthetic_dob]').checked, true);
assert.equal(c.querySelector('[name=real_customer]').checked, false);
for (const name of ['image_quality','geometry','background'])
  assert.equal(c.querySelector(`[name=${name}]`).value, 'not_tested');
const anchor = c.getElementById('open-gov-session');
anchor.addEventListener('click', event=>event.preventDefault());
anchor.click();
assert.equal(sample.window.sessionStorage.getItem('manual-gov-photo-session'), '1');
assert.match(c.getElementById('gov-session-note').textContent, /Switch to that tab/);
const observation = c.getElementById('test-observation-form');
const next = observation.querySelector('[name=advance]');
observation.dispatchEvent(new sample.window.SubmitEvent('submit', {bubbles:true,cancelable:true,submitter:next}));
assert.equal(new sample.window.FormData(observation).get('advance'), 'yes', 'Disabling buttons must preserve Save-and-next');
assert.ok([...observation.querySelectorAll('button[type=submit]')].every(button=>button.disabled));
sample.window.close();
console.log('Queue DOM checks pass: batch selection, private defaults, manual session note and Save-and-next serialization.');
