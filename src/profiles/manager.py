"""
SimPad — Dynamic Graph Profile Manager.
Loads, saves, lists, and monitors JSON profiles directly from the profiles/ directory.
Supports read-only preset protection and profile cloning.
"""

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_PROFILES_DIR = Path(__file__).resolve().parent.parent.parent / "profiles"
_VERSION = 2


# TODO: [SRP] GraphProfile is a pure data class representing profile state and metadata serialization.
class GraphProfile:
    """Encapsulates a graph profile model loaded from a JSON file."""
    def __init__(self, name: str, graph_data: dict, is_preset: bool = False, created: str = ""):
        self.name = name
        self.graph_data = graph_data
        self.is_preset = is_preset
        self.created = created or datetime.now().isoformat(timespec="seconds")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "preset": self.is_preset,
            "version": _VERSION,
            "created": self.created,
            "graph_data": deepcopy(self.graph_data),
        }

    @classmethod
    def from_dict(cls, data: dict, fallback_name: str = "Custom") -> "GraphProfile":
        name = data.get("name", fallback_name)
        is_preset = bool(data.get("preset", False))
        graph_data = data.get("graph_data", {"nodes": {}, "links": []})
        created = data.get("created", "")
        return cls(name=name, graph_data=graph_data, is_preset=is_preset, created=created)


# TODO: [SRP] GraphProfileManager manages profile persistence, disk monitoring, and active profile selection.
class GraphProfileManager:
    """Manages profile loading, saving, cloning, and dynamic directory watching."""

    def __init__(self):
        _PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        self.profiles: Dict[str, GraphProfile] = {}
        self._active_profile_name: str = "Default"
        self._file_mtimes: Dict[Path, float] = {}

        self.reload_all()

    # TODO: [SLAP] Keep reload_all at a single level of abstraction by delegating file parsing to helper.
    def reload_all(self) -> bool:
        """Reloads all JSON profiles from the profiles/ directory."""
        self.profiles.clear()
        self._file_mtimes.clear()

        json_files = list(_PROFILES_DIR.glob("*.json"))
        for json_path in json_files:
            self._load_single_file(json_path)

        # Ensure Default profile exists
        if "Default" not in self.profiles and self.profiles:
            self._active_profile_name = next(iter(self.profiles.keys()))

        return True

    def _load_single_file(self, json_path: Path):
        try:
            mtime = json_path.stat().st_mtime
            self._file_mtimes[json_path] = mtime

            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            prof_name = json_path.stem
            prof = GraphProfile.from_dict(data, fallback_name=prof_name)
            prof.name = prof_name
            self.profiles[prof_name] = prof
        except Exception as e:
            print(f"[ProfileManager] Error loading {json_path}: {e}")

    def check_for_changes(self) -> bool:
        """
        Polls the profiles/ directory for file additions, deletions or modifications.
        Returns True if changes occurred on disk and profiles were reloaded.
        """
        current_files = set(_PROFILES_DIR.glob("*.json"))
        known_files = set(self._file_mtimes.keys())

        if current_files != known_files:
            self.reload_all()
            return True

        for json_path in current_files:
            try:
                mtime = json_path.stat().st_mtime
                if mtime != self._file_mtimes.get(json_path, 0):
                    self.reload_all()
                    return True
            except OSError:
                pass

        return False

    def list_names(self) -> List[str]:
        """Returns sorted list of available profile names."""
        return sorted(list(self.profiles.keys()))

    def get_profile(self, name: str) -> Optional[GraphProfile]:
        return self.profiles.get(name)

    def get_active(self) -> GraphProfile:
        return self.profiles.get(self._active_profile_name) or next(iter(self.profiles.values()), GraphProfile("Default", {"nodes": {}, "links": []}, is_preset=True))

    def set_active(self, name: str) -> bool:
        if name in self.profiles:
            self._active_profile_name = name
            return True
        return False

    # TODO: [DRY] save_profile and clone_profile delegate disk serialization to helper _write_profile_to_disk.
    def save_profile(self, name: str, graph_data: dict) -> Tuple[Optional[GraphProfile], str]:
        """
        Saves profile to disk. Returns (profile, error_msg).
        Rejects saving if active profile is a read-only preset.
        """
        existing = self.profiles.get(name)
        if existing and existing.is_preset:
            return None, f"'{name}' is a read-only preset. Use Clone to create an editable copy."

        prof = GraphProfile(name=name, graph_data=graph_data, is_preset=False)
        return self._write_profile_to_disk(prof)

    def clone_profile(self, source_name: str, new_name: str = "") -> Tuple[Optional[GraphProfile], str]:
        """Clones an existing profile (preset or user profile) into a new editable profile."""
        source_prof = self.get_profile(source_name)
        if not source_prof:
            return None, f"Source profile '{source_name}' not found."

        if not new_name:
            base_name = f"{source_name} Copy"
            new_name = base_name
            counter = 1
            while new_name in self.profiles:
                counter += 1
                new_name = f"{base_name} {counter}"

        cloned_data = deepcopy(source_prof.graph_data)
        cloned_prof = GraphProfile(name=new_name, graph_data=cloned_data, is_preset=False)
        return self._write_profile_to_disk(cloned_prof)

    # TODO: [DRY] Private helper to write profile JSON to disk and register file modification time.
    def _write_profile_to_disk(self, prof: GraphProfile) -> Tuple[Optional[GraphProfile], str]:
        name = prof.name
        self.profiles[name] = prof
        self._active_profile_name = name

        file_path = _PROFILES_DIR / f"{name}.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(prof.to_dict(), f, indent=2)
            self._file_mtimes[file_path] = file_path.stat().st_mtime
            return prof, "OK"
        except Exception as e:
            return None, f"Failed to write file: {e}"

    def delete_profile(self, name: str) -> Tuple[bool, str]:
        """Deletes a user profile. Rejects deletion if it's a built-in preset."""
        prof = self.profiles.get(name)
        if not prof:
            return False, f"Profile '{name}' does not exist."

        if prof.is_preset:
            return False, f"Cannot delete built-in preset '{name}'."

        del self.profiles[name]
        file_path = _PROFILES_DIR / f"{name}.json"
        if file_path.exists():
            try:
                file_path.unlink()
            except Exception as e:
                return False, f"Error deleting file: {e}"

        if file_path in self._file_mtimes:
            del self._file_mtimes[file_path]

        if self._active_profile_name == name:
            self._active_profile_name = next(iter(self.profiles.keys()), "Default")

        return True, "OK"
