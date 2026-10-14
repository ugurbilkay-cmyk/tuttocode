import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { ENTRY, STEP_HEADINGS, birthDate, inputRecord, classify, runPrecheck, saveEvidence } from '../scripts/govuk_precheck.mjs';

function fakeDriver({ rating = 'Good', unknown = false, queue = false, blocked = false, timeout = false, changedHeading = false, previousResult = false } = {}) {
  const actions = [];
  const paths = ['/filter/overseas', '/filter/age', '/filter/previous-passport', '/filter/how-to-apply',
    '/photo/digital-photo', '/photo/choose-photo-method', '/photo/how-to-take-a-photo', '/photo/upload',
    '/photo/photo-check-result-good'];
  let index = previousResult ? 8 : 0;
  let cookie = true;
  return {
    actions,
    goto: async url => { assert.equal(url, ENTRY); actions.push(['goto', url]); },
    snapshot: async () => ({ url: `https://www.passport.service.gov.uk${unknown ? '/unexpected' : paths[index]}`,
      h1: index === 8 ? 'Photo result' : changedHeading ? 'Accept declaration' : STEP_HEADINGS[paths[index]], h2: index === 8 ? ['Your photo', rating] : [],
      mainText: blocked ? 'Web Page Blocked!' : queue ? 'You are in a queue' : index === 8 ? `Photo result\n${rating}\nActual feedback` : 'Input page' }),
    hasButton: async () => cookie,
    clickButton: async name => { actions.push(['click', name]); if (name.includes('cookies')) cookie = false; else index++; },
    checkRadio: async name => actions.push(['radio', name]),
    fill: async (label, value) => actions.push(['fill', label, value]),
    upload: async (name, file) => { actions.push(['upload', name, file]); index++; },
    waitForResult: async () => { if (timeout) throw new Error('Timed out waiting for result'); },
    screenshot: async () => Buffer.from('screenshot fixture'),
  };
}
let fixtureDirectory;
let input;
test.before(async () => {
  fixtureDirectory = await fs.mkdtemp(path.join(os.tmpdir(), 'govuk-workflow-'));
  const file = path.join(fixtureDirectory, 'sample.jpg');
  const data = Buffer.alloc(50000); data[0] = 0xff; data[1] = 0xd8;
  await fs.writeFile(file, data);
  input = { ...await inputRecord({ photo: file, dob: '1980-01-01', syntheticDob: true, authorisedUpload: true }) };
});
test.after(async () => { await fs.rm(fixtureDirectory, { recursive: true }); });

test('DOB rejects nonexistent, future and ambiguous dates', () => {
  assert.deepEqual(birthDate('2000-02-29'), { year: 2000, month: 2, day: 29 });
  for (const value of ['2001-02-29', '1980-13-01', '01/01/1980', '2999-01-01']) assert.throws(() => birthDate(value));
});
test('authorisation is required before reading or transmitting a photo', async () => {
  await assert.rejects(inputRecord({ photo: '/missing', dob: '1980-01-01' }), /Authorisation/);
});
test('input captures the exact JPEG hash and synthetic DOB', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'govuk-input-'));
  try {
    const file = path.join(tmp, 'photo.jpg');
    const jpeg = Buffer.alloc(50000); jpeg[0] = 0xff; jpeg[1] = 0xd8;
    await fs.writeFile(file, jpeg);
    const record = await inputRecord({ photo: file, dob: '1980-01-01', syntheticDob: true, authorisedUpload: true });
    assert.equal(record.photoSha256.length, 64);
    assert.equal(record.syntheticDob, true);
    await fs.writeFile(file, Buffer.alloc(50000));
    await assert.rejects(inputRecord({ photo: file, dob: '1980-01-01', authorisedUpload: true }), /JPEG/);
  } finally { await fs.rm(tmp, { recursive: true }); }
});
test('only an actual Photo result with Good qualifies', () => {
  assert.equal(classify({ h1: 'Photo result', h2: ['Good'] }), 'good');
  assert.equal(classify({ h1: 'Instructions', h2: ['Good'] }), 'unavailable');
  assert.equal(classify({ h1: 'Photo result', h2: ['Other rating'] }), 'needs_review');
});
test('normal workflow uploads once and never continues beyond the photo result', async () => {
  const driver = fakeDriver();
  const result = await runPrecheck(driver, input);
  assert.equal(result.status, 'good');
  assert.equal(result.referenceComparisonEligible, false);
  assert.equal(result.syntheticDob, true);
  assert.equal(result.applicationSubmitted, false);
  assert.equal(driver.actions.filter(action => action[0] === 'upload').length, 1);
  assert.deepEqual(driver.actions.at(-1), ['upload', 'Choose your photo', input.photo]);
});
test('non-Good result preserves feedback without inventing Photomatic scores', async () => {
  const result = await runPrecheck(fakeDriver({ rating: 'Other rating' }), { ...input, syntheticDob: false });
  assert.equal(result.status, 'needs_review');
  assert.match(result.resultText, /Actual feedback/);
  assert.equal('photomatic' in result, false);
});
test('unknown page, queue and timeout never become a pass', async () => {
  for (const scenario of [{ unknown: true }, { queue: true }, { blocked: true }, { timeout: true }, { changedHeading: true }]) {
    const driver = fakeDriver(scenario);
    const result = await runPrecheck(driver, input);
    assert.equal(result.status, 'unavailable');
    assert.equal(result.referenceComparisonEligible, false);
    assert.ok(result.error);
    assert.ok(driver.actions.filter(action => action[0] === 'upload').length <= 1);
  }
});
test('changed photo is not uploaded under an obsolete fingerprint', async () => {
  const driver = fakeDriver();
  const result = await runPrecheck(driver, { ...input, photoSha256: 'different' });
  assert.equal(result.status, 'unavailable');
  assert.match(result.error, /changed/);
  assert.equal(result.uploaded, false);
  assert.equal(driver.actions.some(action => action[0] === 'upload'), false);
});
test('a previous browser result cannot validate a different selected photo', async () => {
  const result = await runPrecheck(fakeDriver({ previousResult: true }), input);
  assert.equal(result.status, 'unavailable');
  assert.equal(result.uploaded, false);
  assert.match(result.error, /previous photo result/);
});
test('unverified child context remains separate from validated adult comparisons', async () => {
  const result = await runPrecheck(fakeDriver(),{...input,syntheticDob:false,ageYears:3});
  assert.equal(result.status,'good');
  assert.equal(result.ageContextVerified,false);
  assert.equal(result.referenceComparisonEligible,false);
});
test('evidence writes preserve separate runs rather than overwrite', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'govuk-evidence-'));
  try {
    const driver = fakeDriver();
    const result = await runPrecheck(driver, input);
    const first = await saveEvidence(driver, { ...result }, tmp);
    const second = await saveEvidence(driver, { ...result }, tmp);
    assert.notEqual(first, second);
    assert.equal(JSON.parse(await fs.readFile(path.join(first, 'result.json'))).status, 'good');
    assert.equal(await fs.readFile(path.join(first, 'result.png'), 'utf8'), 'screenshot fixture');
  } finally { await fs.rm(tmp, { recursive: true }); }
});
