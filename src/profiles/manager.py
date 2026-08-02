"""
SimPad — Profile Manager
Handles loading, saving, listing and deleting haptic profiles from disk.
Built-in presets are read-only and always available.
"""

import json
import shutil
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Profiles stored next to the project root
_PROFILES_DIR = Path(__file__).resolve().parent.parent.parent / "profiles"
_VERSION = 1


# =============================================================================
# Built-in presets  (read-only)
# =============================================================================
_PRESETS: Dict[str, dict] = {
    "Default": {
        "lock":       {"enabled": True,  "threshold": 0.15, "low_gain": 0.30, "low_gamma": 1.0,  "high_gain": 1.00, "high_gamma": 1.5},
        "oversteer":  {"enabled": True,  "threshold": 0.12, "low_gain": 1.00, "low_gamma": 1.2,  "high_gain": 0.40, "high_gamma": 1.0},
        "understeer": {"enabled": True,  "threshold": 0.10, "low_gain": 0.50, "low_gamma": 1.5,  "high_gain": 0.80, "high_gamma": 1.0},
        "spin":       {"enabled": True,  "threshold": 0.18, "low_gain": 1.00, "low_gamma": 1.0,  "high_gain": 0.20, "high_gamma": 2.0},
    },
    "Aggressive": {
        "lock":       {"enabled": True,  "threshold": 0.08, "low_gain": 0.60, "low_gamma": 0.7,  "high_gain": 1.50, "high_gamma": 0.8},
        "oversteer":  {"enabled": True,  "threshold": 0.06, "low_gain": 1.50, "low_gamma": 0.8,  "high_gain": 0.80, "high_gamma": 0.8},
        "understeer": {"enabled": True,  "threshold": 0.06, "low_gain": 1.00, "low_gamma": 0.9,  "high_gain": 1.20, "high_gamma": 0.9},
        "spin":       {"enabled": True,  "threshold": 0.10, "low_gain": 1.50, "low_gamma": 0.7,  "high_gain": 0.60, "high_gamma": 1.2},
    },
    "Subtle": {
        "lock":       {"enabled": True,  "threshold": 0.25, "low_gain": 0.15, "low_gamma": 1.5,  "high_gain": 0.50, "high_gamma": 2.0},
        "oversteer":  {"enabled": True,  "threshold": 0.20, "low_gain": 0.50, "low_gamma": 1.5,  "high_gain": 0.20, "high_gamma": 1.5},
        "understeer": {"enabled": True,  "threshold": 0.18, "low_gain": 0.25, "low_gamma": 2.0,  "high_gain": 0.40, "high_gamma": 1.5},
        "spin":       {"enabled": True,  "threshold": 0.28, "low_gain": 0.50, "low_gamma": 1.5,  "high_gain": 0.10, "high_gamma": 2.5},
    },
    "ABS Focus": {
        "lock":       {"enabled": True,  "threshold": 0.08, "low_gain": 0.50, "low_gamma": 0.8,  "high_gain": 1.80, "high_gamma": 0.7},
        "oversteer":  {"enabled": True,  "threshold": 0.15, "low_gain": 0.40, "low_gamma": 1.5,  "high_gain": 0.15, "high_gamma": 1.5},
        "understeer": {"enabled": True,  "threshold": 0.15, "low_gain": 0.20, "low_gamma": 2.0,  "high_gain": 0.15, "high_gamma": 2.0},
        "spin":       {"enabled": True,  "threshold": 0.20, "low_gain": 0.40, "low_gamma": 1.5,  "high_gain": 0.10, "high_gamma": 2.5},
    },
    "Drift": {
        "lock":       {"enabled": True,  "threshold": 0.15, "low_gain": 0.20, "low_gamma": 1.2,  "high_gain": 0.50, "high_gamma": 1.5},
        "oversteer":  {"enabled": True,  "threshold": 0.08, "low_gain": 1.80, "low_gamma": 0.7,  "high_gain": 1.00, "high_gamma": 0.8},
        "understeer": {"enabled": False, "threshold": 0.20, "low_gain": 0.20, "low_gamma": 2.0,  "high_gain": 0.10, "high_gamma": 2.0},
        "spin":       {"enabled": True,  "threshold": 0.10, "low_gain": 1.20, "low_gamma": 0.8,  "high_gain": 0.50, "high_gamma": 1.2},
    },
}

