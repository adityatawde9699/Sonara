"""Import llama-cpp-python without the diskcache package (CVE-2025-69872).

llama-cpp-python declares a hard dependency on ``diskcache`` and imports it
when ``llama_cpp`` loads, but only uses it for ``LlamaDiskCache``. Every
diskcache release through 5.6.3, the latest, unpickles cache entries by
default. Anyone who can write to the cache directory can therefore run code
in the process that reads it (PYSEC-2026-2447 / GHSA-w8v5-vhqr-4h9v). No
fixed release exists.

Sonara never uses a llama.cpp disk cache. So it installs llama-cpp-python
with ``--no-deps``, leaves diskcache out entirely (see
``requirements-llm-nodeps.txt``), and registers this disabled stand-in before
importing ``llama_cpp``. The stand-in satisfies the import and refuses to
build a cache. It is installed even when a real diskcache is present, so the
unpickling code is never loaded into a Sonara process.
"""

from __future__ import annotations

import sys
import types
from typing import Any

DISKCACHE_ADVISORY = "PYSEC-2026-2447 (CVE-2025-69872)"


class DiskCacheDisabled(RuntimeError):
    """Raised when code tries to use diskcache inside Sonara."""


def _disabled(*_args: Any, **_kwargs: Any) -> Any:
    raise DiskCacheDisabled(
        "diskcache is disabled in Sonara: it deserializes cache files with pickle "
        f"({DISKCACHE_ADVISORY}), and Sonara does not use a llama.cpp disk cache."
    )


def _disabled_diskcache_module() -> types.ModuleType:
    module = types.ModuleType("diskcache", "Disabled by Sonara; see llama_runtime.py.")
    module.__sonara_disabled__ = True  # type: ignore[attr-defined]
    for name in ("Cache", "FanoutCache", "Deque", "Index", "Disk", "JSONDisk"):
        module.__dict__[name] = type(name, (), {"__init__": _disabled})
    return module


def install_diskcache_guard() -> None:
    """Make ``import diskcache`` yield the disabled stand-in in this process."""
    existing = sys.modules.get("diskcache")
    if existing is not None and getattr(existing, "__sonara_disabled__", False):
        return
    # Replace a real, already-imported module too: nothing in Sonara may use it.
    sys.modules["diskcache"] = _disabled_diskcache_module()


def import_llama() -> Any:
    """Return ``llama_cpp.Llama`` with the diskcache guard in place."""
    install_diskcache_guard()
    from llama_cpp import Llama

    return Llama
