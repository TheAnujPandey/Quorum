from contextvars import ContextVar

llm_overrides: ContextVar[dict[str, str]] = ContextVar("llm_overrides", default={})
