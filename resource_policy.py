"""Explicit, conservative resource settings shared by local inference paths."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceProfile:
    name: str
    tts_prefetch_chunks: int
    audio_cache_bytes: int


PROFILES = {
    "low_resource": ResourceProfile("low_resource", 1, 128 << 20),
    "standard": ResourceProfile("standard", 2, 512 << 20),
    "high_performance": ResourceProfile("high_performance", 4, 1024 << 20),
}


def get_resource_profile(name: str = "standard", *, custom: ResourceProfile | None = None) -> ResourceProfile:
    """Resolve a named profile or a validated custom policy."""
    if name == "custom":
        if custom is None:
            raise ValueError("Custom resource profile settings are required.")
        values = (custom.tts_prefetch_chunks, custom.audio_cache_bytes)
        if any(value <= 0 for value in values):
            raise ValueError("Custom resource settings must be positive.")
        if custom.tts_prefetch_chunks > 16:
            raise ValueError("Custom queue and batch limits exceed safe bounds.")
        return custom
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown resource profile: {name}") from exc
