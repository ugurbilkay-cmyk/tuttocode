# Photomatic template implementation

## Imported settings

The import contains all 208 country/document XML files and all 169 print XML
files from the supplied Photomatic7 installation, including the 48 loose installed
print templates. Source filenames and SHA-256 hashes are recorded in
`app/photomatic_catalog.json`. These are the installation's saved settings;
the import does not certify that every historical template is a current government
specification.

The importer reads the original bytes correctly even where the XML incorrectly
declares UTF-16. It exports only photo dimensions, geometry, background ranges,
digital/save/email dimensions, print positions and associated artwork. It does
not export passwords, issued code lists, camera drivers or executables.

To import a later installation:

```
python3 scripts/import_photomatic.py /path/to/Photomatic7
```

Every supplied country resolves to its named default print layout. If that layout
does not exist under the selected printer, the exact named installed layout or
another printer's matching named layout is available and its source printer is
shown. No missing layout was invented for this installation.

## Crop and export

Each photo keeps its selected country and print layout in the database. Existing
rows migrate to the UK passport profile without modifying previously issued
JPEGs or codes. The crop uses the country aspect ratio, eye-line percentage,
head-height or face-width target, and the template's minimum/maximum geometry.
AI segmentation locates the visible head top; landmarks provide a fallback.
Free-style templates do not require a face. Overlays and flags are the originals.

The print master retains the physical template aspect ratio at 30 pixels per
millimetre, so a small digital visa requirement does not degrade the printed photo.
For Save/Email, required digital dimensions take precedence; otherwise the
corresponding imported export template is used, adjusting the height when its
format differs from the country. Fitting preserves the face's proportions.
The original UK Save dimensions remain 600 x 771; the HMPO master remains
1050 x 1350. Ireland Passport online exports at 715 x 951.

Automatic colour correction, shadow softening and background evening default
to off, matching the saved installation's automatic-edit/face-shadow settings.
The controls remain available for explicit staff use. Existing environment
overrides still take priority; remove or set `AUTO_ADJUST`, `FIX_SHADOWS` and
`EVEN_BG` to false to use the matching defaults.

## Print

Printer sheets use the imported pixel canvas, DPI, active box coordinates,
physical photo dimensions, orientation, background and cut-mark settings.
Landscape boxes rotate the portrait clockwise. Borderless bleed is clipped at
the paper edge. UK Print2Hotfolder uses 1844 x 1240 pixels at 301 DPI, with six
45 x 35 mm landscape boxes at x=5/54/103 mm and y=4/66 mm.

A UK code occupies the template's photo-number position where enabled. The
separate code slip remains available. The print preview provides an actual-size
page and JPEG download; printer margins, borderless scaling and driver settings
must be checked on the real printer with a ruler. A physical print has not been
verified by the automated tests.

## Retention and access

Original shop uploads are retained only while pending, to support recropping.
They are deleted on code issuance, rejection or expiry. Photos with issued codes
cannot be recropped. All new staff actions require the existing admin password.
The existing signed HMPO retrieval endpoint and photo-code retention remain.

UK and Irish passport profiles are the only code-enabled categories. UK issuance
works through the existing HMPO integration. Irish issuance is explicitly disabled
until the Irish service connection is established; it cannot create a misleading
HMPO-style Irish code.

## Verification and limits

`test_photomatic.py` checks every country/default print reference, artwork files,
all 169 print renderings, six-photo rotation, representative crop/export dimensions,
eye-line position, crown detection, crop adjustment and legacy database migration.
`test_e2e.py` checks staff upload/recrop/export/email, code restrictions, pending
source cleanup, signed retrieval and expiry. SMTP is mocked; no test email is sent.
A real sample photo was also processed locally with the actual MediaPipe models
and reviewed in Safari, including the crop guides and corrected curly-hair framing.

This reproduces the imported settings and the main desktop workflow. It does not
reproduce Photomatic's proprietary FaceIt/ICAO scoring algorithm, native Canon
tethering, printer-driver/device controls or the external France ANTS/German
driving-licence submission applications. The three special-mode templates show
that their external step is required. Browser camera capture and file upload are
available. Matching the legacy engine exactly requires paired original/output
photos and additional calibration; the AI checks support staff review.
