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
from synthetic import make_face, Fake


def run(name, kw, expect_ok, expect_fail_key=None, age="adult", **opts):
    data, an = make_face(**kw)
    enhance_options = dict(auto_adjust=True, fix_shadows=True, even_bg=True)
    enhance_options.update(opts)
    res = P.process(data, age, analyzer=Fake(an), **enhance_options)
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
run("too close (head too large)", {"scale": 2.4}, False, "headsize")
run("too small / far", {"W": 1200, "H": 1600, "scale": 0.4}, False, "resolution")
run("smiling", {"smile": 0.8}, False, "expression")
run("smiling child (allowed)", {"smile": 0.8}, True, age="child")
run("eyes closed", {"blink": 0.9}, False, "eyes")
run("eyes closed baby (allowed)", {"blink": 0.9}, True, age="baby")
run("shadow on face, fix off", {"half_shadow": True}, False, "shadow", fix_shadows=False)
_, _, sh = run("shadow on face, fix on", {"half_shadow": True}, True)
(TMP / "shadow_fixed.jpg").write_bytes(sh.jpeg)
(TMP / "shadow_before.jpg").write_bytes(sh.before_jpeg)

# colour cast + underexposed: background should come out neutral and light
# whole scene under-exposed with a blue/cold cast (camera on wrong white balance)
d0, an0 = make_face()
arr = np.asarray(Image.open(io.BytesIO(d0))).astype(np.float32) * np.array([0.55, 0.62, 0.78])
buf = io.BytesIO(); Image.fromarray(arr.clip(0, 255).astype(np.uint8)).save(buf, "JPEG", quality=92)
cc = P.process(buf.getvalue(), analyzer=Fake(an0), auto_adjust=True, fix_shadows=True, even_bg=True)
print("OK  blue cast + dark scene        ok=", cc.ok, [c.detail for c in cc.checks if c.key == "adjust"])
assert cc.ok
o = np.asarray(Image.open(io.BytesIO(cc.jpeg)))
corner = o[20:200, 20:150].reshape(-1, 3).mean(0)
print("    background after:", corner.round(1))
assert corner.min() > 190 and corner.max() - corner.min() < 8, corner
(TMP / "cast_fixed.jpg").write_bytes(cc.jpeg)
(TMP / "cast_before.jpg").write_bytes(cc.before_jpeg)

# features kept: fine detail in the face matches before/after
def detail(rgb):
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    return g - cv2.GaussianBlur(g, (0, 0), 6)
b = np.asarray(Image.open(io.BytesIO(sh.before_jpeg)).resize((350, 450)))
a = np.asarray(Image.open(io.BytesIO(sh.preview_jpeg)))
db_, da_ = detail(b)[120:330, 90:260], detail(a)[120:330, 90:260]
corr = np.corrcoef(db_.ravel(), da_.ravel())[0, 1]
print(f"    facial detail correlation before/after: {corr:.3f}")
assert corr > 0.85
_, _, gl = run("glare on glasses (flagged)", {"glare": True}, True)
assert any(c.key == "glare" and c.status != "pass" for c in gl.checks)

