# Tuttoprint and Photomatic integration plan

Implementation plan prepared on 13 October 2026. The manual preserved-JPEG import, staff review and UK issuance path are implemented in the local prototype. A genuine sample was saved and reopened on the equipped shop installation, transferred and imported byte for byte. Photomatic generated another analysis crop on reopening; exact-file measurement provenance, repeated-export behaviour, the Windows helper and production validation remain outstanding.

The user's priority is two separate tracks. First, run our independent engine now through the simplest working local interface. Its upload, crop, enhancement, background, skin tools, measurements and output routes do not require the Photomatic executable or its licence. Imported document/layout settings are local data; they do not invoke the vendor runtime. Full vendor-score equivalence remains unestablished and unimplemented metrics stay visibly Not tested.

Second, progressively investigate Photomatic's settings, measured behaviour and possible integration. The preserved-file companion workflow below is optional for vendor review; it is not a prerequisite for running our engine. Staff can use both applications while our own quality engine is calibrated against reference examples. Structured-result extraction and deeper analysis remain research tasks, rather than established capabilities. Desktop packaging is deferred while the current local studio is made usable.

## What is ready and what needs building

| Capability | Current position | First version work |
|---|---|---|
| Local enhancement and optional OpenAI preparation | Implemented in the local Tuttoprint prototype | Export a named candidate for Photomatic review |
| Photomatic detailed measurements | Observed working on the local Windows installation | Record the exact document, individual results and final export |
| Country profiles and print layouts | Imported into Tuttoprint; Photomatic printing remains available | Test physical DE100-XD output separately |
| Reviewed Photomatic import | Implemented; genuine vendor sample imported unchanged | Verify representative staff jobs and record the analysis crop |
| Own UK code and retrieval paths | Preserved issuance implemented and locally tested | Verify the public service with HMPO |
| Irish codes | External provider workflow | Retain export to the external provider |
| Automatic extraction of Photomatic scores | No verified interface | Investigate structured results separately; use staff entry initially |

The normal preparation upload, Save and code paths can process or re-encode an image. The separate reviewed-file mode preserves the exported JPEG and avoids those transformations. See [staff instructions](REVIEWED_IMPORT.md).

## Staff workflow

1. Open a camera photo in Tuttoprint and select the document and age group. Preserve the camera original.
2. Apply the included local tools. Use OpenAI only when staff select that optional service. Compare the preparation with the original and review skin repairs.
3. Export the prepared candidate with a job reference. Open it in Photomatic and select the matching document profile. Photomatic may adjust the framing.
4. Review Image Quality, Face size and position, Background and the individual measurements. Record failures, cautions and untested fields as they appear.
5. Save a digital portrait from Photomatic into a dedicated job folder. A print sheet from Backup is a separate output.
6. Reopen that saved portrait in Photomatic and inspect it again. Record Input Image Size and ID photo data dimensions: the equipped-shop test generated a new analysis crop on reopening. Inspect the exact saved JPEG separately. Do not assume repeated saving will converge or that scores for the new crop measure the unchanged file.
7. Import the final JPEG into Tuttoprint in reviewed-file mode. Staff confirm the document, review evidence, likeness and customer permission against that exact file.
8. For UK jobs, issue our code using the preserved JPEG. For Irish jobs, export for the external provider. For other countries, print or save through the selected workflow.

An edit after review creates a new candidate and requires a new review. The original and earlier evidence remain associated with the job until its normal retention expiry.

## First milestone verify the digital export

Use the local Windows test installation. Start with the loaded sample portrait, then one of our prepared portraits. Record the running software version, active country profile, quality profile and Save settings before changing configuration.

Inspect the existing Open File, Auto Process and Save controls. Establish which settings determine the final portrait dimensions and JPEG encoding. The supplied historical default Save profile is 600 by 771 pixels, while the supplied UK Online Renewal profile specifies 800 by 1120. The installed export must be measured rather than inferred from either file.

For each test, collect input and exported dimensions, JPEG byte count, selected profile, observed measurements and statuses, and a SHA-256 digest of the export. Verify the portrait contains no overlays, print sheet artwork or guide lines. Reopen the export and compare framing and measurements with the prior view. Test repeated exports and filename collisions.

Completion means we can reproduce a documented digital portrait export and explain any changes between preparation, Photomatic assessment and export. No real provider code, email or physical print is needed for this milestone.

## Second milestone add preserved import and review

