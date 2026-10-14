# Staff-operated validation queue

Open **More → Test queues** in the studio, or `/admin/tests`. Prepare photos with our own engine first. Select 5, 10, 20 or individual prepared jobs, name the queue and create it. Append subsequent cases to the same queue up to 200. This step makes no OpenAI, GOV.UK or Photomatic requests.

Each case freezes the exact Save JPEG. The private snapshot records its SHA-256, dimensions, source/master hashes, country, age group, preparation options, current engine-code/catalog fingerprint and existing prepared-master measurements. Those heuristic measurements are not a fresh assessment of the frozen final JPEG. A separate `final_jpeg_ofiq` record is retained only when the native assessment hash matches the exact frozen export; a mismatch remains Not assessed. Editing the studio job cannot change a frozen case; add the revised job as another case.

## Work through cases

1. Open a case and download its named JPEG.
2. Open GOV.UK normally once. Staff upload the file themselves, using the correct birth-date/age context. For the next photo, use the service's normal change-photo/upload-another workflow when available. Ensure a fresh result belongs to the current file. The queue does not operate the external page, reuse credentials, avoid access controls or retry blocked submissions.
3. Record the observed feedback and birth date used; attach a screenshot if useful. Leave **Not checked** when it was not checked. **Unavailable** records an access problem, not a photo failure. Placeholder birthdays/sample cases are explicitly labelled and excluded from distinct customer counts. GOV.UK may retain uploads and birth details for up to six months; see its [privacy policy](https://www.passport.service.gov.uk/help/privacy).
4. Separately open that exact file in Photomatic. Record all three category colours, assessed dimensions and any crop changes; attach the result screenshot. Reopening may crop again, so confirm comparable framing rather than assuming it. This is currently a manual reference step, not a vendor batch checker.
5. Confirm file matching, then **Save result and next photo**. Observations are revisioned, staff-labelled records; concurrent stale saves are rejected. Codes remain a separate staff workflow with existing advisory checks.

## Counts and evidence

GOV.UK Good and Photomatic outcomes are separate. Only **dark green in all three** vendor categories enters the strict dark-green total. Light green, amber, red, grey and untested categories do not count. The dashboard also shows comparable-framing results and disagreements between vendor dark green and existing engine findings or GOV.UK flags.

The distinct customer total requires real-customer marking, a non-identifying reference, no placeholder birthday, an original source hash, our engine preparation, comparable framing and a vendor screenshot. Duplicate source hashes or customer references count once within this queue. This is evidence of a recorded vendor match, not proof of every local metric matching or government approval. All attempts, failures, crop differences and revisions should remain in the study. A 200/1000-case threshold does not automatically certify or retire the reference engine; representative conditions and false-pass/false-fail analysis remain necessary.

## Retention and exports

By default, test files and detailed observations expire with the source job. For a study spanning several days, explicitly select **Keep separate test copies and observations** when creating the queue: these copies survive ordinary source expiry until the configured study deadline (currently 30 days from queue creation). Rejecting an original removes its test copies even with this option. Expiry scrubs photos, screenshots, DOBs and detailed measurements; source-expired cases remain as empty placeholders until queue expiry. Retained study copies can outlive their original studio-job link.

Download the JPEG batch ZIP and JSON report before expiry. Both require staff authentication. The ZIP contains numbered exact JPEGs, attached evidence screenshots and a matching manifest with the observation history; altered/expired files cause an error instead of exporting a mismatched batch. Reports contain private test metadata, including recorded birthdays: store them with the study's authorised access and retention controls. Exports are not automatically removed from staff download folders. No customer files or results belong in Git.
