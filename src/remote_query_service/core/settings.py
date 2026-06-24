from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from remote_query_service.core.models import PolicyDocument

_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    # Prefer REMOTE_QUERY_* names and continue accepting LOGTAIL_* for compatibility.
    policy_path: Path = Field(
        default=Path("config/policy.json"),
        validation_alias=AliasChoices("REMOTE_QUERY_POLICY_PATH", "LOGTAIL_POLICY_PATH"),
    )
    session_ttl_seconds: int = Field(
        default=1800,
        validation_alias=AliasChoices("REMOTE_QUERY_SESSION_TTL_SECONDS", "LOGTAIL_SESSION_TTL_SECONDS"),
    )
    max_chunk_bytes: int = Field(
        default=65536,
        validation_alias=AliasChoices("REMOTE_QUERY_MAX_CHUNK_BYTES", "LOGTAIL_MAX_CHUNK_BYTES"),
    )
    default_lines: int = Field(
        default=200,
        validation_alias=AliasChoices("REMOTE_QUERY_DEFAULT_LINES", "LOGTAIL_DEFAULT_LINES"),
    )
    redact_patterns: str = Field(
        default="",
        validation_alias=AliasChoices("REMOTE_QUERY_REDACT_PATTERNS", "LOGTAIL_REDACT_PATTERNS"),
    )
    redis_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("REMOTE_QUERY_REDIS_URL", "LOGTAIL_REDIS_URL"),
    )
    api_keys: str = Field(
        default="",
        validation_alias=AliasChoices("REMOTE_QUERY_API_KEYS", "LOGTAIL_API_KEYS"),
    )
    error_log_path: Path | None = Field(
        default=Path("var/error.log"),
        validation_alias=AliasChoices("REMOTE_QUERY_ERROR_LOG_PATH", "LOGTAIL_ERROR_LOG_PATH"),
    )
    audit_log_path: Path | None = Field(
        default=Path("var/audit.log"),
        validation_alias=AliasChoices("REMOTE_QUERY_AUDIT_LOG_PATH", "LOGTAIL_AUDIT_LOG_PATH"),
    )
    # SSH defaults applied to any host policy that omits these fields.
    ssh_default_user: str | None = Field(
        default=None,
        validation_alias="REMOTE_QUERY_SSH_DEFAULT_USER",
    )
    ssh_default_key_path: str | None = Field(
        default=None,
        validation_alias="REMOTE_QUERY_SSH_DEFAULT_KEY_PATH",
    )
    ssh_default_known_hosts: str | None = Field(
        default=None,
        validation_alias="REMOTE_QUERY_SSH_DEFAULT_KNOWN_HOSTS",
    )

    def load_policy(self) -> PolicyDocument:
        # Build substitution context: .env file values as base, os.environ takes precedence.
        # This ensures plain vars like SSH_USER and SSH_KEY_PATH defined in .env are expanded
        # even though pydantic-settings only loads declared fields into Settings attributes.
        env_file = self.model_config.get("env_file", ".env")
        try:
            from dotenv import dotenv_values
            env_context: dict[str, str] = {
                k: v for k, v in {**dotenv_values(env_file), **os.environ}.items() if v is not None
            }
        except ImportError:
            env_context = dict(os.environ)
        try:
            raw = self.policy_path.read_text(encoding="utf-8")
            raw = _ENV_VAR_RE.sub(lambda m: env_context.get(m.group(1), m.group(0)), raw)
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in policy file '{self.policy_path}': {exc}") from exc
        self._apply_ssh_defaults(data)
        return PolicyDocument.model_validate(data)

    def _apply_ssh_defaults(self, policy_data: dict) -> None:
        for host in policy_data.get("hosts", []):
            if not host.get("username") and self.ssh_default_user:
                host["username"] = self.ssh_default_user
            if not host.get("private_key_path") and self.ssh_default_key_path:
                host["private_key_path"] = self.ssh_default_key_path
            if "known_hosts_path" not in host and self.ssh_default_known_hosts:
                host["known_hosts_path"] = self.ssh_default_known_hosts

    def compiled_redactions(self) -> list[re.Pattern[str]]:
        if not self.redact_patterns.strip():
            return []
        return [re.compile(pattern) for pattern in self.redact_patterns.split("||") if pattern]

    def parsed_api_keys(self) -> dict[str, str]:
        mappings: dict[str, str] = {}
        if not self.api_keys.strip():
            return mappings
        for pair in self.api_keys.split(","):
            token, sep, subject = pair.partition(":")
            if not sep or not token or not subject:
                raise ValueError(
                    "REMOTE_QUERY_API_KEYS entries must use token:subject format"
                    " (LOGTAIL_API_KEYS is still accepted for compatibility)"
                )
            mappings[token.strip()] = subject.strip()
        return mappings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

