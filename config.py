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

_base = os.path.dirname(os.path.abspath(__file__))
DB_PATH        = os.path.join(_base, "dct_risk.db")
UPLOAD_FOLDER  = os.path.join(_base, "uploads")
MAX_UPLOAD_MB  = 16