Add an authenticated import action associated with a Tuttoprint job. Store the exported JPEG separately from the working master. Validate that it is a readable supported JPEG within bounded upload limits, record its dimensions and digest, and generate separate preview derivatives. Preserve the JPEG itself unchanged.

Store review evidence with the file digest, job revision, document, age group, operator identity and timestamp. Record vendor software version and profile when available. Individual entries retain the displayed value, displayed status and evidence source. Photomatic scores remain vendor scores; they are not percentages of acceptance or interchangeable with our measurements.

Use four visible states: Pass, Caution, Fail and Not tested. Keep document allowances distinct from an operator responsibility override. Manual results are labelled Staff reviewed in Photomatic. A screenshot can support the review, but a coloured square or saved filename cannot automatically establish a pass.

Update code issuance, Save, email and retrieval so reviewed-file jobs consistently use the preserved deliverable. Audit the retrieval digest and test that the downloaded JPEG equals the imported JPEG byte for byte. Working previews and print sheets remain separate derivatives. Issued jobs retain the exact file used for their code.

Red quality checks remain advisory, with staff able to proceed under the existing responsibility workflow. Missing evidence remains visible. File corruption, stale review, concurrent edits and mismatched files are integrity errors rather than quality decisions.

## Third milestone simplify the Windows handoff

Start with normal Open file and Save controls. After the manual round trip works, add a Windows helper with per-job folders for prepared candidates and reviewed exports. Require staff to select the export for the intended job; folder detection alone never marks it approved.

The helper waits for writes to complete, validates the file, shows the job and document, and imports it through the authenticated service. Retries must not duplicate jobs, codes or reviews. Test partial writes, repeated names, multiple simultaneous customers, cancellations, changed files, offline service and application restarts. Avoid changing shared printer or camera folders.

A dedicated Tuttoprint action opens our job and code screen. Redirecting the existing IDstation.online button is a separate investigation requiring a verified supported interface. The first version does not depend on modifying vendor binaries or replacing its activation settings.

## Fourth milestone verify shop operation

Run representative staff jobs end to end before customer code use. Verify individual operator attribution, permissions, retention cleanup, original preservation, review history and recovery after interruption. Test invalid and expired retrieval requests, exact delivered bytes, HTTPS hosting, code slip and real HMPO retrieval through the appropriate validation process. Creating a local code alone does not prove that HMPO can retrieve it.

For the DE100-XD, verify physical photo dimensions, copies, spacing, printer scaling and colour with the actual driver and paper configuration. Keep Photomatic available for other-country printing during the transition. Irish code submission remains with the chosen provider.

## Independent quality engine calibration

### Agreed 200-photo paired trial

On 14 October 2026 the user specified a minimum of 200 daily-customer photos
prepared in our independent engine and then assessed in Photomatic. The agreed
acceptance criterion is **dark green only** in all three vendor summary categories:
Image Quality, Face Size and Position, and Background. Light green, amber, red,
grey, missing and untested results do not count as a pass. Record the actual
displayed colour separately from numerical scores; do not infer it from a
filename, successful Save or the existence of an export.

Use consecutive, distinct, eligible customer cases and keep every first attempt
in the denominator. Do not discard difficult results or count repeated copies,
multiple edits or multiple enhancement levels of the same photo as additional
customers. Record each retry as another version of its existing case. A successful
retry does not erase the first failure.

For each case retain an anonymous case reference, camera original, processing
recipe and engine revision, final delivered JPEG with SHA-256, our measured
results and the exact JPEG digest those results describe, document profile,
Photomatic software/quality profile when known, Input Image Size and ID photo
data dimensions, all three observed colours, detailed failures/cautions and
staff review evidence. Store approved validation copies in a private evaluation
archive separate from temporary delivery jobs; normal job expiry is not a
long-term reference archive. Photos, customer details and private evidence are
not Git artifacts.

Photomatic must receive the exact JPEG prepared by our engine, under the same
document profile. A second vendor crop or edit can make the categories green
without validating our exported framing. Such a result is **not comparable**
for the full three-category claim until the assessed pixel region is established.
Record the result honestly and investigate it rather than counting it as an
exact-file pass. The observed 800 × 1120 input / 780 × 1093 analysis crop is an
unresolved example of this issue.

Pin the engine revision and recipes for the acceptance run. A change to a model,
prompt, strength, crop rule or threshold creates a new candidate revision.
Keep earlier failures, rerun the complete reference set, and also test fresh
customer cases that were not used to tune the candidate. The minimum milestone
is 200 distinct comparable cases with all three categories dark green on the
candidate under evaluation. Report totals for pending, not-comparable and
non-dark-green cases as well as passes; 200 selected successes are not a 200-case
perfect run.

