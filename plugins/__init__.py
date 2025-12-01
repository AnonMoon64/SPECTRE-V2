"""plugins package entrypoint.

This module delegates plugin discovery to `plugins.loader` which implements
metadata-first loading and keeps a backwards-compatible class-name shim.
"""
from .loader import load_plugins

__all__ = ["load_plugins"]