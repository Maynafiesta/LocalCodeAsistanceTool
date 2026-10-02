import json
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    upstream: str = "http://127.0.0.1:11434"
    tokens: dict[str, str] = field(default_factory=dict)
    chat_model: str = "qwen2.5-coder:7b-instruct-q4_K_M"
    completion_model: str = "qwen2.5-coder:1.5b-base"
    concurrency: int = 3
    queue_size: int = 15
    chat_wait: float = 30.0
    completion_wait: float = 2.0
    upstream_timeout: float = 120.0
    context_length: int = 4096
    completion_context_length: int = 8192
    completion_max_tokens: int = 256
    max_body_bytes: int = 1_048_576
    index_path: str = "data/context.sqlite"
    retrieval_chars: int = 6000
    monitor_users: tuple[str, ...] = ("developer",)

    def __post_init__(self):
        if not self.tokens or any(not u or len(t) < 32 for u, t in self.tokens.items()):
            raise ValueError("CODEASSIST_TOKENS must map users to tokens of at least 32 characters")
        if len(set(self.tokens.values())) != len(self.tokens):
            raise ValueError("Each user must have a unique token")
        if (
            self.concurrency < 1
            or self.queue_size < 0
            or min(self.context_length, self.completion_context_length) < 512
        ):
            raise ValueError("Invalid concurrency, queue size or context length")
        if not 1 <= self.completion_max_tokens < self.completion_context_length:
            raise ValueError("Completion token limit must be positive and smaller than its context")
        if min(self.chat_wait, self.completion_wait, self.upstream_timeout) <= 0:
            raise ValueError("Timeouts must be positive")
        if not isinstance(self.monitor_users, (list, tuple)) or any(
            not isinstance(user, str) or not user for user in self.monitor_users
        ):
            raise ValueError("MONITOR_USERS must be a JSON array of user names")

    @classmethod
    def from_env(cls):
        tokens = json.loads(os.environ.get("CODEASSIST_TOKENS", "{}"))
        if not isinstance(tokens, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in tokens.items()
        ):
            raise ValueError("CODEASSIST_TOKENS must be a JSON object of strings")
        monitor_users = json.loads(os.environ.get("MONITOR_USERS", '["developer"]'))
        if not isinstance(monitor_users, list) or any(
            not isinstance(user, str) or not user for user in monitor_users
        ):
            raise ValueError("MONITOR_USERS must be a JSON array of user names")
        return cls(
            upstream=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
            tokens=tokens,
            chat_model=os.environ.get("CHAT_MODEL", cls.chat_model),
            completion_model=os.environ.get("COMPLETION_MODEL", cls.completion_model),
            concurrency=int(os.environ.get("MAX_CONCURRENT_REQUESTS", "3")),
            queue_size=int(os.environ.get("MAX_QUEUED_REQUESTS", "15")),
            context_length=int(os.environ.get("MODEL_CONTEXT_LENGTH", "4096")),
            completion_context_length=int(os.environ.get("COMPLETION_CONTEXT_LENGTH", "8192")),
            completion_max_tokens=int(os.environ.get("COMPLETION_MAX_TOKENS", "256")),
            index_path=os.environ.get("CONTEXT_INDEX_PATH", "data/context.sqlite"),
            monitor_users=tuple(monitor_users),
        )
