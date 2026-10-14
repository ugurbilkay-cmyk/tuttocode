// Test-only public-browser workflow. No private HMPO endpoints or application submission.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

const ENTRY = 'https://www.passport.service.gov.uk/filter';
const ORIGIN = 'https://www.passport.service.gov.uk';
const VERSION = 'govuk-browser-precheck-v1';
const STEP_HEADINGS = {
  '/filter/overseas': 'Do you live in the UK?',
  '/filter/age': 'Date of birth',
  '/filter/previous-passport': 'Have you had a UK passport before?',
  '/filter/how-to-apply': 'How to apply',
  '/photo/digital-photo': 'How to get a digital passport photo',
  '/photo/choose-photo-method': 'Get a digital photo',
  '/photo/how-to-take-a-photo': 'How to take a digital passport photo',
  '/photo/upload': 'Upload your photo',
};

function birthDate(value, now = new Date()) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) throw new Error('DOB must be YYYY-MM-DD.');
  const date = new Date(`${value}T00:00:00Z`);
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== value || date > now) {
    throw new Error('DOB must be a valid date that is not in the future.');
  }
  const [year, month, day] = value.split('-').map(Number);
  return { year, month, day };
}

async function inputRecord({ photo, dob, syntheticDob = false, authorisedUpload = false }) {
  if (!authorisedUpload) throw new Error('Authorisation to send this photo and DOB to GOV.UK is required.');
  const parsed = birthDate(dob);
  if (typeof photo !== 'string' || !photo) throw new Error('An explicit --photo JPEG path is required.');
  const file = path.resolve(photo);
  const data = await fs.readFile(file);
  if (data.length < 50000 || data.length > 10000000 || data[0] !== 0xff || data[1] !== 0xd8) {
    throw new Error('Use a JPEG between 50 KB and 10 MB.');
  }
  return {
    photo: file, photoSha256: crypto.createHash('sha256').update(data).digest('hex'),
    photoBytes: data.length, dob, birth: parsed, syntheticDob: !!syntheticDob,
    authorisedUpload: true, destination: ORIGIN, retentionNotice: 'HMPO may retain photo and DOB for up to six months.',
  };
}

function classify(state) {
  if (state.h1 !== 'Photo result') return 'unavailable';
  // A Good rating is the only passing rating observed in the live trial.
  // Other result pages keep their full wording for staff review; no guessed score mapping.
  return state.h2.includes('Good') ? 'good' : 'needs_review';
}

function allowed(state) {
  const url = new URL(state.url);
  if (url.origin !== ORIGIN) throw new Error('Outside the normal passport journey; check unavailable.');
  if (/captcha|verify you are human|waiting room|you are in a queue/i.test(state.mainText)) {
    throw new Error('Queue or human verification encountered; no bypass attempted.');
  }
  return url.pathname;
}

// driver supplies normal visible-browser actions. Shared by the CLI and Codex CUA trial.
async function runPrecheck(driver, input) {
  const started = new Date();
  const steps = [];
  let uploaded = false;
  let state;
  let error;
  try {
    await driver.goto(ENTRY);
    for (let count = 0; count < 12; count++) {
      state = await driver.snapshot();
      const route = allowed(state);
      steps.push({ path: route, heading: state.h1 });
      if (state.h1 === 'Photo result') {
        if (!uploaded) throw new Error('A previous photo result appeared before this JPEG was uploaded.');
        break;
      }
      if (STEP_HEADINGS[route] !== state.h1) throw new Error('Public page heading changed; stopped before further actions.');
      if (await driver.hasButton('Reject analytics cookies')) {
        await driver.clickButton('Reject analytics cookies');
        state = await driver.snapshot();
        allowed(state);
      }
      switch (route) {
        case '/filter/overseas':
          await driver.checkRadio('Yes');
          await driver.clickButton('Continue');
          break;
        case '/filter/age':
          await driver.fill('Day', String(input.birth.day));
          await driver.fill('Month', String(input.birth.month));
          await driver.fill('Year', String(input.birth.year));
          await driver.clickButton('Continue');
          break;
        case '/filter/previous-passport':
          // Test navigation context, not a claim made in a submitted application.
          await driver.checkRadio('No');
          await driver.clickButton('Continue');
          break;
        case '/filter/how-to-apply':
        case '/photo/digital-photo':
        case '/photo/how-to-take-a-photo':
          await driver.clickButton('Continue');
          break;
        case '/photo/choose-photo-method':
          await driver.checkRadio('I’ll take or upload a digital photo');
          await driver.clickButton('Continue');
          break;
        case '/photo/upload':
          if (uploaded) throw new Error('Upload did not produce a result; no repeat upload attempted.');
          if (crypto.createHash('sha256').update(await fs.readFile(input.photo)).digest('hex') !== input.photoSha256) {
            throw new Error('Selected JPEG changed after fingerprinting; stopped before upload.');
          }
          await driver.upload('Choose your photo', input.photo);
          uploaded = true;
          await driver.waitForResult();
          break;
        default:
          throw new Error('Unrecognised public page; stopped without continuing the application.');
      }
    }
    state = await driver.snapshot();
    allowed(state);
    if (state.h1 !== 'Photo result') throw new Error('No photo result received.');
  } catch (failure) {
    error = failure.message;
    try { state = await driver.snapshot(); } catch { /* preserve the last observed page */ }
  }
  return {
    version: VERSION, startedAt: started.toISOString(), finishedAt: new Date().toISOString(),
    elapsedSeconds: +( (Date.now() - started.getTime()) / 1000 ).toFixed(2),
    status: error ? 'unavailable' : classify(state), error: error || null,
    photoSha256: input.photoSha256, photoBytes: input.photoBytes, photoFile: path.basename(input.photo),
    dob: input.dob, syntheticDob: input.syntheticDob,
    referenceComparisonEligible: !input.syntheticDob && !error,
    testNavigationContext: { residentInUK: true, previousUKPassport: false },
    uploaded, resultPath: state ? new URL(state.url).pathname : null,
    observedHeadings: state ? [state.h1, ...state.h2] : [],
    resultText: state?.mainText || '', steps,
    manualCropAppliedByRunner: false, governmentAssessedCrop: 'not verified',
    applicationSubmitted: false, codeGenerated: false, finalPassportApproval: false,
  };
}

