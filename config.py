import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
NEWSAPI_KEY       = os.environ.get("NEWSAPI_KEY", "")

MODEL_ANALYSIS = "claude-opus-4-5"
MODEL_FAST     = "claude-haiku-4-5-20251001"

_base     = os.path.dirname(os.path.abspath(__file__))
_on_vercel = bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"))

# Vercel's filesystem is read-only outside /tmp
DB_PATH       = "/tmp/dct_risk.db"       if _on_vercel else os.path.join(_base, "dct_risk.db")
UPLOAD_FOLDER = "/tmp/uploads"           if _on_vercel else os.path.join(_base, "uploads")
MAX_UPLOAD_MB = 16
