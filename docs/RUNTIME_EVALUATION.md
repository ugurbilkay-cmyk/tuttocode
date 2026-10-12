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

Any transfer to TuttoCode needs an explicit reviewed-file import path that
preserves the approved JPEG and links review evidence to its SHA-256. Our current
pipeline can recrop/re-encode imports; it is not yet that transfer path. Code
hosting and real HMPO retrieval must be verified separately. Photomatic's local
check is not an authority acceptance certificate.
