"""Verify the JWS token HMPO sends when it fetches a photo code.

Spec (passport.service.gov.uk/help/photo-codes):
- JWS in the Authorization header, signed by HMPO.
- Verify with HMPO's published public key.
- 'sub' must equal the HTTPS short URL of the code, e.g. https://tutto.uk/Ab3xK9pQ
"""
import logging
import threading
import time
import urllib.request

import jwt
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from cryptography.hazmat.primitives.serialization import (
    load_der_public_key,
    load_pem_public_key,
    load_ssh_public_key,
)

from . import config

log = logging.getLogger("tuttoid.hmpo")
_lock = threading.Lock()
_key = None
_key_loaded_at = 0.0
KEY_REFRESH_SECONDS = 24 * 3600
CLOCK_LEEWAY = 600  # seconds of clock difference tolerated


def _parse_key(raw: bytes):
    raw = raw.strip()
    for loader in (load_pem_public_key, load_der_public_key):
        try:
            return loader(raw)
        except Exception:
            pass
    try:
        return load_ssh_public_key(raw)
    except Exception:
        pass
    raise ValueError("Unrecognised HMPO public key format")


def _algorithms(key):
    if isinstance(key, rsa.RSAPublicKey):
        return ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512"]
    if isinstance(key, ec.EllipticCurvePublicKey):
        return ["ES256", "ES384", "ES512"]
    if isinstance(key, ed25519.Ed25519PublicKey):
        return ["EdDSA"]
    raise ValueError("Unsupported key type")


def _download():
    req = urllib.request.Request(config.HMPO_KEY_URL, headers={"User-Agent": "tuttoid/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read()


def get_key(force=False):
    """Load key from file; refresh from HMPO URL daily. Falls back to cached file."""
    global _key, _key_loaded_at
    with _lock:
        fresh = time.time() - _key_loaded_at < KEY_REFRESH_SECONDS
        if _key is not None and fresh and not force:
            return _key
        raw = None
        if config.HMPO_KEY_URL:
            try:
                raw = _download()
                _parse_key(raw)
                config.HMPO_KEY_FILE.write_bytes(raw)
            except Exception as e:
                log.warning("Could not refresh HMPO key (%s); using cached file", e)
                raw = None
        if raw is None and config.HMPO_KEY_FILE.exists():
            raw = config.HMPO_KEY_FILE.read_bytes()
        if raw is None:
            raise RuntimeError("HMPO public key unavailable")
        _key = _parse_key(raw)
        _key_loaded_at = time.time()
        return _key


def short_url(code: str) -> str:
    return f"https://{config.SHORT_DOMAIN}/{code}"


def _norm(url: str) -> str:
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    scheme, rest = url.split("://", 1)
    host, _, path = rest.partition("/")
    return f"{scheme.lower()}://{host.lower()}/{path.rstrip('/')}"


def verify(auth_header: str | None, code: str) -> tuple[bool, str]:
    """Return (ok, reason)."""
    if not auth_header:
        return False, "missing authorization"
    token = auth_header.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    try:
        key = get_key()
    except Exception as e:
        log.error("HMPO key error: %s", e)
        return False, "key unavailable"

    def _decode(k):
        # Signature is verified here; time claims are checked below by us,
        # because HMPO's clock/units may differ (e.g. milliseconds).
        return jwt.decode(
            token, k, algorithms=_algorithms(k),
            options={"verify_aud": False, "verify_iat": False, "verify_nbf": False,
                     "verify_exp": False, "require": ["sub"]},
        )

    try:
        claims = _decode(key)
    except jwt.InvalidSignatureError:
        # HMPO may have rotated its key: refetch once and retry.
        try:
            key = get_key(force=True)
            claims = _decode(key)
        except Exception as e:
            return False, f"bad signature ({type(e).__name__})"
    except Exception as e:
        return False, f"invalid token ({type(e).__name__})"

    times = {k: claims.get(k) for k in ("iat", "nbf", "exp") if k in claims}
    log.info("HMPO token sub=%s times=%s now=%d", claims.get("sub"), times, int(time.time()))

    def _secs(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return v / 1000 if v > 1e11 else v  # milliseconds -> seconds

    now = time.time()
    exp = _secs(claims.get("exp"))
    if exp is not None and exp < now - CLOCK_LEEWAY:
        return False, "token expired"
    for k in ("iat", "nbf"):
        t = _secs(claims.get(k))
        if t is not None and t > now + CLOCK_LEEWAY:
            return False, f"{k} in future by {int(t - now)}s"

    if _norm(str(claims.get("sub", ""))) != _norm(short_url(code)):
        return False, f"sub mismatch ({claims.get('sub')})"
    return True, "ok"