sheet = P.print_sheet(good.jpeg, "tpcode.uk/Ab3xK9pQ")
sim = Image.open(io.BytesIO(sheet))
assert sim.size == (1844, 1240), sim.size
assert sim.info['dpi'] == (301, 301)
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
    if path.endswith("/issue") and method == "POST":
        fields = dict(urllib.parse.parse_qsl((data or b"").decode()))
        fields.update(review_likeness="on", review_visibility="on", customer_permission="on")
        photo_id = path.split("/p/")[1].split("/")[0]
        fields["review_revision"] = str(main.db.get(photo_id)["revision"])
        data = urllib.parse.urlencode(fields).encode()
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
old_limit = main.config.MAX_UPLOAD_MB
main.config.MAX_UPLOAD_MB = 1
oversize, oversize_headers = multipart({"age_group": "adult"}, b"x" * (2 * 1024 * 1024))
oversize_headers["Authorization"] = AUTH
s, _, _ = req("/admin/new", "POST", oversize, oversize_headers)
check("oversized file upload rejected", s == 413)
main.config.MAX_UPLOAD_MB = old_limit
s, _, page = req("/admin/history", headers={"Authorization": AUTH})
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
check("print sheet served", s == 200 and Image.open(io.BytesIO(sheet)).size == (1844, 1240))
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
s, _, _ = req(f"/{code}", host="tpcode.uk", headers={"Authorization": tok(hmpo_priv, exp=int(time.time()) - 3600)})
check("expired token -> 404", s == 404)
s, h, img = req(f"/{code}", host="tpcode.uk", headers={"Authorization": tok(hmpo_priv)})
check("HMPO-signed -> JPEG", s == 200 and h["content-type"] == "image/jpeg" and img[:2] == b"\xff\xd8")
s, h, img = req(f"/{code}", host="tpcode.uk", headers={"Authorization": "Bearer " + tok(hmpo_priv)})
check("Bearer prefix accepted", s == 200)
s, _, _ = req(f"/{code}", host="tpcode.uk", headers={"Authorization": tok(hmpo_priv, iat=int(time.time() * 1000))})
check("iat in milliseconds accepted", s == 200)
s, _, _ = req(f"/{code}", host="tpcode.uk", headers={"Authorization": tok(hmpo_priv, iat=int(time.time()) + 120, nbf=int(time.time()) + 120)})
check("HMPO clock 2 min ahead accepted", s == 200)
s, _, _ = req(f"/{code}", host="tpcode.uk", headers={"Authorization": tok(hmpo_priv, nbf=int(time.time()) + 7200)})
check("nbf 2h in future rejected", s == 404)
kb = len(img) / 1024
check(f"size within 50KB-10MB ({kb:.0f}KB)", 50 <= kb <= 10240)
s, _, _ = req(f"/{code}", host="tpcode.uk:443", headers={"Authorization": tok(hmpo_priv)})
check("host with port still routed", s == 200)
s, _, _ = req("/admin", host="tpcode.uk", headers={"Authorization": AUTH})
check("admin not reachable on short domain", s == 404)
s, _, _ = req(f"/{code}", headers={"Authorization": tok(hmpo_priv)})
check("code route not on main domain", s == 404)
check("fetch counted", db.get(pid)["fetched_count"] == 5)
s, _, _ = req(f"/admin/p/{pid}/before.jpg", headers={"Authorization": AUTH})
check("before image served", s == 200)

# shop flow with a failing photo
bad, _ = make_face(bg=(90, 70, 60))
P._analyzer = Fake(make_face(bg=(90, 70, 60))[1])
body, hdr = multipart({"age_group": "adult", "name": "Walk In"}, bad)
hdr["Authorization"] = AUTH
s, h, _ = req("/admin/new", "POST", body, hdr)
pid2 = h["location"].split("/admin/p/")[1]
s, _, _ = req(f"/admin/p/{pid2}/issue", "POST", b"", {"Authorization": AUTH, "Content-Type": "application/x-www-form-urlencoded"})
check("failed photo cannot be issued", s == 400)
s, _, _ = req(f"/admin/p/{pid2}/issue", "POST", b"override=on", {"Authorization": AUTH, "Content-Type": "application/x-www-form-urlencoded"})
check("generic override cannot bypass failed quality checks", s == 400)

