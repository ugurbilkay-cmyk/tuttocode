# Official photo rules compared with the folder

Checked 12 October 2026. This initial pass compares selected fields in **11
profiles across six jurisdictions**. Finland's accessible evidence is the original
2015 decree, with current amendments still to confirm. This does not validate all
208 profiles or every requirement of these 11. Reference settings remain intact;
the findings define corrections and validation for Tuttoprint's own system.

## United Kingdom

UK paper dimensions match 35 × 45 mm. The stored 64–75% head range is
28.8–33.75 mm; the published crown-to-chin range is 29–34 mm. Use exact official
bounds with a calibrated measurement. [UK paper requirements](https://www.gov.uk/photos-for-passports/photo-requirements).

Both UK online exports exceed the published 600 × 750 minimum. The digital rules
require 50 KB–10 MB and unaltered colour photos. The separate `UK online` profile's
100000 legacy-KB upper limit conflicts with that maximum; validate final delivered
bytes. The decoded 6°/90-pixel checks are internal thresholds, not numeric limits
established by this public guidance. [UK digital requirements](https://www.gov.uk/photos-for-passports).

Our own UK code architecture follows the published HTTPS short-URL and signed
retrieval model. Transport success does not constitute photo approval.
[HMPO supplier protocol](https://www.passport.service.gov.uk/help/photo-codes).

### GOV.UK automated precheck integration research — 14 October 2026

HMPO documents an automated technical photo check in the online application.
It displays errors and correction tips, and then asks the customer to review
the photo. This is a useful additional UK reference result, rather than a
complete approval certificate. Some checks require later examination.
[Examiner guidance: digital online check](https://www.gov.uk/government/publications/photographic-standards/photo-standards-accessible#digital-photo-online-check).

No published public supplier photo-validation API or photo-check sandbox was
found in the official sources searched. That does not prove a partner interface
does not exist. The published supplier protocol explains secure JPEG retrieval
by photo code, not a validation request returning quality scores. Confirm an
appropriate integration/test route with HMPO before relying on bulk production
automation. No message to HMPO has been sent.

A test browser helper now follows the ordinary public journey and records the
visible precheck result. The first end-to-end trial and the reusable workflow
both reached a Good result on 14 October 2026, as documented below. This is not
a supported public API integration. Opening the official Start now link during research redirected the reading
tool to a JavaScript queue, so plain stateless HTTP access did not reach the
upload flow. This is not evidence that ordinary browser access is unavailable.
Do not bypass the queue, use guessed private endpoints, infer an API contract
from browser traffic or treat an unavailable result as a pass.
[Application entry point](https://www.gov.uk/apply-renew-passport).

For a controlled proof of concept, select one specifically authorised photo and
the correct birth information, verify the normal browser flow, upload the exact
delivered JPEG, capture the result wording and photo reference, and stop after
the precheck. Do not submit a passport application, accept its final declaration
or pay an application fee as part of a photo-quality trial. Use the correct age
context; children have different standards/allowances, so arbitrary birth dates
can undermine the comparison. The exact age-dependent behaviour of the public
checker has not been measured in this research.
[Children's photo exceptions](https://www.gov.uk/government/publications/photographic-standards/photo-standards-accessible#exceptions-to-photo-standards-for-children).

HMPO states that photos, gender and date-of-birth details can be held for up to
six months, including incomplete/discontinued applications. Treat testing as an
external data transfer and explain that retention before selecting customer
photos for it. Initial source research transmitted no customer photos or birth
information. The subsequent explicitly authorised browser trials sent the
installed sample export and a labelled synthetic adult birthday.
[Application privacy policy](https://www.passport.service.gov.uk/help/privacy).

Store a GOV.UK result as a separate evidence source: automated precheck passed,
flagged (with the actual reasons), unavailable, or not checked. Link it to the
exact JPEG digest, document/age context, observed framing/crop, operator and
time. Do not translate it into Photomatic's three dark-green categories or
claim an official acceptance decision. An API adapter, if documented access is
established, can subsequently replace the browser/manual collection step.

The current official examiner guidance permits brightness/contrast filters and
background edits that preserve likeness, but specifically rejects facial
enhancements such as blemish removal. An online precheck pass cannot establish
compliance of our skin-cleaning recipe with those rules. The portrait-cleanup-v2
prompt permits tiny temporary surface-spot cleanup; UK suitability needs to be
resolved against the facial-editing rule, independently of machine pass counts.
[Photo editing rules](https://www.gov.uk/government/publications/photographic-standards/photo-standards-accessible#photo-editing),
[Precheck is not final acceptance](https://www.passport.service.gov.uk/help/terms-and-conditions).

#### Live trial and automatic test runner

The explicitly authorised installed sample was prepared by our independent
offline engine using Balanced enhancement and the UK Online Renewal profile.
The uploaded JPEG was 800 × 1120 pixels, with SHA-256
`c4e0e36c6b05aa4f9b84d2c3c8b17fb42da258984d1a90d4bf8f8a2afae7c590`.
The user requested an invented birthday; the trial used 1 January 1980 and
records it as synthetic, ineligible for age-correct customer validation counts.
No customer's real date of birth was inferred. Both runs uploaded the same
sample, so they represent one unique photo rather than two validation cases.

The ordinary browser reached **Photo result → Good**, with no displayed flags.
It said that photos with a good rating are most likely to be suitable. The
reusable workflow completed in **7.12 seconds** through the Codex browser driver.
No application, declaration, payment or code generation followed. No manual
GOV.UK crop was applied; the government's internally assessed region was not
verified and must not be assumed byte-identical to the export.

Our own profile-based head-size check flagged this export at 46.8% versus the
decoded template's 30–44% range. GOV.UK's Good result does not automatically
invalidate that measurement or validate its threshold. This is a concrete
calibration discrepancy to investigate with framing evidence and Photomatic.
It is not a three-dark-green Photomatic match.

`scripts/govuk_precheck.mjs` supplies the shared browser workflow and a local
Playwright CLI. It records the exact JPEG hash, birthday context, visible rating
and feedback, elapsed time, screenshot, journey steps and stop conditions.
Queues, verification challenges, unexpected pages and timeouts are recorded as
unavailable, never as a pass. Non-Good photo results are retained as needs-review
with their actual wording; their score mapping has not yet been live validated.
It uploads one explicitly selected file per invocation, with no bulk retries,
and stops at the result page. The CLI browser launcher is separate from the
Codex driver used in the live trial. See [run instructions](GOVUK_PRECHECK.md).

Private evidence lives under the ignored `output/govuk-precheck-20261014/`
directory. It is not published in Git or attached to the PR. The standalone
runner has focused tests for provenance, date validation, stop behaviour,
failure handling and preserving separate evidence files.

## Ireland

The paper profile's 35 × 45 mm is within the published size range. Online output
715 × 951 matches the minimum. Normalize its 9000 legacy-KB limit against 9 MB
using explicit byte units. Alteration is prohibited; issuing a provider code is
separate from providing an uploadable JPEG. Public guidance does not validate all
stored head/eye percentages. [Irish photo guidelines](https://api.ireland.ie/en/dfa/passports/photo-guidelines/).

The native width-first crop behaviour is separately documented in
[the decoding notes](STANDARDS_DECODING.md).

## United States

The paper working frame is 50 × 50 mm, but the default sheet places photos at
51 × 51 mm, matching the guide's rounded equivalent of 2 × 2 inches. Its 50–68%
head range becomes 25.5–34.68 mm on that sheet, within the guide's 25–35 mm range.
Validate the final deliverable rather than changing the intermediate frame
automatically. This comparison does not cover visa or online renewal profiles.
[U.S. passport requirements](https://travel.state.gov/en/passports/apply/help/photos.html).

## Canada

Paper size matches 50 × 70 mm. The stored head range is 30.8–36.4 mm, slightly
wider than the published 31–36 mm. Monochrome or colour is allowed, so the current
processor's blanket colour-only rejection is inappropriate for this document.
Photographer/date details also belong to physical delivery.
[Canadian requirements](https://www.canada.ca/en/immigration-refugees-citizenship/services/canadian-passports/photos.html).

Online output 1200 × 1800 and 45–50% head framing match the published minimum and
range. Official resolution extends to 3000 × 4500; bytes must be 200 KB–5 MB.
The template's 4000 legacy-KB maximum is nominally more restrictive, pending exact
unit normalization. Treat paper and online as distinct policies.
[Canadian digital specifications](https://www.canada.ca/en/immigration-refugees-citizenship/services/canadian-passports/photos.html#digital-photo-specifications).

## Australia

Both passport profiles use 35 × 45 mm, within the published dimensions. Their
head range is 31.95–36 mm rather than precisely 32–36 mm. Australian passport
prints require dye sublimation; inkjet is excluded. Glasses/child exceptions also
need specific policy. [Australian Passport Office](https://www.passports.gov.au/passports-explained/how-apply/passport-photo-guidelines).

The DE100-XD uses piezoelectric inkjet, so it cannot be presented as meeting that
Australian passport printing requirement merely because the layout fits.
[DE100-XD specifications](https://www.fujifilm.com/de/en/business/photofinishing/frontier-dry/de100xd/specifications).

## Finland

36 × 47 mm and 500 × 653 pixels match the original decree. The stored head range
31.96–36.19 mm is wider than its 32–36 mm. The decree specifies headroom, chin
clearance and centering and excludes hair/beard from dimensional measurements;
our visible-hair crown measurement needs a different validation. JPEG size is
capped at 250 KB. These statements translate sections 2 and 9 of the Finnish text.
[Original decree 532/2015](https://www.finlex.fi/fi/laki/alkup/2015/20150532).

The Police guide and current consolidated text were unavailable in this pass.
Confirm amendments before calling this a complete current-rule validation.

## Validation method

For each profile retain the decoded setting, authoritative source/date, our
measurement method and evidence from final exports/prints as distinct records.
Check dimensions, calibrated framing, byte limits, appearance/editing policy,
age/medical exceptions, paper/print method and provider integration. A match for
one field cannot mark the whole profile approved. Compare original/output pairs
to calibrate our AI independently of proprietary scores.

The [print audit](PRINT_PIPELINE.md) provides real finished output and handoff
evidence, including differences from saved defaults. Physical print testing is
still required.
