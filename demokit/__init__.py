"""Shared plumbing for the demos: settings, model calls, memory on either base, the web shell."""

from .config import ROOT, ConfigError, load_env, mode, model, require
from .memory import Hit, Memory, Recall

__all__ = ["ROOT", "ConfigError", "Hit", "Memory", "Recall", "load_env", "mode", "model", "require"]
