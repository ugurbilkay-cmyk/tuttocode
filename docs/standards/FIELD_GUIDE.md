# Stored photo standards field guide

Generated from the supplied reference installation. Read [the decoding notes](../STANDARDS_DECODING.md) for verified application logic and unresolved engine behaviour.

## Country fields

| XML field | Meaning | Unit |
|---|---|---|
| `App2Start` | Legacy external application reference; basename only | filename |
| `BackB` | Preferred background B channel | 0–255 channel value |
| `BackBmax` | Maximum background B channel | 0–255 channel value |
| `BackBmin` | Minimum background B channel | 0–255 channel value |
| `BackG` | Preferred background G channel | 0–255 channel value |
| `BackGmax` | Maximum background G channel | 0–255 channel value |
| `BackGmin` | Minimum background G channel | 0–255 channel value |
| `BackR` | Preferred background R channel | 0–255 channel value |
| `BackRmax` | Maximum background R channel | 0–255 channel value |
| `BackRmin` | Minimum background R channel | 0–255 channel value |
| `BackgroundColor` | Optional serialized colour value; not a quality score | serialized colour |
| `BackgroundColorMax` | Optional serialized upper colour bound | serialized colour |
| `BackgroundColorMin` | Optional serialized lower colour bound | serialized colour |
| `DefaultPrintTemplateName` | Default sheet layout reference | filename |
| `EmailTemplateName` | Default digital Email profile reference | filename |
| `FlagFileName` | Country flag artwork reference | filename |
| `Format` | Serialized format selection | enum name |
| `ISOtemplatename` | Country quality-profile override reference | filename |
| `LandCode` | Legacy identifier; do not assume this is an ISO country code | identifier |
| `LandName` | Country/document display label | text |
| `OverlayFileName` | Overlay artwork reference | filename |
| `RadioBtnlabel` | Label for the special workflow action | text |
| `RequiredDigitalFileSizeMax` | Maximum digital JPEG size; exact byte conversion requires tracing | legacy KB |
| `RequiredDigitalFileSizeMin` | Minimum digital JPEG size; exact byte conversion requires tracing | legacy KB |
| `RequiredDigitalHeight` | Required digital export height; -1 means no explicit requirement | pixels |
| `RequiredDigitalWidth` | Required digital export width; -1 means no explicit requirement | pixels |
| `SaveTemplateName` | Default digital Save profile reference | filename |
| `URLforSpecs` | Stored specification link; may be stale or refer to another country | URL |
| `bBlockBGtool` | Disable background editing for this document | boolean |
| `bDoAutoCrop` | Run automatic crop for this document | boolean |
| `bDoICAOcheck` | Run automatic quality checking for this document | boolean |
| `bForceCutmarks` | Document requests cut marks on its print sheet | boolean |
| `bGlassesForbidden` | Document policy forbids glasses; independent of detecting glare | boolean |
| `bSpecialMode` | Additional document workflow enabled | boolean |
| `bUseFaceHeight` | Enable height-based geometry | boolean |
| `bUseFaceWidth` | Enable width-based geometry; do not discard when height is also enabled | boolean |
| `bUseISOtemplate` | Use the country's named quality profile instead of the global selection | boolean |
| `bUseOverlay` | Display the reference guide overlay | boolean |
| `bUseZoomFactor` | Use the legacy zoom-factor framing mode | boolean |
| `iCanvasHeight` | Physical photo height | mm |
| `iCanvasWidth` | Physical photo width | mm |
| `iEyesHeight` | Target eye-line position measured from the photo top | % of photo height |
| `iEyesHeightMax` | Maximum eye-line position from the photo top | % of photo height |
| `iEyesHeightMin` | Minimum eye-line position from the photo top | % of photo height |
| `iFaceHeight` | Target head/face height; landmark/crown definition needs engine tracing | % of photo height |
| `iFaceHeightMax` | Maximum head/face height | % of photo height |
| `iFaceHeightMin` | Minimum head/face height | % of photo height |
| `iFaceWidth` | Target face width | % of photo width |
| `iFaceWidthMax` | Maximum face width | % of photo width |
| `iFaceWidthMin` | Minimum face width | % of photo width |
| `iFreeFrameHeight` | Free-frame parameter; physical interpretation not yet traced | legacy parameter |
| `iFreeFrameWidth` | Free-frame parameter; physical interpretation not yet traced | legacy parameter |
| `iRadioButton2Use` | Legacy special-mode button selection; enum mapping not established | selector |
| `iZoomFactor` | Legacy zoom factor; not a universal physical measurement | legacy factor |
| `strFormat` | Named aspect-ratio format | enum name |

## Quality settings one by one

A switch enables a check. A numeric score threshold does not define the algorithm that produces that score.

