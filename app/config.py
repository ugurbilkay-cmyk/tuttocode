import os
from pathlib import Path


def _bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
PHOTO_DIR = DATA_DIR / "photos"
DB_PATH = DATA_DIR / "tuttoid.sqlite3"
MODEL_DIR = Path(os.getenv("MODEL_DIR", BASE_DIR / "models"))

# Short domain that serves photo codes to HMPO, e.g. "tutto.uk".
# Must be: name 1-6 chars, TLD 2-3 chars. Path is 6-8 chars.
SHORT_DOMAIN = os.getenv("SHORT_DOMAIN", "tpcode.uk").lower()
CODE_LENGTH = int(os.getenv("CODE_LENGTH", "8"))

# Public site where customers upload (main domain).
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://staff.tpcode.uk").rstrip("/")

SHOP_NAME = os.getenv("SHOP_NAME", "Tuttoprint")
SHOP_CONTACT = os.getenv("SHOP_CONTACT", "info@tuttoprint.co.uk · Edmonton Green, London")

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")  # required; admin is locked if empty

# Days a code (and the photo) stays available. Deleted after this.
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "30"))
# Pending (un-issued) uploads are deleted after this many hours.
PENDING_RETENTION_HOURS = int(os.getenv("PENDING_RETENTION_HOURS", "24"))

HMPO_KEY_URL = os.getenv(
    "HMPO_KEY_URL",
    "https://www.passport.service.gov.uk/photo/public/keys/photo-code-auth-key.pub",
)
HMPO_KEY_FILE = Path(os.getenv("HMPO_KEY_FILE", DATA_DIR / "hmpo-photo-code-auth-key.pub"))

# Default state of the enhance tick-boxes on the station page.
AUTO_ADJUST = _bool("AUTO_ADJUST", False)     # Photomatic p_bAutoedit=false
FIX_SHADOWS = _bool("FIX_SHADOWS", False)     # AdjustExposureFaceShadows=0
EVEN_BG = _bool("EVEN_BG", False)
BG_REPLACE = _bool("BG_REPLACE", False)       # replace background with plain grey

# Customer self-upload page. Off = shop/staff use only.
PUBLIC_UPLOADS = _bool("PUBLIC_UPLOADS", False)

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))

# Server only. Never put this key in templates, JavaScript or job records.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2")
OPENAI_TIMEOUT_SECONDS = int(os.getenv("OPENAI_TIMEOUT_SECONDS", "180"))
IRISH_PROVIDER_URL = os.getenv("IRISH_PROVIDER_URL", "").strip()

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")

for d in (DATA_DIR, PHOTO_DIR):
    d.mkdir(parents=True, exist_ok=True)
