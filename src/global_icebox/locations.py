"""Named filesystem roots, so ideas can cite files that exist on more than one machine.

An idea is worth ranking partly because of where its plan lives, but a raw path is wrong the
moment it is read on the other machine: `/Users/x/code/projects/...` means nothing on the
Windows PC, and `C:\\Users\\x\\code\\projects\\...` means nothing here. So the database stores a
*logical* reference — `future_work/mcp-servers.md` — and each machine keeps its own mapping
from `future_work` to a real directory.

The mapping is deliberately NOT stored in the database and NOT committed to the repo:

- not in the database, because the database is per-machine by owner decision (backup only,
  never synced) and the mapping is exactly the part that must differ per machine;
- not in the repo, because the repo IS shared between machines, so a committed config would be
  correct on one and wrong on the other — the same class of mistake as start.ps1 pinning
  `UV_PYTHON` to a Windows filename.

It lives in the user's own config directory instead, and is written through `set_location` so a
new setup can record itself once rather than being edited by hand.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Reserved so a location name can never collide with the path syntax used to reference it.
_ILLEGAL = set('/\\:*?"<>|')

CONFIG_ENV = "CONCINNITY_CONFIG"
DB_ENV = "GLOBAL_ICEBOX_DB_PATH"


def config_path() -> Path:
    """Where this machine's mapping lives. Overridable so tests never touch the real config."""
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override)
    return Path.home() / ".concinnity" / "config.json"


def validate_name(name: str) -> str:
    value = (name or "").strip()
    if not value:
        raise ValueError("location name is required")
    if any(ch in _ILLEGAL for ch in value):
        raise ValueError(
            "location name must not contain path separators or wildcards; got "
            f"{name!r}"
        )
    return value


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {"locations": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        # Refuse rather than silently starting from an empty mapping: overwriting a config the
        # user hand-edited into invalid JSON would destroy the only copy of their paths.
        raise ValueError(f"{path} is not valid JSON ({exc}); refusing to overwrite it") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    locations = data.get("locations") or {}
    if not isinstance(locations, dict):
        raise ValueError(f"{path}: 'locations' must be a JSON object")
    data["locations"] = {str(k): str(v) for k, v in locations.items()}
    return data


def save_config(data: dict[str, Any]) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def list_locations() -> dict[str, Any]:
    data = load_config()
    out: dict[str, Any] = {}
    for name, raw in sorted(data["locations"].items()):
        p = Path(raw).expanduser()
        # `exists` is reported, never enforced. A machine may legitimately hold a mapping for a
        # directory that only exists on the other one, and refusing to record it would make the
        # config unusable as the shared vocabulary it is meant to be.
        out[name] = {"path": str(p), "exists": p.exists()}
    return {
        "config_path": str(config_path()),
        "config_exists": config_path().exists(),
        "db_path_env": os.environ.get(DB_ENV),
        "locations": out,
    }


def set_location(name: str, path: str) -> dict[str, Any]:
    name = validate_name(name)
    if not (path or "").strip():
        raise ValueError("path is required")
    resolved = Path(path).expanduser()
    data = load_config()
    previous = data["locations"].get(name)
    data["locations"][name] = str(resolved)
    saved = save_config(data)
    return {
        "name": name,
        "path": str(resolved),
        "previous_path": previous,
        "exists": resolved.exists(),
        "config_path": str(saved),
    }


def remove_location(name: str) -> dict[str, Any]:
    name = validate_name(name)
    data = load_config()
    if name not in data["locations"]:
        raise ValueError(f"no location named {name!r}")
    removed = data["locations"].pop(name)
    saved = save_config(data)
    return {"name": name, "removed_path": removed, "config_path": str(saved)}


def resolve_location(reference: str) -> dict[str, Any]:
    """Turn `name/relative/path` (or bare `name`) into a real path on THIS machine."""
    ref = (reference or "").strip()
    if not ref:
        raise ValueError("reference is required")
    ref = ref.replace("\\", "/")
    name, _, remainder = ref.partition("/")
    name = validate_name(name)
    data = load_config()
    if name not in data["locations"]:
        known = ", ".join(sorted(data["locations"])) or "(none configured)"
        raise ValueError(
            f"unknown location {name!r}. Known locations: {known}. "
            "Record it with set_location before referencing it."
        )
    root = Path(data["locations"][name]).expanduser()
    target = root / remainder if remainder else root
    # Containment check: a reference must not climb out of its own root via '..'.
    try:
        target.resolve().relative_to(root.resolve())
    except ValueError:
        raise ValueError(f"{reference!r} escapes the {name!r} location root") from None
    return {
        "reference": reference,
        "location": name,
        "root": str(root),
        "path": str(target),
        "exists": target.exists(),
    }
