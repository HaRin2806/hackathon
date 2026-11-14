"""Server configuration. Secrets live only in backend/.env (never in the APK or the web bundle)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent

# OpenAI-compatible chat/completions endpoints (same pattern as P-110 vlm_mass.py).
PROVIDER_PRESETS = {
    "openai": ("https://api.openai.com/v1", "gpt-5.4-mini"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.5-flash"),
    "deepseek": ("https://api.deepseek.com", "deepseek-chat"),
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # "openai" | "gemini" | "deepseek" | "mock" (mock = fixture for offline dev, never shown as AI output)
    ai_provider: str = "gemini"
    ai_api_key: SecretStr = SecretStr("")
    ai_base_url: str = ""  # empty -> preset
    ai_model: str = ""  # empty -> preset
    ai_fallback_model: str = ""  # used when the main model returns 503/404/429 (e.g. gemini-flash-lite-latest)
    ai_reasoning_effort: str = "low"  # "" to omit; keeps thinking models fast (measured ~3s on gemini-3.5-flash)
    ai_timeout_s: float = 45.0
    job_deadline_s: float = 90.0

    data_dir: Path = BACKEND_DIR / "data" / "jobs"
    history_events_path: Path = BACKEND_DIR / "data" / "history_events.json"
    web_dir: Path = ROOT_DIR / "web"

    font_bold: str = ""
    font_regular: str = ""

    max_upload_mb: float = 5.0
    cors_origins: str = "*"

    def resolved_base_url(self) -> str:
        return (self.ai_base_url or PROVIDER_PRESETS.get(self.ai_provider, ("", ""))[0]).rstrip("/")

    def resolved_model(self) -> str:
        if self.ai_provider == "mock":
            return "mock-fixture"
        return self.ai_model or PROVIDER_PRESETS.get(self.ai_provider, ("", ""))[1]


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s
