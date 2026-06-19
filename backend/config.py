"""Central configuration — reads from .env via python-dotenv, exposes typed settings.

Usage:
    from backend.config import Settings, settings
    gateway = WebRTCGateway(api_key=settings.livekit_api_key, ...)

Environment variables (set in .env at project root):
    LIVEKIT_HOST           - LiveKit server hostname  (default: localhost)
    LIVEKIT_PORT           - LiveKit server port      (default: 7880)
    LIVEKIT_API_KEY        - LiveKit API key
    LIVEKIT_API_SECRET     - LiveKit API secret
    WITNESS_PREP_API_KEYS  - Comma-separated API keys (default: dev-key)
    CORS_ORIGINS           - Comma-separated allowed origins (default: *)
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Resolve project root once (backend/config.py -> backend/ -> project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env from project root — silent if missing
load_dotenv(PROJECT_ROOT / ".env")


class Settings:
    """Typed reader for environment-based config. Immutable by convention."""

    def __init__(self) -> None:
        self.livekit_host: str = os.getenv("LIVEKIT_HOST", "localhost")
        self.livekit_port: int = int(os.getenv("LIVEKIT_PORT", "7880"))
        self.livekit_api_key: str = os.getenv("LIVEKIT_API_KEY", "")
        self.livekit_api_secret: str = os.getenv("LIVEKIT_API_SECRET", "")

        # Auth
        raw_keys = os.getenv("WITNESS_PREP_API_KEYS", "")
        self.api_keys: set[str] = {k.strip() for k in raw_keys.split(",") if k.strip()}
        if not self.api_keys:
            self.api_keys = {"dev-key"}

        # OpenRouter (LLM inference)
        self.openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
        self.openrouter_base_url: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        self.openrouter_model: str = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")

        # CORS
        raw_origins = os.getenv("CORS_ORIGINS", "*")
        self.cors_origins: list[str] = [o.strip() for o in raw_origins.split(",") if o.strip()]
        if not self.cors_origins:
            self.cors_origins = ["*"]

        self.log_dir: Path = Path(os.getenv("WITNESS_PREP_LOG_DIR", str(PROJECT_ROOT / "data" / "sessions")))
        self.data_dir: Path = PROJECT_ROOT / "data"
        self.frontend_dir: Path = PROJECT_ROOT / "frontend"


# Module-level singleton — import `settings` anywhere, it's always current.
settings = Settings()
