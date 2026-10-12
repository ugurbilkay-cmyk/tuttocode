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
