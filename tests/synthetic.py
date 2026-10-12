import io
import cv2
import numpy as np
from PIL import Image
from app import processing as P

def make_face(W=2400, H=3200, bg=(232, 232, 228), roll=0.0, scale=1.0, cx=None, cy=None,
              smile=0.0, blink=0.0, half_shadow=False, glare=False):
    img = np.full((H, W, 3), bg, np.uint8)
    noise = np.random.default_rng(0).normal(0, 1.5, img.shape)
    img = np.clip(img + noise, 0, 255).astype(np.uint8)
    cx = W // 2 if cx is None else cx
    cy = int(H * 0.42) if cy is None else cy
    fw, fh = int(330 * scale), int(440 * scale)
    # shoulders
    cv2.ellipse(img, (cx, cy + int(fh * 2.1)), (int(fw * 2.6), int(fh * 1.3)), 0, 180, 360, (40, 50, 80), -1)
    cv2.rectangle(img, (cx - int(fw * 2.6), cy + int(fh * 2.1)), (cx + int(fw * 2.6), H), (40, 50, 80), -1)
    cv2.rectangle(img, (cx - fw // 3, cy + fh // 2), (cx + fw // 3, cy + int(fh * 1.1)), (170, 130, 110), -1)
    # hair + face
    cv2.ellipse(img, (cx, cy - int(fh * 0.15)), (int(fw * 1.08), int(fh * 1.05)), roll, 180, 360, (45, 30, 20), -1)
    cv2.ellipse(img, (cx, cy), (fw, fh), roll, 0, 360, (200, 160, 140), -1)
    tex = np.random.default_rng(1).normal(0, 6, img.shape)
    mask = np.zeros(img.shape[:2], np.uint8)
    cv2.ellipse(mask, (cx, cy), (fw, fh), roll, 0, 360, 255, -1)
    img = np.where(mask[..., None] > 0, np.clip(img + tex, 0, 255), img).astype(np.uint8)
    if half_shadow:
        # soft side light: left side of the face falls off gradually
        xs = np.arange(img.shape[1], dtype=np.float32)
        ramp = np.clip((xs - (cx - fw)) / (1.4 * fw), 0, 1)
        fall = (0.4 + 0.6 * ramp)[None, :, None]
        img = np.where(mask[..., None] > 0, (img * fall).astype(np.uint8), img)

    pts = np.tile([cx, cy], (478, 1)).astype(np.float32)
    r = np.radians(roll)
    rot = lambda dx, dy: (cx + dx * np.cos(r) - dy * np.sin(r), cy + dx * np.sin(r) + dy * np.cos(r))  # noqa
    ex, ey = fw * 0.40, -fh * 0.15
    L, R = rot(-ex, ey), rot(ex, ey)
    for c in (L, R):
        cv2.ellipse(img, (int(c[0]), int(c[1])), (int(fw * .14), int(fh * .05)), roll, 0, 360, (250, 250, 250), -1)
        cv2.circle(img, (int(c[0]), int(c[1])), int(fh * .045), (60, 40, 30), -1)
    if glare:
        cv2.circle(img, (int(L[0] + fw * .1), int(L[1] - fh * .09)), int(fh * .05), (255, 255, 255), -1)
    pts[P.L_IRIS], pts[P.R_IRIS] = L, R
    pts[P.CHIN] = rot(0, fh)
    pts[P.FOREHEAD] = rot(0, -fh * 0.85)
    pts[P.NOSE] = rot(0, fh * 0.15)
    pts[P.FACE_L], pts[P.FACE_R] = rot(-fw, 0), rot(fw, 0)
    for ring, c in ((P.LEFT_EYE_RING, L), (P.RIGHT_EYE_RING, R)):
        for k, idx in enumerate(ring):
            a = 2 * np.pi * k / len(ring)
            pts[idx] = (c[0] + fw * .14 * np.cos(a), c[1] + fh * .05 * np.sin(a))
    person = np.zeros(img.shape[:2], np.float32)
    person[(np.abs(img.astype(int) - np.array(bg)).sum(-1) > 25)] = 1.0
    person = cv2.dilate(person, np.ones((9, 9)))
    bs = {"eyeBlinkLeft": blink, "eyeBlinkRight": blink, "jawOpen": 0.02,
          "mouthSmileLeft": smile, "mouthSmileRight": smile}
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, "JPEG", quality=92)
    return buf.getvalue(), P.Analysis([P.FaceData(pts, bs)], person)


class Fake:
    def __init__(self, analysis):
        self.a = analysis

    def analyze(self, rgb):
        if self.a.person_mask is None or rgb.shape[:2] == self.a.person_mask.shape:
            return self.a
        # A code JPEG has been cropped/resized. Locate the two known synthetic
        # white eye ellipses to map test landmarks into that actual image frame.
        bright = (rgb.min(axis=2) > 242).astype(np.uint8)
        count, _, stats, centers = cv2.connectedComponentsWithStats(bright)
        largest = sorted(range(1, count), key=lambda i: stats[i, cv2.CC_STAT_AREA], reverse=True)[:2]
        if len(largest) != 2:
            return P.Analysis([], None)
        eyes = sorted((centers[i] for i in largest), key=lambda c: c[0])
        points = self.a.faces[0].points
        previous = [points[P.L_IRIS], points[P.R_IRIS]]
        scale = np.linalg.norm(eyes[1] - eyes[0]) / np.linalg.norm(previous[1] - previous[0])
        offset = (eyes[0] + eyes[1]) / 2 - scale * (previous[0] + previous[1]) / 2
        matrix = np.array([[scale, 0, offset[0]], [0, scale, offset[1]]], np.float32)
        h, w = rgb.shape[:2]
        mask = cv2.warpAffine(self.a.person_mask, matrix, (w, h))
        return P.Analysis([P.FaceData(points * scale + offset, self.a.faces[0].blendshapes)], mask)