| XML field | Default | NOlevels | Meaning | Unit |
|---|---|---|---|---|
| `CheckAge` | true | absent | Enable age estimate | boolean |
| `CheckArtefacts` | true | false | Enable image artefacts | boolean |
| `CheckBackBright` | true | false | Enable background brightness | boolean |
| `CheckBackColor` | true | false | Enable background colour | boolean |
| `CheckBackShadows` | true | false | Enable background shadows | boolean |
| `CheckBackUniform` | true | false | Enable background uniformity | boolean |
| `CheckCompressed` | true | false | Enable compression quality | boolean |
| `CheckConfidence` | true | false | Enable measurement confidence | boolean |
| `CheckContrast` | true | false | Enable contrast | boolean |
| `CheckExpression` | true | false | Enable neutral expression | boolean |
| `CheckEyeAngle` | true | false | Enable eye-line tilt | boolean |
| `CheckEyeDistance` | true | false | Enable distance between eyes | boolean |
| `CheckEyes` | true | false | Enable eye detection | boolean |
| `CheckEyesClear` | true | false | Enable eye detail visible | boolean |
| `CheckEyesNotFacingCamera` | true | absent | Enable gaze direction | boolean |
| `CheckEyesOpen` | true | false | Enable eyes open | boolean |
| `CheckFace` | true | false | Enable face detection | boolean |
| `CheckFaceFree` | true | false | Enable face unobstructed | boolean |
| `CheckFaceLarge` | true | false | Enable face too large | boolean |
| `CheckFaceNotFacingCamera` | false | absent | Enable face orientation | boolean |
| `CheckFacePositionHigh` | true | false | Enable face too high | boolean |
| `CheckFacePositionLeft` | true | false | Enable face too far left | boolean |
| `CheckFacePositionLow` | true | false | Enable face too low | boolean |
| `CheckFacePositionRight` | true | false | Enable face too far right | boolean |
| `CheckFaceSmall` | true | false | Enable face too small | boolean |
| `CheckGenQuality` | true | false | Enable general image quality | boolean |
| `CheckGender` | true | absent | Enable gender estimate | boolean |
| `CheckGlare` | true | false | Enable glasses glare | boolean |
| `CheckGlasses` | true | absent | Enable glasses detection | boolean |
| `CheckHat` | false | false | Enable headwear | boolean |
| `CheckHotspots` | true | false | Enable bright hotspots | boolean |
| `CheckInputSize` | true | false | Enable input pixel dimensions | boolean |
| `CheckInterlaced` | true | true | Enable interlacing | boolean |
| `CheckMotionblur` | true | false | Enable motion blur | boolean |
| `CheckMouthClosed` | true | false | Enable mouth closed | boolean |
| `CheckMultipleFaces` | true | absent | Enable multiple faces | boolean |
| `CheckNoise` | true | false | Enable image noise | boolean |
| `CheckOverexposed` | true | false | Enable overexposure | boolean |
| `CheckPose` | true | false | Enable face pose | boolean |
| `CheckRealface` | true | absent | Enable real-face check | boolean |
| `CheckRedEyes` | true | absent | Enable red eye | boolean |
| `CheckShadowInEyes` | true | false | Enable eye shadows | boolean |
| `CheckShadowInFace` | true | false | Enable face shadows | boolean |
| `CheckSharpness` | true | false | Enable sharpness | boolean |
| `CheckSkinColor` | true | false | Enable skin colour | boolean |
| `CheckSmiling` | true | false | Enable smiling | boolean |
| `CheckSuitable` | true | false | Enable biometric suitability | boolean |
| `CheckSunGlases` | true | false | Enable sunglasses/dark eye area | boolean |
| `CheckUnderexposed` | true | false | Enable underexposure | boolean |
| `CheckUniform` | true | false | Enable uniform lighting | boolean |
| `MaxAngle` | 6 | 5 | Maximum absolute eye-line tilt | degrees |
| `MinArtefacts` | 30 | 30 | Legacy acceptance threshold for MinArtefacts | legacy engine score |
| `MinBackBright` | 30 | 30 | Legacy acceptance threshold for MinBackBright | legacy engine score |
| `MinBackColor` | 30 | 30 | Legacy acceptance threshold for MinBackColor | legacy engine score |
| `MinBackShadows` | 30 | 30 | Legacy acceptance threshold for MinBackShadows | legacy engine score |
| `MinBackUniform` | 30 | 30 | Legacy acceptance threshold for MinBackUniform | legacy engine score |
| `MinCompressed` | 30 | 30 | Legacy acceptance threshold for MinCompressed | legacy engine score |
| `MinConfidence` | 30 | 30 | Legacy acceptance threshold for MinConfidence | legacy engine score |
| `MinContrast` | 30 | 30 | Legacy acceptance threshold for MinContrast | legacy engine score |
| `MinEyesNotFacingCamera` | 30 | absent | Legacy acceptance threshold for MinEyesNotFacingCamera | legacy engine score |
| `MinEyesOpen` | 39 | 30 | Legacy acceptance threshold for MinEyesOpen | legacy engine score |
| `MinEyesclear` | 30 | 30 | Legacy acceptance threshold for MinEyesclear | legacy engine score |
| `MinFaceLarge` | 30 | 30 | Legacy acceptance threshold for MinFaceLarge | legacy engine score |
| `MinFaceNotFacingCamera` | 30 | absent | Legacy acceptance threshold for MinFaceNotFacingCamera | legacy engine score |
| `MinFacePositionHigh` | 30 | 30 | Legacy acceptance threshold for MinFacePositionHigh | legacy engine score |
| `MinFacePositionLeft` | 30 | 30 | Legacy acceptance threshold for MinFacePositionLeft | legacy engine score |
| `MinFacePositionLow` | 30 | 30 | Legacy acceptance threshold for MinFacePositionLow | legacy engine score |
| `MinFacePositionRight` | 30 | 30 | Legacy acceptance threshold for MinFacePositionRight | legacy engine score |
| `MinFaceSmall` | 30 | 30 | Legacy acceptance threshold for MinFaceSmall | legacy engine score |
| `MinFacefree` | 30 | 30 | Legacy acceptance threshold for MinFacefree | legacy engine score |
| `MinGenQuality` | 30 | 30 | Legacy acceptance threshold for MinGenQuality | legacy engine score |
| `MinGlarefree` | 30 | 30 | Legacy acceptance threshold for MinGlarefree | legacy engine score |
| `MinGlasses` | 30 | absent | Legacy acceptance threshold for MinGlasses | legacy engine score |
| `MinHat` | 30 | 30 | Legacy acceptance threshold for MinHat | legacy engine score |
| `MinHotspots` | 36 | 36 | Legacy acceptance threshold for MinHotspots | legacy engine score |
| `MinInputHeight` | 400 | 800 | Minimum input height | pixels |
| `MinInputWidth` | 300 | 600 | Minimum input width | pixels |
| `MinInterlaced` | 30 | 30 | Legacy acceptance threshold for MinInterlaced | legacy engine score |
| `MinMotionblur` | 30 | 30 | Legacy acceptance threshold for MinMotionblur | legacy engine score |
| `MinNeutralExpression` | 30 | 30 | Legacy acceptance threshold for MinNeutralExpression | legacy engine score |
| `MinNoise` | 18 | 18 | Legacy acceptance threshold for MinNoise | legacy engine score |
| `MinOverexposed` | 36 | 36 | Legacy acceptance threshold for MinOverexposed | legacy engine score |
| `MinPose` | 22 | 7 | Legacy acceptance threshold for MinPose | legacy engine score |
| `MinRedEyes` | 30 | absent | Legacy acceptance threshold for MinRedEyes | legacy engine score |
| `MinSharpness` | 18 | 18 | Legacy acceptance threshold for MinSharpness | legacy engine score |
| `MinSkinColor` | 30 | 30 | Legacy acceptance threshold for MinSkinColor | legacy engine score |
| `MinSmiling` | 30 | 30 | Legacy acceptance threshold for MinSmiling | legacy engine score |
| `MinSuitable` | 30 | 30 | Legacy acceptance threshold for MinSuitable | legacy engine score |
| `MinSunglases` | 30 | 30 | Legacy acceptance threshold for MinSunglases | legacy engine score |
| `MinUnderexposed` | 30 | 30 | Legacy acceptance threshold for MinUnderexposed | legacy engine score |
| `MinUniform` | 30 | 30 | Legacy acceptance threshold for MinUniform | legacy engine score |
| `MineyeDistance` | 90 | 100 | Minimum inter-eye distance | pixels |
| `MouthClosed` | 30 | 30 | Legacy acceptance threshold for MouthClosed | legacy engine score |
| `RefBackColorBlue` | 230 | 230 | Global reference background colour channel; country also has its own bounds | 0–255 channel value |
| `RefBackColorGreen` | 230 | 230 | Global reference background colour channel; country also has its own bounds | 0–255 channel value |
| `RefBackColorRed` | 230 | 230 | Global reference background colour channel; country also has its own bounds | 0–255 channel value |
| `ShadowInEyes` | 30 | 30 | Legacy acceptance threshold for ShadowInEyes | legacy engine score |
| `ShadowInFace` | 30 | 30 | Legacy acceptance threshold for ShadowInFace | legacy engine score |

