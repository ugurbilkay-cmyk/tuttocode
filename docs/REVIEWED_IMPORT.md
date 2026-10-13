# Photomatic export and staff review

Tuttoprint can now import a digital JPEG exported by Photomatic, record staff review, and issue its own UK code using that exact JPEG. This is a manual handoff. Photomatic results are entered by staff; no automatic vendor score extraction is claimed.

## Prepare and import a photo

1. Prepare the camera photo in the normal studio screen. Apply all pending changes and finish any OpenAI preview review.
2. Click Save for Photomatic. This downloads the prepared master with a job reference, without another Save-profile resize.
3. Open that file in Photomatic, select the matching document and review its individual checks.
4. Save a single digital portrait using a unique filename. Reopen it in Photomatic and record both Input Image Size and ID photo data dimensions. Photomatic may analyse a new crop on reopening; its displayed scores then describe that crop, rather than necessarily the full saved JPEG. Separately inspect the exact imported JPEG and record this distinction in the review notes.
5. Return to the preparation job and click Import reviewed export. Select the saved JPEG and confirm the document. Import unchanged JPEG creates a separate linked review job.
6. Record the operator, actual Photomatic profile, category results, individual measurements and final-photo confirmations. Save staff review.
7. For a UK document, confirm the recorded review and issue the code. Failed checks or untested categories remain visible and staff can proceed under recorded responsibility. Irish jobs retain the external-provider route.

Standalone files can also be imported from Import Photomatic export in the studio navigation. A print sheet, screenshot or prepared master without Photomatic review must not be recorded as a reviewed vendor export.

## What the system preserves

The original imported JPEG bytes, embedded metadata and file digest remain unchanged. Save and photo email use those bytes. UK issuance copies the same bytes into the immutable code file; authenticated retrieval verifies its digest before returning it. Preview images and print sheets are separate derivatives.

A linked import copies available camera-original evidence and records the preparation revision, prepared-file digest, processing options, measurements and checks. A failed source-resolution check remains visible even if the imported portrait is enlarged. The original preparation job remains separate.

The review records the signed-in account plus the operator name entered by staff. With the current shared Basic-auth account, the operator name is an attestation rather than separately authenticated personal identity. Separate staff accounts remain a production improvement.

## Results and decisions

Pass, Caution, Fail and Not tested are explicit states. Values start empty and statuses start Not tested. Vendor scores retain their original scale; importing a photo does not invent measured passes. Recorded results are labelled as staff evidence rather than automatic verification.

The file panel independently checks JPEG readability, dimensions and encoding. UK file dimensions and byte-size warnings do not resize the photo and remain subject to staff responsibility. Child, disability, health and other decision contexts can be recorded with notes without erasing any observed failure.

An imported review job cannot be enhanced or recropped in place. Changes belong in a new preparation/export job because they would invalidate the existing evidence. Review revisions prevent stale forms from issuing a code, and changed files fail their integrity check. Issued reviews are read-only. Retention cleanup removes the imported portrait, preview, code file and copied camera evidence.

## Validation status

The preserved-import suite covers byte equality, signed retrieval with a local test key, tampered files, stale and concurrent reviews, untested results, operator responsibility, source-resolution evidence, retained originals, exact email attachments with mocked sending, non-UK issuance, EXIF orientation and expiry cleanup.

On 13 October 2026, the equipped Windows station saved the installed vendor sample as an 800 × 1120 RGB JPEG (515,145 bytes) under United Kingdom Online Renewal. After transfer, a separate local review job imported it; both Save exact JPEG and the full-photo response returned byte-identical data. Its SHA-256 is `4f8ac0ff648962da806422e83db9a07a621f528d1a09f13b86d0210bc5e353a9`. No customer review was attested and no code was issued for this sample.

Reopening that export in Photomatic produced ID photo data at 780 × 1093. Some displayed values changed, including hotspots from 70 before export to 69 after reopening. This confirms the manual file handoff, and also establishes why staff must record the analysis context. It does not establish an automatic, exact-file vendor pass or equivalent ICAO calculations in our engine. Public HMPO retrieval and physical DE100-XD printing remain production validation steps.
