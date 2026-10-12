"""End-to-end test with a synthetic face (no ML models needed).

Run: python3 tests/test_e2e.py
"""
import base64
import io
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

TMP = Path(tempfile.mkdtemp())
os.environ.update(
    DATA_DIR=str(TMP), HMPO_KEY_URL="", ADMIN_PASSWORD="secret", SHORT_DOMAIN="tpcode.uk", PUBLIC_UPLOADS="true",
    HMPO_KEY_FILE=str(TMP / "hmpo.pub"),
)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import jwt  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from app import processing as P  # noqa: E402

# fake HMPO key pair
hmpo_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
(TMP / "hmpo.pub").write_bytes(hmpo_priv.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
other_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)


# ---------------------------------------------------------------- synthetic face
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
        sh = img.copy()
        sh[:, :cx] = (sh[:, :cx] * 0.45).astype(np.uint8)
        img = np.where(mask[..., None] > 0, sh, img)

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
        return self.a


def run(name, kw, expect_ok, expect_fail_key=None, age="adult"):
    data, an = make_face(**kw)
    res = P.process(data, age, analyzer=Fake(an))
    fails = [c.key for c in res.checks if c.status == "fail"]
    status = "OK " if (res.ok == expect_ok and (expect_fail_key is None or expect_fail_key in fails)) else "BAD"
    print(f"{status} {name:28s} ok={res.ok} fails={fails} warns={[c.key for c in res.checks if c.status=='warn']}")
    assert status == "OK ", res.checks
    return data, an, res


print("--- processing")
data, an, good = run("good photo", {}, True)
out = Image.open(io.BytesIO(good.jpeg))
assert out.size == (P.OUT_W, P.OUT_H), out.size
kb = len(good.jpeg) / 1024
assert 50 <= kb <= 10000, kb
print(f"    output {out.size} {kb:.0f}KB")
(TMP / "good.jpg").write_bytes(good.jpeg)
run("tilted head", {"roll": 12}, False, "tilt")
run("dark background", {"bg": (90, 70, 60)}, False, "background")
run("too close (no headroom)", {"scale": 2.4}, False, "framing")
run("too small / far", {"W": 1200, "H": 1600, "scale": 0.4}, False, "resolution")
run("smiling", {"smile": 0.8}, False, "expression")
run("smiling child (allowed)", {"smile": 0.8}, True, age="child")
run("eyes closed", {"blink": 0.9}, False, "eyes")
run("eyes closed baby (allowed)", {"blink": 0.9}, True, age="baby")
run("shadow on face", {"half_shadow": True}, False, "shadow")
_, _, gl = run("glare on glasses (flagged)", {"glare": True}, True)
assert any(c.key == "glare" and c.status != "pass" for c in gl.checks)

sheet = P.print_sheet(good.jpeg, "tpcode.uk/Ab3xK9pQ")
sim = Image.open(io.BytesIO(sheet))
assert sim.size == (1800, 1200), sim.size
(TMP / "sheet.jpg").write_bytes(sheet)
print("    print sheet", sim.size)

# ---------------------------------------------------------------- web app
print("--- web app")
import uvicorn  # noqa: E402

from app import main  # noqa: E402

P._analyzer = Fake(an)  # use the synthetic analysis for every upload
server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=8765, log_level="warning"))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(50):
    if server.started:
        break
    time.sleep(0.1)

BASE = "http://127.0.0.1:8765"
AUTH = "Basic " + base64.b64encode(b"admin:secret").decode()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


opener = urllib.request.build_opener(NoRedirect)


def req(path, method="GET", data=None, headers=None, host=None):
    h = dict(headers or {})
    if host:
        h["Host"] = host
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        resp = opener.open(r)
        return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def multipart(fields, file_bytes):
    b = "----tuttoidtest"
    parts = []
    for k, v in fields.items():
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="photo"; filename="p.jpg"\r\n'
                 f'Content-Type: image/jpeg\r\n\r\n'.encode() + file_bytes + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    return b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={b}"}


def check(label, cond):
    print(("OK " if cond else "BAD"), label)
    assert cond, label


s, _, body = req("/")
check("upload page renders", s == 200 and b"passport photo code" in body)

# customer online upload
body, hdr = multipart({"age_group": "adult", "consent": "on"}, data)
s, h, _ = req("/upload", "POST", body, hdr)
check("customer upload redirects to result", s == 303 and h["location"].startswith("/r/"))
pid = h["location"].split("/r/")[1]
s, _, page = req(f"/r/{pid}")
check("result page shows pass", s == 200 and b"passed our checks" in page)
s, _, _ = req(f"/r/{pid}/preview.jpg")
check("preview available", s == 200)
form = urllib.parse.urlencode({"name": "Test Person", "email": "t@example.com"}).encode()
s, h, _ = req(f"/r/{pid}/submit", "POST", form, {"Content-Type": "application/x-www-form-urlencoded"})
check("customer submits contact", s == 303)