# Photomatic station: source retained while pending, recrop, then delete it on issue.
P._analyzer = Fake(an)
body, hdr = multipart({"age_group": "adult", "country_id": "united-kingdom-passport"}, data)
hdr["Authorization"] = AUTH
s, h, _ = req("/admin/new", "POST", body, hdr)
check("shop photo uploaded", s == 303)
shop_pid = h["location"].split("/admin/p/")[1]
check("pending source retained for crop adjustment", (TMP / "photos" / f"{shop_pid}_source").exists())
s, _, page = req(f"/admin/p/{shop_pid}", headers={"Authorization": AUTH})
check("Photomatic station renders imported countries", s == 200 and b"Select country / document" in page and b"Canada Passport" in page)
form = urllib.parse.urlencode({"country_id": "usa-passport", "opts": "1", "zoom": "1", "x": "0", "y": "0", "rotation": "0"}).encode()
s, _, _ = req(f"/admin/p/{shop_pid}/reprocess", "POST", form, {"Authorization": AUTH, "Content-Type": "application/x-www-form-urlencoded"})
check("recrop to USA template", s == 303 and db.get(shop_pid)["country_id"] == "usa-passport")
s, _, image = req(f"/admin/p/{shop_pid}/full.jpg", headers={"Authorization": AUTH})
check("USA crop is square", Image.open(io.BytesIO(image)).size == (1500, 1500))
s, _, _ = req(f"/admin/p/{shop_pid}/issue", "POST", b"override=on", {"Authorization": AUTH, "Content-Type": "application/x-www-form-urlencoded"})
check("non UK/Irish code blocked even with override", s == 400 and not db.get(shop_pid)["code"])
form = urllib.parse.urlencode({"country_id": "ireland-passport-online", "opts": "1"}).encode()
s, _, _ = req(f"/admin/p/{shop_pid}/reprocess", "POST", form, {"Authorization": AUTH, "Content-Type": "application/x-www-form-urlencoded"})
check("Irish online crop saved", s == 303)
s, _, image = req(f"/admin/p/{shop_pid}/save.jpg", headers={"Authorization": AUTH})
check("Irish digital export uses exact dimensions", s == 200 and Image.open(io.BytesIO(image)).size == (715, 951))
from unittest.mock import patch
sent_messages = []
class FakeSMTP:
    def __init__(self, *args, **kwargs): pass
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def starttls(self): pass
    def login(self, *args): pass
    def send_message(self, message): sent_messages.append(message)
db.update_contact(shop_pid, "Shop test", "example@example.com", "")
with patch.object(main.config, "SMTP_HOST", "smtp.test"), patch.object(main.smtplib, "SMTP", FakeSMTP):
    s, _, _ = req(f"/admin/p/{shop_pid}/email", "POST", b"", {"Authorization": AUTH})
    check("photo email prepared through SMTP", s == 303 and len(sent_messages) == 1)
    attachment = next(sent_messages[0].iter_attachments())
    check("email attachment uses Irish dimensions", Image.open(io.BytesIO(attachment.get_payload(decode=True))).size == (715, 951))
s, _, _ = req(f"/admin/p/{shop_pid}/issue", "POST", b"override=on", {"Authorization": AUTH, "Content-Type": "application/x-www-form-urlencoded"})
check("Irish code cannot be falsely issued without provider connection", s == 503 and not db.get(shop_pid)["code"])
form = urllib.parse.urlencode({"country_id": "united-kingdom-passport", "opts": "1"}).encode()
s, _, _ = req(f"/admin/p/{shop_pid}/reprocess", "POST", form, {"Authorization": AUTH, "Content-Type": "application/x-www-form-urlencoded"})
check("recrop back to UK", s == 303)
s, _, _ = req(f"/admin/p/{shop_pid}/issue", "POST", b"override=on", {"Authorization": AUTH, "Content-Type": "application/x-www-form-urlencoded"})
check("UK shop code issued and source deleted", s == 303 and db.get(shop_pid)["code"] and not (TMP / "photos" / f"{shop_pid}_source").exists())
s, _, _ = req(f"/admin/p/{shop_pid}/reprocess", "POST", form, {"Authorization": AUTH, "Content-Type": "application/x-www-form-urlencoded"})
check("issued photo cannot be recropped", s == 409)

# expiry purge
with db.conn() as c:
    c.execute("UPDATE photos SET expires=? WHERE id=?", (time.time() - 1, pid))
n = db.purge_expired()
s, _, _ = req(f"/{code}", host="tpcode.uk", headers={"Authorization": tok(hmpo_priv)})
check(f"expired code purged ({n} removed) -> 404", s == 404 and not (TMP / "photos" / f"{pid}.jpg").exists())

server.should_exit = True
print("\nAll tests passed. Outputs in", TMP)