async function saveEvidence(driver, result, directory) {
  const output = path.resolve(directory);
  await fs.mkdir(output, { recursive: true });
  // Each run gets a separate folder; evidence never silently overwrites an older trial.
  const run = await fs.mkdtemp(path.join(output, 'precheck-'));
  try {
    await fs.writeFile(path.join(run, 'result.png'), await driver.screenshot());
    result.screenshot = 'result.png';
  } catch (error) {
    result.screenshotError = error.message;
  }
  await fs.writeFile(path.join(run, 'result.json'), `${JSON.stringify(result, null, 2)}\n`);
  return run;
}

export { ENTRY, VERSION, STEP_HEADINGS, birthDate, inputRecord, classify, runPrecheck, saveEvidence };

if (typeof process !== 'undefined' && process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  (async () => {
    const { values } = parseArgs({ options: {
      photo: { type: 'string' }, dob: { type: 'string' }, output: { type: 'string', default: 'output/govuk-prechecks' },
      'synthetic-dob': { type: 'boolean', default: false }, 'authorised-upload': { type: 'boolean', default: false },
    } });
    const input = await inputRecord({ photo: values.photo, dob: values.dob,
      syntheticDob: values['synthetic-dob'], authorisedUpload: values['authorised-upload'] });
    const { chromium } = await import('playwright');
    const browser = await chromium.launch({ headless: false });
    try {
      const page = await browser.newPage();
      page.setDefaultTimeout(15000);
      const driver = {
        goto: url => page.goto(url),
        snapshot: async () => ({ url: page.url(), h1: await page.locator('h1').first().innerText(),
          h2: await page.locator('h2').allTextContents(), mainText: await page.locator('#main-content').innerText() }),
        hasButton: name => page.getByRole('button', { name, exact: true }).isVisible(),
        clickButton: name => page.getByRole('button', { name, exact: true }).click(),
        checkRadio: name => page.getByRole('radio', { name, exact: true }).check(),
        fill: (label, value) => page.getByLabel(label, { exact: true }).fill(value),
        upload: async (name, file) => {
          const pending = page.waitForEvent('filechooser');
          await page.getByRole('button', { name, exact: true }).click();
          await (await pending).setFiles([file]);
        },
        waitForResult: () => page.getByRole('heading', { name: 'Photo result', exact: true }).waitFor({ timeout: 45000 }),
        screenshot: () => page.screenshot({ fullPage: true }),
      };
      const result = await runPrecheck(driver, input);
      const evidence = await saveEvidence(driver, result, values.output);
      console.log(JSON.stringify({ status: result.status, elapsedSeconds: result.elapsedSeconds, evidence, error: result.error }));
      if (result.status === 'unavailable') process.exitCode = 2;
    } finally { await browser.close(); }
  })().catch(error => { console.error(error.message); process.exitCode = 2; });
}
