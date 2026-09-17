"""Central configuration, read from environment variables."""

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Anthropic
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    anthropic_max_tokens: int = int(os.getenv("ANTHROPIC_MAX_TOKENS", "2048"))

    # Storage
    db_path: str = os.getenv("LOGSENSE_DB_PATH", "logsense.db")

    # Triage
    drain_depth: int = int(os.getenv("DRAIN_DEPTH", "4"))
    drain_sim_threshold: float = float(os.getenv("DRAIN_SIM_THRESHOLD", "0.5"))
    drain_max_children: int = int(os.getenv("DRAIN_MAX_CHILDREN", "100"))
    min_cluster_size_for_rca: int = int(os.getenv("MIN_CLUSTER_SIZE_FOR_RCA", "2"))

    # Actions
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    github_repo: str = os.getenv("GITHUB_REPO", "")  # owner/repo
    dry_run: bool = os.getenv("LOGSENSE_DRY_RUN", "true").lower() != "false"

    # API
    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("API_PORT", "8000"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    # Test flags
    live_tests: bool = os.getenv("LOGSENSE_LIVE_TESTS", "").lower() == "1"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
