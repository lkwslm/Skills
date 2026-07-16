"""Strict, read-only adapters for supported Spec providers."""

from .base import ProviderError
from .openspec import OpenSpecProvider
from .speckit import SpecKitProvider

__all__ = ["OpenSpecProvider", "ProviderError", "SpecKitProvider"]