# admin
s, _, _ = req("/admin")
check("admin requires auth", s == 401)
s, _, page = req("/admin", headers={"Authorization": AUTH})
check("admin list shows customer", s == 200 and b"Test Person" in page)
s, h, _ = req(f"/admin/p/{pid}/issue", "POST", b"", {"Authorization": AUTH, "Content-Type": "application/x-www-form-urlencoded",
                                                   "Origin": "https://evil.example"})
check("CSRF from other origin blocked", s == 403)
s, h, _ = req(f"/admin/p/{pid}/issue", "POST", b"", {"Authorization": AUTH, "Content-Type": "application/x-www-form-urlencoded"})
check("admin issues code", s == 303)

from app import db  # noqa: E402

code = db.get(pid)["code"]
check(f"code generated ({code})", code and len(code) == 8)
s, _, page = req(f"/r/{pid}")
check("customer page now shows code", code.encode() in page)
s, _, sheet = req(f"/admin/p/{pid}/sheet.jpg", headers={"Authorization": AUTH})
check("print sheet served", s == 200 and Image.open(io.BytesIO(sheet)).size == (1800, 1200))
s, _, slip = req(f"/admin/p/{pid}/slip", headers={"Authorization": AUTH})
check("code slip served", s == 200 and code.encode() in slip)

# HMPO fetch on short domain
url = f"https://tpcode.uk/{code}"
tok = lambda key, sub=url, **extra: jwt.encode({"sub": sub, "iat": int(time.time()), **extra}, key, algorithm="RS256")  # noqa
s, _, _ = req(f"/{code}", host="tpcode.uk")
check("no token -> 404", s == 404)
s, _, _ = req(f"/{code}", host="tpcode.uk", headers={"Authorization": tok(other_priv)})
check("wrong signer -> 404", s == 404)
s, _, _ = req(f"/{code}", host="tpcode.uk", headers={"Authorization": tok(hmpo_priv, sub="https://tpcode.uk/zzzzzzzz")})
check("sub mismatch -> 404", s == 404)
s, _, _ = req(f"/{code}", host="tpcode.uk", headers={"Authorization": tok(hmpo_priv, exp=int(time.time()) - 600)})
check("expired token -> 404", s == 404)
s, h, img = req(f"/{code}", host="tpcode.uk", headers={"Authorization": tok(hmpo_priv)})
check("HMPO-signed -> JPEG", s == 200 and h["content-type"] == "image/jpeg" and img[:2] == b"\xff\xd8")
s, h, img = req(f"/{code}", host="tpcode.uk", headers={"Authorization": "Bearer " + tok(hmpo_priv)})
check("Bearer prefix accepted", s == 200)
kb = len(img) / 1024
check(f"size within 50KB-10MB ({kb:.0f}KB)", 50 <= kb <= 10240)
s, _, _ = req(f"/{code}", host="tpcode.uk:443", headers={"Authorization": tok(hmpo_priv)})
check("host with port still routed", s == 200)
s, _, _ = req("/admin", host="tpcode.uk", headers={"Authorization": AUTH})
check("admin not reachable on short domain", s == 404)
s, _, _ = req(f"/{code}", headers={"Authorization": tok(hmpo_priv)})
check("code route not on main domain", s == 404)
check("fetch counted", db.get(pid)["fetched_count"] == 3)

# shop flow with a failing photo
bad, _ = make_face(bg=(90, 70, 60))
P._analyzer = Fake(make_face(bg=(90, 70, 60))[1])
body, hdr = multipart({"age_group": "adult", "name": "Walk In"}, bad)
hdr["Authorization"] = AUTH
s, h, _ = req("/admin/new", "POST", body, hdr)
pid2 = h["location"].split("/admin/p/")[1]
s, _, _ = req(f"/admin/p/{pid2}/issue", "POST", b"", {"Authorization": AUTH, "Content-Type": "application/x-www-form-urlencoded"})
check("failed photo can't be issued without override", s == 400)

# expiry purge
with db.conn() as c:
    c.execute("UPDATE photos SET expires=? WHERE id=?", (time.time() - 1, pid))
n = db.purge_expired()
s, _, _ = req(f"/{code}", host="tpcode.uk", headers={"Authorization": tok(hmpo_priv)})
check(f"expired code purged ({n} removed) -> 404", s == 404 and not (TMP / "photos" / f"{pid}.jpg").exists())

server.should_exit = True
print("\nAll tests passed. Outputs in", TMP)