PRESET_NAMES: List[str] = list(_PRESETS.keys())


# =============================================================================
# Profile data model
# =============================================================================
class Profile:
    def __init__(self, name: str, effects: dict, created: str = ""):
        self.name    = name
        self.effects = effects          # {eid: {param: value}}
        self.created = created or datetime.now().isoformat(timespec="seconds")
        self.is_preset = False

    # ── Serialisation ──────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "name":    self.name,
            "version": _VERSION,
            "created": self.created,
            "effects": deepcopy(self.effects),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        return cls(
            name=data["name"],
            effects=data["effects"],
            created=data.get("created", ""),
        )

    @classmethod
    def from_preset(cls, preset_name: str) -> "Profile":
        p = cls(name=preset_name, effects=deepcopy(_PRESETS[preset_name]))
        p.is_preset = True
        return p

    def copy_as(self, new_name: str) -> "Profile":
        return Profile(name=new_name, effects=deepcopy(self.effects))


# =============================================================================
# Profile Manager
# =============================================================================
class ProfileManager:
    """
    Manages user profiles on disk and exposes built-in presets.

    Profiles are stored as JSON files in <project_root>/profiles/.
    Presets are hardcoded and read-only.
    """

    def __init__(self):
        _PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, Profile] = {}
        self._load_all()

    # ── Disk I/O ───────────────────────────────────────────────────────────

    def _load_all(self):
        self._cache.clear()
        for path in sorted(_PROFILES_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                p = Profile.from_dict(data)
                self._cache[p.name] = p
            except Exception as e:
                print(f"[PROFILES] Failed to load {path.name}: {e}", flush=True)

    def save(self, profile: Profile) -> bool:
        """Persist a profile to disk. Returns True on success."""
        if profile.is_preset:
            return False   # never overwrite presets
        try:
            path = self._profile_path(profile.name)
            path.write_text(
                json.dumps(profile.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._cache[profile.name] = profile
            return True
        except Exception as e:
            print(f"[PROFILES] Save error: {e}", flush=True)
            return False

    def delete(self, name: str) -> bool:
        """Delete a user profile from disk. Cannot delete presets."""
        if name in PRESET_NAMES:
            return False
        path = self._profile_path(name)
        if path.exists():
            path.unlink()
        self._cache.pop(name, None)
        return True

    def rename(self, old_name: str, new_name: str) -> bool:
        """Rename a user profile."""
        if old_name in PRESET_NAMES or new_name in PRESET_NAMES:
            return False
        if old_name not in self._cache:
            return False
        profile = self._cache[old_name]
        old_path = self._profile_path(old_name)
        profile.name = new_name
        if old_path.exists():
            old_path.unlink()
        self._cache.pop(old_name)
        return self.save(profile)

    # ── Queries ────────────────────────────────────────────────────────────

    def list_user_profiles(self) -> List[str]:
        return sorted(self._cache.keys())

    def list_all(self) -> List[str]:
        """Presets first, then user profiles."""
        return PRESET_NAMES + self.list_user_profiles()

    def get(self, name: str) -> Optional[Profile]:
        if name in PRESET_NAMES:
            return Profile.from_preset(name)
        return self._cache.get(name)

    def exists(self, name: str) -> bool:
        return name in PRESET_NAMES or name in self._cache

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _profile_path(name: str) -> Path:
        safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
        return _PROFILES_DIR / f"{safe}.json"

    def duplicate(self, name: str, new_name: str) -> Optional[Profile]:
        """Duplicate any profile (including presets) under a new user name."""
        src = self.get(name)
        if src is None:
            return None
        copy = src.copy_as(new_name)
        self.save(copy)
        return copy
