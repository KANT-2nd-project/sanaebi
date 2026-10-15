"""Deterministic hashes shared by current evaluation entrypoints.

Historical experiment runners retain their original helpers and manifests.
"""

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path


def digest(value):
    """Hash canonical JSON using the existing selection serialization contract."""
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def file_hashes(paths: Iterable[str]) -> dict[str, str | None]:
    """Keep supplied path keys and represent missing/non-file paths as None."""
    return {
        name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
        if Path(name).is_file()
        else None
        for name in paths
    }
