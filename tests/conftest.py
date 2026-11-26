import os
import sys
from pathlib import Path

os.environ["MOCK_DELAY_SCALE"] = "0"
os.environ["DEMO_DELAY_SCALE"] = "0"
# tests never touch the real Supabase project: memory backend + a single local user
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_SECRET_KEY"] = ""
os.environ["STORAGE"] = "local"
os.environ["LLM_PROVIDER"] = "mock"
for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
    os.environ[k] = ""
import tempfile
os.environ["CACHE_DB"] = os.path.join(tempfile.mkdtemp(prefix="specta-test-"), "cache.sqlite")   # never the real cache
os.environ["SPECTA_DB"] = os.path.join(tempfile.mkdtemp(prefix="specta-test-"), "specta.sqlite")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