Absence in XML does not necessarily disable a check. Constructor defaults and effective values are recorded in profiles.json. For example, CheckInputFormat is absent from all three XML profiles but defaults true in this library.

## All country and document profiles

Complete individual fields and default origins are in [profiles.json](profiles.json). The table shows stored values, including inactive geometry ranges.

| Profile | Photo mm | Head range % | Eyes from top % | Geometry enabled | Quality profile |
|---|---|---|---|---|---|
| 25x33 generic | 30 × 40 | 64–78 | 40–52 | height | DefaultISOlevels.XML |
| 25x35 generic | 25 × 35 | 64–78 | 40–52 | height | DefaultISOlevels.XML |
| 26x32 generic | 26 × 32 | 60–78 | 42–52 | height | DefaultISOlevels.XML |
| 30x30 generic | 30 × 30 | 64–78 | 40–52 | height | DefaultISOlevels.XML |
| 30x35 generic | 30 × 35 | 64–78 | 40–52 | height | DefaultISOlevels.XML |
| 30x40 generic | 30 × 40 | 64–78 | 40–52 | height | DefaultISOlevels.XML |
| 30x45 generic | 30 × 45 | 64–78 | 40–52 | height | DefaultISOlevels.XML |
| 35x35 generic | 35 × 35 | 72–85 | 40–55 | height | DefaultISOlevels.XML |
| 35x40 generic | 35 × 40 | 72–85 | 40–55 | height | DefaultISOlevels.XML |
| 35x45 generic | 35 × 45 | 67–80 | 40–54 | height | DefaultISOlevels.XML |
| 35x50 generic | 35 × 50 | 72–85 | 40–55 | height | DefaultISOlevels.XML |
| 36x47 generic | 36 × 47 | 68–77 | 40–52 | height | DefaultISOlevels.XML |
| 40x40 generic | 40 × 40 | 50–78 | 42–51 | height | DefaultISOlevels.XML |
| 40x45 generic | 40 × 45 | 64–78 | 40–52 | height | DefaultISOlevels.XML |
| 40x50 generic | 40 × 50 | 50–78 | 42–51 | height | DefaultISOlevels.XML |
| 40x55 generic | 40 × 55 | 50–78 | 42–51 | height | DefaultISOlevels.XML |
| 40x60 generic | 40 × 60 | 54–68 | 36–51 | height | DefaultISOlevels.XML |
| 45x45 generic | 45 × 45 | 72–85 | 40–55 | height | DefaultISOlevels.XML |
| 45x55 generic | 45 × 55 | 50–78 | 42–51 | height | DefaultISOlevels.XML |
| 50x60 generic | 50 × 60 | 50–78 | 42–51 | height | DefaultISOlevels.XML |
| 51x51 generic | 50 × 50 | 50–68 | 32–44 | height | DefaultISOlevels.XML |
| Afghanistan Passport | 35 × 45 | 68–80 | 42–54 | height | DefaultISOlevels.XML |
| Albania Passport | 40 × 50 | 50–78 | 42–51 | height | DefaultISOlevels.XML |
| Algeria Passport | 35 × 45 | 60–80 | 42–53 | height | DefaultISOlevels.XML |
| Andorra Passport | 35 × 40 | 60–80 | 42–54 | height | DefaultISOlevels.XML |
| Angola Passport | 50 × 50 | 50–68 | 32–44 | height | DefaultISOlevels.XML |
| Argentina Passport | 38 × 38 | 65–80 | 45–55 | height | DefaultISOlevels.XML |
| Armenia Passport | 35 × 45 | 55–67 | 42–51 | height | DefaultISOlevels.XML |
| Australia AAA IDP online | 35 × 45 | 71–80 | 42–54 | height | DefaultISOlevels.XML |
| Australia Passport DFAT | 35 × 45 | 71–80 | 42–54 | height | DefaultISOlevels.XML |
| Australia Passport | 35 × 45 | 71–80 | 42–54 | height | DefaultISOlevels.XML |
| Australia VISA | 35 × 45 | 71–80 | 42–54 | height | DefaultISOlevels.XML |
| Australia WWC online | 35 × 45 | 71–80 | 42–54 | height | DefaultISOlevels.XML |
| Austria Passport | 35 × 45 | 66–80 | 44–53 | height | DefaultISOlevels.XML |
| Austria VISA | 35 × 45 | 66–80 | 44–53 | height | DefaultISOlevels.XML |
| Bahrein Passport | 40 × 60 | 50–63 | 32–44 | height | DefaultISOlevels.XML |
| Bahrein Visa | 40 × 60 | 50–63 | 32–44 | height | DefaultISOlevels.XML |
| Belarus Passport | 40 × 50 | 63–71 | 41–50 | height | DefaultISOlevels.XML |
| Belarus VISA | 40 × 50 | 63–71 | 41–50 | height | DefaultISOlevels.XML |
| Belgium Passport | 35 × 45 | 70–80 | 42–53 | height | DefaultISOlevels.XML |
| Bhutan Passport | 35 × 45 | 58–66 | 42–54 | width | DefaultISOlevels.XML |
| Bhutan VISA | 35 × 45 | 58–66 | 42–54 | width | DefaultISOlevels.XML |
| Bosnia Herzegovina Passport | 35 × 45 | 68–80 | 42–52 | height | DefaultISOlevels.XML |
| Brasil eVisa online | 35 × 45 | 50–70 | 32–52 | height | DefaultISOlevels.XML |
| Brasil Passport | 50 × 70 | 44–52 | 32–40 | height | DefaultISOlevels.XML |
| Brasil Visa | 35 × 45 | 50–68 | 32–52 | height | DefaultISOlevels.XML |
| Bulgaria Passport | 35 × 45 | 68–80 | 42–52 | height | DefaultISOlevels.XML |
| Bulgaria VISA | 35 × 45 | 68–80 | 42–52 | height | DefaultISOlevels.XML |
| Cambodia eVisa online | 35 × 45 | 68–80 | 42–54 | height | DefaultISOlevels.XML |
| Cambodia Passport | 35 × 45 | 68–80 | 42–54 | height | DefaultISOlevels.XML |
| Cambodia VISA | 38 × 38 | 65–80 | 45–55 | height | DefaultISOlevels.XML |
| Canada Citizenship online | 50 × 70 | 44–52 | 32–40 | height | DefaultISOlevels.XML |
| Canada Citizenship | 50 × 70 | 44–52 | 32–40 | height | DefaultISOlevels.XML |
| Canada eVisa online | 50 × 70 | 44–52 | 32–40 | height | DefaultISOlevels.XML |
| Canada Firearms online 3x4 | 30 × 40 | 43–62 | 48–55 | height | DefaultISOlevels.XML |
| Canada Firearms online | 45 × 57 | 43–62 | 48–55 | height | DefaultISOlevels.XML |
| Canada Firearms | 45 × 57 | 43–62 | 48–55 | height | DefaultISOlevels.XML |
| Canada HandyDART online | 32 × 32 | 65–80 | 45–55 | height | DefaultISOlevels.XML |
| Canada Passport online | 40 × 60 | 45–50 | 36–46 | height | DefaultISOlevels.XML |
| Canada Passport | 50 × 70 | 44–52 | 32–40 | height | DefaultISOlevels.XML |
| Canada Perm Residence online | 50 × 70 | 44–52 | 32–40 | height | DefaultISOlevels.XML |
| Canada Perm Residence | 50 × 70 | 44–52 | 32–40 | height | DefaultISOlevels.XML |
| Canada VISA | 35 × 45 | 69–80 | 40–60 | height | DefaultISOlevels.XML |
| China eVISA online | 30 × 40 | 58–69 | 38–50 | width | DefaultISOlevels.XML |
| China Passport Online | 33 × 48 | 58–69 | 34–55 | height | DefaultISOlevels.XML |
| China Passport | 33 × 48 | 58–69 | 34–55 | height | DefaultISOlevels.XML |
| China VISA | 33 × 48 | 58–69 | 34–55 | height | DefaultISOlevels.XML |
| Colombia VISA | 30 × 40 | 53–70 | 45–55 | height | DefaultISOlevels.XML |
| Croatia Passport | 35 × 45 | 70–80 | 42–53 | height | DefaultISOlevels.XML |
| Cyprus Passport | 35 × 45 | 70–80 | 42–53 | height | DefaultISOlevels.XML |
| Czech Passport | 35 × 45 | 68–80 | 42–54 | height | DefaultISOlevels.XML |
| Denmark Passport | 35 × 45 | 67–80 | 40–54 | height | DefaultISOlevels.XML |
| DVA online | 50 × 70 | 44–58 | 34–48 | height | DefaultISOlevels.XML |
| Egypt Passport | 40 × 60 | 50–63 | 32–44 | height | DefaultISOlevels.XML |
| Egypt Visa | 40 × 60 | 50–63 | 32–44 | height | DefaultISOlevels.XML |
| Estonia Passport online | 40 × 50 | 70–80 | 42–52 | height | DefaultISOlevels.XML |
| Estonia Passport | 40 × 50 | 70–80 | 42–52 | height | DefaultISOlevels.XML |
| Estonia VISA | 40 × 50 | 70–80 | 42–52 | height | DefaultISOlevels.XML |
| Finland Passport | 36 × 47 | 68–77 | 40–52 | height | DefaultISOlevels.XML |
| Finland VISA | 36 × 47 | 68–77 | 40–52 | height | DefaultISOlevels.XML |
| France ANTS online | 35 × 45 | 68–80 | 42–54 | height | DefaultISOlevels.XML |
| France Passport | 35 × 45 | 68–80 | 42–54 | height | DefaultISOlevels.XML |
| Free Style 35x45 | 80 × 120 | 30–88 | 32–44 | free-style | DefaultISOlevels.XML |
| Free Style 50x70 | 80 × 120 | 30–88 | 32–44 | free-style | DefaultISOlevels.XML |
| Free Style | 80 × 120 | 30–88 | 32–44 | free-style | DefaultISOlevels.XML |
| Germany Fuhrerschein online | 35 × 45 | 70–82 | 37–52 | height | DefaultISOlevels.XML |
| Germany Passport BW | 35 × 45 | 71–82 | 37–52 | height | DefaultISOlevels.XML |
| Germany Passport | 35 × 45 | 71–82 | 37–52 | height | DefaultISOlevels.XML |
| Germany VISA | 35 × 45 | 71–80 | 35–52 | height | DefaultISOlevels.XML |
| Ghana Passport | 50 × 50 | 50–68 | 32–44 | height | DefaultISOlevels.XML |
| Greece ID online 40x50 | 40 × 50 | 60–74 | 38–48 | height | DefaultISOlevels.XML |
| Greece Passport | 40 × 60 | 50–60 | 32–44 | height | DefaultISOlevels.XML |
| Hongkong Passport online | 30 × 40 | 64–72 | 40–56 | height | DefaultISOlevels.XML |
| Hongkong Passport | 40 × 50 | 64–72 | 40–56 | height | DefaultISOlevels.XML |
| Hongkong VISA online | 30 × 40 | 64–72 | 40–56 | height | DefaultISOlevels.XML |
| Hongkong VISA | 40 × 50 | 64–72 | 40–56 | height | DefaultISOlevels.XML |
| Hungary Passport | 35 × 45 | 69–80 | 40–53 | height | DefaultISOlevels.XML |
| Iceland Passport | 35 × 45 | 70–80 | 41–53 | height | DefaultISOlevels.XML |
| India eVisa online | 50 × 50 | 50–68 | 32–44 | height | DefaultISOlevels.XML |
| India PAN card | 50 × 70 | 44–52 | 32–40 | height | DefaultISOlevels.XML |
| India Passport online | 35 × 45 | 69–84 | 42–52 | height | DefaultISOlevels.XML |
| India Passport | 50 × 50 | 50–68 | 32–44 | height | DefaultISOlevels.XML |
| India VISA | 50 × 50 | 50–68 | 32–44 | height | DefaultISOlevels.XML |
| Indonesia eVisa online | 40 × 60 | 50–60 | 30–50 | height | DefaultISOlevels.XML |
| Indonesia Passport | 35 × 45 | 74–85 | 35–52 | height | DefaultISOlevels.XML |
| Indonesia VISA | 35 × 45 | 74–85 | 35–52 | height | DefaultISOlevels.XML |
| Iran e-Visa online | 40 × 60 | 70–80 | 42–56 | height | DefaultISOlevels.XML |
| Iran Passport | 30 × 40 | 54–68 | 36–51 | height | DefaultISOlevels.XML |
| Iraq Passport | 35 × 45 | 68–80 | 42–54 | height | DefaultISOlevels.XML |
| Iraq Visa | 35 × 45 | 68–80 | 42–54 | height | DefaultISOlevels.XML |
| Ireland Passport online | 30 × 40 | 55–73 | 36–54 | height, width | DefaultISOlevels.XML |
| Ireland Passport | 35 × 45 | 45–54 | 35–45 | height | DefaultISOlevels.XML |
| Ireland Public Services Card online | 30 × 40 | 55–73 | 36–54 | height, width | DefaultISOlevels.XML |
| Ireland VISA | 35 × 45 | 71–80 | 35–51 | height | DefaultISOlevels.XML |
| Irish TAXI | 70 × 100 | 68–88 | 35–55 | height | DefaultISOlevels.XML |
| Israel Passport | 50 × 50 | 50–68 | 32–44 | height | DefaultISOlevels.XML |
| Italia Passport | 35 × 40 | 60–80 | 42–54 | height | DefaultISOlevels.XML |
| Jamaica Passport | 35 × 45 | 65–75 | 37–54 | height | DefaultISOlevels.XML |
| Japan e-Visa online | 35 × 45 | 70–80 | 42–54 | height | DefaultISOlevels.XML |
| Japan Passport | 35 × 45 | 71–80 | 43–54 | height | DefaultISOlevels.XML |
| Japan VISA 45x45 | 45 × 45 | 50–68 | 32–44 | height | DefaultISOlevels.XML |
| Japan VISA 51x51 | 50 × 50 | 50–68 | 32–44 | height | DefaultISOlevels.XML |
| Japan Visa | 50 × 50 | 50–68 | 32–44 | height | DefaultISOlevels.XML |
| Kenya Passport | 40 × 50 | 60–78 | 42–52 | height | DefaultISOlevels.XML |
| Korea Passport | 35 × 45 | 56–78 | 40–60 | height | DefaultISOlevels.XML |
| Korea VISA | 50 × 50 | 60–70 | 42–58 | height | DefaultISOlevels.XML |
| Kosovo Passport | 35 × 45 | 70–80 | 42–53 | height | DefaultISOlevels.XML |
| Kuwait Passport 40x50 | 40 × 50 | 50–78 | 42–51 | height | DefaultISOlevels.XML |
| Kuwait Passport Renewal | 40 × 60 | 50–63 | 32–44 | height | DefaultISOlevels.XML |
| Kuwait Visa | 40 × 60 | 50–63 | 32–44 | height | DefaultISOlevels.XML |
| Laos Passport | 40 × 60 | 54–68 | 36–51 | height | DefaultISOlevels.XML |
| Latvia Passport | 35 × 45 | 60–70 | 40–50 | height | DefaultISOlevels.XML |
| Lithuania Passport | 40 × 60 | 50–60 | 32–44 | height | DefaultISOlevels.XML |
| Luxembourgh Passport | 35 × 45 | 71–80 | 35–51 | height | DefaultISOlevels.XML |
| Malaysia eVISA online | 70 × 100 | 60–70 | 42–55 | height | DefaultISOlevels.XML |
| Malaysia Passport | 70 × 100 | 50–60 | 42–55 | height | DefaultISOlevels.XML |
| Malaysia VISA | 70 × 100 | 55–70 | 42–55 | height | DefaultISOlevels.XML |
| Malta Passport | 35 × 45 | 64–75 | 35–54 | height | DefaultISOlevels.XML |
| Mexico Passport | 35 × 45 | 70–80 | 40–60 | height | DefaultISOlevels.XML |
| Mexico Permanent Resident | 35 × 45 | 70–80 | 40–60 | height | DefaultISOlevels.XML |
| Mexico VISA | 35 × 45 | 70–80 | 40–60 | height | DefaultISOlevels.XML |
| Montenegro Passport | 35 × 45 | 71–80 | 35–51 | height | DefaultISOlevels.XML |
| Morocco Passport | 35 × 45 | 68–78 | 42–53 | height | DefaultISOlevels.XML |
| Myanmar Visa | 38 × 46 | 65–80 | 45–55 | height | DefaultISOlevels.XML |
| Namibia Passport | 35 × 45 | 58–66 | 42–54 | width | DefaultISOlevels.XML |
| Namibia Visa | 35 × 45 | 58–66 | 42–54 | width | DefaultISOlevels.XML |
| Nederland Passport | 35 × 45 | 58–66 | 42–54 | width | DefaultISOlevels.XML |
| New Zealand AAA IDP online | 35 × 45 | 71–80 | 42–54 | height | DefaultISOlevels.XML |
| New Zealand Passport online | 30 × 40 | 55–80 | 30–50 | height | DefaultISOlevels.XML |
| New Zealand VISA | 35 × 45 | 55–80 | 30–50 | height | DefaultISOlevels.XML |
| Nigeria Passport | 35 × 45 | 64–75 | 42–54 | height | DefaultISOlevels.XML |
| Norway Passport | 35 × 45 | 70–80 | 42–53 | height | DefaultISOlevels.XML |
| NSW TAXI | 50 × 50 | 68–88 | 35–55 | height | NOlevels.XML |
| Oman Passport | 40 × 60 | 50–63 | 32–44 | height | DefaultISOlevels.XML |
| Oman Visa | 40 × 60 | 50–63 | 32–44 | height | DefaultISOlevels.XML |
| Pakistan eServices online | 35 × 45 | 64–74 | 42–54 | height | DefaultISOlevels.XML |
| Pakistan Passport | 50 × 50 | 50–68 | 32–44 | height | DefaultISOlevels.XML |
| Panama Maritime | 50 × 50 | 50–69 | 33–50 | height | DefaultISOlevels.XML |
| Philippines Passport | 35 × 45 | 68–80 | 42–54 | height | DefaultISOlevels.XML |
| Philippines Visa | 35 × 45 | 68–80 | 42–54 | height | DefaultISOlevels.XML |
| Poland Passport | 35 × 45 | 69–80 | 36–53 | height | DefaultISOlevels.XML |
| Portugal Passport | 35 × 45 | 71–80 | 35–52 | height | DefaultISOlevels.XML |
| Romania Citizenship | 30 × 40 | 48–64 | 22–52 | height | DefaultISOlevels.XML |
| Romania Passport | 35 × 45 | 70–80 | 41–53 | height | DefaultISOlevels.XML |
| Romania VISA | 35 × 45 | 70–80 | 41–53 | height | DefaultISOlevels.XML |
| Russia Passport | 35 × 45 | 68–80 | 42–52 | height | DefaultISOlevels.XML |
| Russia VISA | 35 × 45 | 65–75 | 42–52 | height | DefaultISOlevels.XML |
| Sante Quebec | 50 × 70 | 44–52 | 32–40 | height | DefaultISOlevels.XML |
| Saudi Arabia Passport | 50 × 50 | 50–68 | 32–44 | height | DefaultISOlevels.XML |
| Saudi Arabia Visa | 50 × 50 | 50–68 | 32–44 | height | DefaultISOlevels.XML |
| Singapore  Passport | 35 × 45 | 56–78 | 40–60 | height | DefaultISOlevels.XML |
| Singapore eVisa online | 35 × 45 | 56–78 | 40–60 | height | DefaultISOlevels.XML |
| Singapore Passport online | 35 × 45 | 56–78 | 40–60 | height | DefaultISOlevels.XML |
| Singapore VISA | 35 × 45 | 56–78 | 40–60 | height | DefaultISOlevels.XML |
| Slovakia Passport | 35 × 45 | 70–80 | 42–53 | height | DefaultISOlevels.XML |
| Slovenia Passport | 35 × 45 | 70–80 | 42–53 | height | DefaultISOlevels.XML |
| South Africa Passport | 35 × 45 | 65–75 | 42–52 | height | DefaultISOlevels.XML |
| South Africa VISA | 35 × 45 | 65–75 | 42–52 | height | DefaultISOlevels.XML |
| Spain ID 26x32 | 40 × 50 | 60–70 | 42–52 | height | DefaultISOlevels.XML |
| Spain Passport | 30 × 40 | 60–70 | 42–52 | height | DefaultISOlevels.XML |
| Spain VISA | 35 × 45 | 60–78 | 42–52 | height | DefaultISOlevels.XML |
| SpecialMode | 35 × 45 | 67–80 | 40–54 | height | DefaultISOlevels.XML |
| Sri Lanka Passport | 35 × 45 | 74–85 | 35–52 | height | DefaultISOlevels.XML |
| Sri Lanka VISA | 35 × 45 | 74–85 | 35–52 | height | DefaultISOlevels.XML |
| Sudan Passport | 35 × 45 | 68–80 | 42–54 | height | DefaultISOlevels.XML |
| Sweden Passport | 35 × 45 | 68–75 | 45–50 | height | DefaultISOlevels.XML |
| Sweden VISA | 35 × 45 | 68–75 | 45–50 | height | DefaultISOlevels.XML |
| Switzerland  Passport | 35 × 45 | 65–75 | 44–52 | height | DefaultISOlevels.XML |
| Switzerland VISA | 35 × 45 | 65–75 | 44–52 | height | DefaultISOlevels.XML |
| Syria Passport | 40 × 60 | 54–68 | 36–51 | height | DefaultISOlevels.XML |
| Thailand Passport | 35 × 45 | 70–80 | 38–58 | height | DefaultISOlevels.XML |
| Thailand VISA | 40 × 60 | 66–80 | 42–54 | height | DefaultISOlevels.XML |
| Turkey Passport | 50 × 60 | 70–80 | 42–52 | height | DefaultISOlevels.XML |
| Turkey Visa | 50 × 60 | 70–80 | 42–52 | height | DefaultISOlevels.XML |
| UAE eVisa online | 35 × 45 | 60–70 | 40–52 | height | DefaultISOlevels.XML |
| UAE Passport | 35 × 45 | 60–70 | 40–52 | height | DefaultISOlevels.XML |
| UAE VISA | 35 × 45 | 60–70 | 40–52 | height | DefaultISOlevels.XML |
| UK online | 50 × 70 | 44–58 | 34–48 | height | DefaultISOlevels.XML |
| Ukraine Passport | 35 × 45 | 60–80 | 42–53 | height | DefaultISOlevels.XML |
| United Kingdom Online Renewal | 50 × 70 | 30–44 | 24–50 | height | DefaultISOlevels.XML |
| United Kingdom Passport | 35 × 45 | 64–75 | 42–54 | height | DefaultISOlevels.XML |
| United Kingdom Visa | 35 × 45 | 64–75 | 42–54 | height | DefaultISOlevels.XML |
| USA Greencard online | 50 × 50 | 50–68 | 32–44 | height | DefaultISOlevels.XML |
| USA passport online | 50 × 50 | 50–68 | 32–44 | height | DefaultISOlevels.XML |
| USA Passport | 50 × 50 | 50–68 | 32–44 | height | DefaultISOlevels.XML |
| USA Visa | 50 × 50 | 50–68 | 32–44 | height | DefaultISOlevels.XML |
| Vietnam Passport | 40 × 60 | 50–60 | 32–44 | height | DefaultISOlevels.XML |
| Vietnam VISA | 40 × 60 | 50–60 | 32–44 | height | DefaultISOlevels.XML |
