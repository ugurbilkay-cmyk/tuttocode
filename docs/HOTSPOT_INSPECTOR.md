# Regional hotspot inspector

Implemented 13 October 2026 as a staff-only diagnostic tool. It does not call
OpenAI, edit photos, create codes or change any existing approval decision.

Open a job and select **Inspect hotspots**. The inspector takes a consistent
snapshot of the original, current prepared photo (the final code JPEG for an
issued job), and an unaccepted AI source when available. Low-resolution originals
can be inspected even when their normal crop was rejected. Each image is
measured in its own coordinate frame; comparison is by named facial region,
not a claim of pixel-perfect correspondence between edited images.

MediaPipe estimates the facial landmarks. Approximate ellipses locate forehead,
nose, image-left cheek, image-right cheek and chin regions; the face oval,
foreground segmentation when available, and protected eye/lip masks constrain
the sampled pixels. These are estimated facial regions, not a validated skin
segmentation method. Beard, headwear, pose and failed landmarks may affect them.
No skin-colour threshold is used to decide which complexions are inspectable.

The initial diagnostic parameters are explicit and **uncalibrated**:

- A bright candidate is at least 80 L* and 15 L* above that region's median, or
  has at least one decoded RGB channel at 250 or above.
- Near-clipped percentages separately count any channel and all three channels
  at 250–255. They indicate proximity to an 8-bit encoding limit; they do not
  prove camera-sensor clipping or quantify recoverable anatomical detail.
- Amber candidate boxes show connected patches of at least three pixels or
  0.02% of the union of inspected regions, whichever is larger. Only the largest
  100 patches are drawn; percentages still count all qualifying pixels.

Counts use native decoded pixels after EXIF orientation. A reduced preview is
only for display. Cyan outlines indicate regions; amber boxes indicate candidate
patches. Neither colour is a passport pass/fail result. Missing faces, invalid
landmarks, invalid masks, tiny sampling regions and engine errors remain
unavailable. Images over 16 million pixels are unavailable rather than silently
resized for measurements.

Each report carries the exact input-file SHA-256, engine version, parameters,
native dimensions, region pixel counts and overlay coordinates. The thumbnail
is embedded in the same authenticated, no-store response as its measurements.
An edit, deletion, expiry or candidate change during inspection invalidates the
response. There is no new photo retention, report storage or public image route.

Synthetic tests cover known highlight locations/areas, uniform complexions,
background and eye/lip exclusion, single-channel versus three-channel values,
invalid geometry, failed detection, access control and stale snapshots. They
verify implementation behaviour, not accuracy on the shop population. Real
reference images are evaluated locally and are not committed to Git.

Before any approval gate or automatic correction uses this method, calibrate
on independently annotated shop photographs with hard lighting, ordinary skin
reflections, all relevant complexions, makeup, glasses, beards, children and
medical cases. Compare Photomatic's per-check results as reference evidence,
alongside independent review. Reserve separate photographs for evaluation and
measure false alarms and missed defects. Photomatic's `MinHotspots=36` is a
different proprietary scale and is not a threshold for these percentages.

Reducing a bright patch's intensity can reduce these counts without recovering
detail. A separate original/candidate likeness and detail review is required.
The next correction stage should use measured locations to guide bounded edits
and then rerun independent checks, not repeatedly edit until a scalar turns green.