Report preparation performance separately from checking accuracy. Vendor-green
outputs show that the tested preparation worked on those cases. To assess our
checker, compare its own classifications on the same final JPEG and include
known-defective test examples alongside the customer trial (blur, clipped
highlights, uneven lighting, glare, poor detail and incorrect framing). This
checks whether our engine notices defects as well as preparing attractive
photos. Unsupported measurements remain Not tested. Track results by document,
age group, capture conditions and the selected local or OpenAI recipe; do not
declare an untested recipe validated from another recipe's results.

After the milestone, expand reliance through a monitored staff pilot with
continued Photomatic spot comparisons and retained failure evidence. This
criterion governs validation of an engine revision; it does not change the
existing staff-responsibility code workflow or prove authority acceptance.

### Target for retiring Photomatic

The user proposed 1,000 successful paired matches as the target for fully
retiring the vendor dependency. Treat this as a decision milestone, rather than
proof based on sample count alone. Keep the same dark-green-only criterion for
accepted final photos in all three categories, exact delivered-file provenance,
distinct cases, recorded failures and reproducible engine/recipe versions.

The retirement evidence must also show that our checker detects defective
examples and does not give a green result to a vendor-failed defect without
investigation. Track missed defects and false alarms separately from the number
of accepted preparations. Keep tuning cases separate from held-out cases and
fresh shop cases. Compare equivalent assessed image regions; vendor recropping
must not silently repair our geometry for the comparison.

Scope the decision to the document profiles and processing recipes actually
validated. One thousand UK-online/local-tool matches do not establish the
accuracy of untested country profiles or the optional OpenAI setup. OpenAI
prompt/model changes and local-engine changes need their own regression and
fresh-case evidence. Unsupported metrics remain visibly untested until their
implementations are evaluated.

Before removing Photomatic from daily operation, independently verify the
remaining functions we use it for: document crop/export rules, physical
DE100-XD output, own UK code retrieval, repeatability and recovery after failures.
Retain the evidence and a practical rollback option through the transition.
The progression is 200 paired cases for the initial pilot, continued validation
towards 1,000, then a scoped retirement decision based on the complete results.

Build a paired reference set containing the same camera original, preparation, Photomatic export, vendor results and Tuttoprint measurements. Start with UK paper and online profiles and the shop's common countries. Include different skin tones, ages and capture conditions, especially clipped highlights, uneven illumination, blur, glasses, hair boundaries and poor source resolution.

Compare each measurement separately. MediaPipe geometry, local image statistics and any future OFIQ output have their own definitions and scales. Document the measured region, units, algorithm version, uncertainty and applicable document rule. Calibrate against both controlled defects and staff review; Photomatic is a useful reference, not absolute ground truth.

Track missed defects and false alarms, including differences by capture conditions and skin tone. Keep unsupported measurements as Not tested. Introduce independent replacements one metric at a time after their agreed evaluation criteria are met. Retain regional hotspot inspection and before-and-after evidence throughout.

## Implementation order and verification

| Order | Deliverable | Completion evidence |
|---|---|---|
| 1 | Verified Photomatic portrait export | Recorded settings, exact JPEG and repeatable export review |
| 2 | Preserved import and staff review | Byte equality, truthful measurement states and stale-review handling |
| 3 | Our UK issuance from that import | Exact same JPEG returned through authenticated retrieval |
| 4 | Windows helper | Reliable job matching and recovery tests |
| 5 | Shop pilot | Public retrieval verified and physical DE100-XD prints checked |
| In parallel after reference capture | Independent metric calibration | Per-metric evaluation with known limitations |

The first ordinary Save/import experiment succeeded with an 800 × 1120 JPEG. The next reference experiment must explain the 780 × 1093 analysis crop generated on reopening, establish the assessed pixel region and test representative prepared portraits and repeat exports. Then simplify the staff handoff with the Windows helper. Public retrieval and physical print validation remain separate milestones.

## Repository references

- [Runtime evaluation and proposed companion workflow](RUNTIME_EVALUATION.md)
- [Decoded document and quality settings](STANDARDS_DECODING.md)
- [Quality engine definitions](QUALITY_ENGINE.md)
- [Current enhancement tools](IMAGE_ENHANCER.md)
- [Print pipeline](PRINT_PIPELINE.md)
