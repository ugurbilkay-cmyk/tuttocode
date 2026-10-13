# Photomatic installation and native engine evaluation

Tested 12 October 2026 on the user's Apple Silicon Mac. The supplied installer
can complete in a local Windows compatibility environment, and its native
checking components can load. A complete quality assessment is not yet proven in
that Mac compatibility environment. A real sample check in the user's activated
Windows shop installation succeeded, establishing a working manual checker for
the temporary transition workflow.

## Environment and scope

The test used the existing Docker Desktop installation, a local Ubuntu 24.04
AMD64 image, Wine 9.0, an isolated 32-bit Wine prefix, Wine Mono 8.1.0 and a
virtual display. Container networking was disabled. The containers had no host
filesystem bind mounts during execution, no extra capabilities and no privilege
escalation. The shop's account configuration and credentials were not copied.
The original installation folders were not modified.

Wine provides [Windows API compatibility](https://www.winehq.org/), rather than a
complete Windows installation. [Wine Mono](https://github.com/wine-mono/wine-mono/releases/tag/wine-mono-8.1.0)
provided the compatible managed runtime in this test. These results establish
only this environment's behaviour; they are not a supported production setup or
evidence that quality scores match a real Windows station.

## Verified results

| Test | Result | Meaning |
|---|---|---|
| Supplied MSI with the bundled Microsoft .NET installer attempt | MSI initially failed its .NET prerequisite with error 1603 | Microsoft .NET Framework was not established by that attempt |
| Wine Mono installation and managed interface inspection | Both exited successfully | Managed code can execute in this compatibility environment |
| Supplied Photomatic MSI after compatible runtime installation | Installer exit 0; Photomatic files and native COM registrations created | The installer can complete here; this alone does not establish usable checks |
| Native FaceIt registrations | Successful | Both DLLs can register their COM classes |
| LocateG6, DibImage and FacePosition2 creation | HRESULT 0 for the actual IUnknown-based interfaces | The native components load and instantiate |
| Sample JPEG ReadFile | HRESULT 0 and true | The native image component can decode the supplied sample |
| EnableAllQualityMetricsEx | HRESULT 0 | The engine accepted the measurement configuration call |
| FindFaceAuto in the standalone native probe | HRESULT 0, false, engine error 5000 | Copy-protection state prevents this probe from producing face measurements |
| Initial full application startup | FontFamilyNotFound exception | Missing Windows-compatible fonts prevented the UI starting |
| Startup with Wine fonts | Setup Wizard visible | Registration/setup remains outstanding in the clean test environment |
| Startup after copying the supplied current Bin dependencies over the MSI installation | Setup Wizard visible | The current supplied application also reaches setup, without the shop's activated configuration |

The standalone error is `locerrCopyProtection = 5000` in the supplied interface
enumeration. This is not proof that the user's working Photomatic licence is
invalid. The native interface includes per-instance `SetLicense` initialization;
the normal vendor application and its activation need to be assessed together.
No licence keys were extracted, supplied to the probe or changed.

The first native smoke test incorrectly requested IDispatch. These components
expose IUnknown-based interfaces; correcting the requested interface made all
three creations succeed. The failed IDispatch test must not be reported as a
failure to load the engine.

## Source identity

The MSI identifies the older Photomatic7 FUJIFILM 7.5.2 installation. The supplied
current Bin directory was tested separately after that installation. Installed
FaceIt DLL hashes match the supplied reference DLLs.

| File | SHA-256 |
|---|---|
| Setup7.msi | `78d58f4f982acc9e896bc8ad40499d7116872d29d7c0d9f97d683c782619d3b8` |
| FaceItLocate.dll | `57c03a71372dedcdfafc90d3d22d36095f38fae7d518b9991c3a980438f49e4d` |
| FaceItMedia.dll | `0b973920bfef2e1af12f361a8ef7aa6b5aac26649887a22e024ebf31a53d7b53` |
| Wine Mono 8.1.0 x86 MSI | `0ed3ec533aef79b2f312155931cf7b1080009ac0c5b4c2bcfeb678ac948e0810` |

Local logs, screenshots, native smoke-test sources and private test copies are
kept in ignored `output/runtime-test`. Vendor binaries, sample photos, runtime
prefixes, remote-connection identifiers and activation information are not Git
artifacts. The temporary containers were stopped after the evaluation.

## Activated Windows application check

With the user's authorization, the working shop computer was accessed through
its existing remote-control service. Photomatic opened through the station's
normal IDStation launcher. Its initial photo screen was empty, with United
Kingdom Passport selected. The supplied SampleData JPEG was opened through the
ordinary file dialog.

The application displayed No irregularities detected and green image-quality,
face-size/position and background categories. The detailed measurement screen
contained numerical outputs including confidence 90, general quality 83,
sharpness 64, motion blur 80 and lighting uniformity 87. These are observed vendor
outputs, not independently validated accuracy estimates or our own scores.
One passing sample establishes operation, not full standard coverage.

No registration or online-service activation fields were edited. No printer job,
photo save/export, email or provider-code submission was initiated. The displayed
upload-credit count remained unchanged. Photomatic was closed after the sample
review, the print station's main screen remained running, and the remote session
was disconnected. Credentials and remote identifiers are excluded from this
record.

The user reports having previously installed Photomatic on another Windows PC,
where local features worked but online codes did not. They also identified a
second Windows computer at home as a potential test installation. Neither report
establishes the vendor's activation-transfer policy. Do not reassign the working
station's online activation as part of a local-checking installation test.

## Transition acceptance criteria

Use the activated Windows application to process a test image through its normal
workflow. Record the selected document, software version, individual measured
and untested results, staff decision, and exact exported digital JPEG. Do not
print, upload for a provider code or change the production station's configuration
as part of a read/check/export test unless specifically requested.

Transfer to TuttoCode uses the separate reviewed-file import path that
preserves the exported JPEG and links staff review evidence to its SHA-256. The
normal preparation pipeline can recrop/re-encode uploads. Code
hosting and real HMPO retrieval must be verified separately. Photomatic's local
check is not an authority acceptance certificate.

## Proposed companion app for our UK codes

The initial integration is an independent TuttoCode companion application and
an authenticated reviewed-file import, with staff using Photomatic's normal
Open file and Save controls. Photomatic continues to assess and frame photos;
TuttoCode records review evidence, hosts the final JPEG, generates our UK code
and produces our branded code slip. Its existing IDstation.online action remains
the vendor's separate route. No replacement of that button or undocumented
binary modification is part of this design.

The workflow is: our job and optional AI candidate, Photomatic document-specific
check, final digital portrait export, staff review of that export, immutable
TuttoCode import, technical file validation, and our UK code. Preparation occurs
before the Photomatic review. Changes after review invalidate it. Verify export
framing, resolution and encoding before deployment; an export is not necessarily
the same byte sequence as the picture assessed before Save. A print sheet from
Backup is not the digital portrait deliverable.

The import must preserve the original exported JPEG bytes. Preview rendering and
branded print layout can use separate derivatives; neither can replace the
issued file. Record staff identity, document, software/version when available,
image SHA-256, review time, observed results and any specific permitted allowance.
Label manual evidence as staff-attested Photomatic review. Missing, failed and
untested required checks cannot be silently converted to machine-verified passes.

The reviewed import now has a separate server path. Normal preparation uploads
invoke our processing, and their issuance may resize/re-encode the JPEG. Those
paths are separate from the preserved import. Validate JPEG decode,
dimensions and file bytes without editing the delivered image, and require
review of the current hash before issuance. An edit, replacement or country
change cancels prior approval; technical failures still block issuance.

A later Windows helper can exchange per-job files through dedicated folders,
wait for export writes to complete and upload through an authenticated HTTPS
API. It must not infer a pass from file presence, a filename or a green status
colour. The supplied settings allow Save even after failed checks. Automatic
quality approval requires a verified structured result interface and a proven
link between its assessed image and the final JPEG; that interface and licence
conditions have not been established. File handoff can be automated while staff
review remains mandatory.

Before shop use, verify the second Windows installation independently, final
export behaviour, review/byte-change failure cases, public HTTPS hosting, signed
HMPO retrieval, expiry and code-slip printing. This companion/import workflow
is not yet validated against a real Photomatic export. The local manual import
and exact-file issuance implementation is described in [staff instructions](REVIEWED_IMPORT.md).

## Local Windows demo export test on 13 October 2026

The local Windows installation displayed a loaded sample under United Kingdom
Online Renewal and working detailed measurements. Observed values included
input size 2133 by 3200, ID photo data 2005 by 2807, measurement confidence 100,
general quality 79, sharpness 58, motion blur 92, contrast 67 and hotspots 59.
Hotspots appeared light green. Neutral expression, mouth closed and smiling
displayed -1 with grey indicators; red eyes, glasses, age and gender displayed
not tested. These are vendor outputs, not independent accuracy estimates.

Clicking Save opened Enter a Demo License. The licence supplied by the user was
entered completely, but submission displayed: No printer detected. Please make
sure your printer is connected and turned ON! This system requires a valid
printer or a USB dongle! Closing the licence dialog also returned the hardware
notice. Successful licence activation and saving were not confirmed.

The user confirmed neither a printer nor a dongle is available at this test
location. No exported JPEG was obtained, so export dimensions, encoding,
repeatability and the subsequent review remain unverified. Resume this test
with vendor-authorized saving on the demo installation or through normal export
on the equipped shop installation. Do not interpret the working measurements
as proof that the complete companion workflow is operational.

The private baseline record is in ignored
output/photomatic-export-evaluation-20261013/baseline-and-export-status.json.
Licence keys, contact details and remote identifiers are excluded. No provider
code, physical print, email or OpenAI request was initiated by this test.
