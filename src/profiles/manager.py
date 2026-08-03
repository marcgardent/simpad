"""
SimPad — Graph Profile Manager
Handles loading, saving, listing and deleting Node Graph profiles from disk.
Built-in presets are full visual node graphs that compile into real-time Python expressions.
"""

import json
import shutil
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

_PROFILES_DIR = Path(__file__).resolve().parent.parent.parent / "profiles"
_VERSION = 2


# =============================================================================
# Built-in Node Graph Presets
# =============================================================================
_GRAPH_PRESETS: Dict[str, dict] = {
    "Default": {
        "nodes": {
            "node_tf_abs": {
                "type": "transform", "in_attr": "attr_in_tf_abs", "out_attr": "attr_out_tf_abs",
                "thresh": 0.15, "gain": 1.0, "gamma": 1.0, "pos": [260.0, 40.0]
            },
            "node_shape_abs": {
                "type": "shape", "in_attr": "attr_in_shape_abs", "in_on": "attr_in_shape_abs_on", "in_off": "attr_in_shape_abs_off",
                "out_attr": "attr_out_shape_abs", "shape": "Square (Pulsed)", "on_ms": 20.0, "off_ms": 30.0, "pos": [460.0, 40.0]
            },
            "node_tf_tc": {
                "type": "transform", "in_attr": "attr_in_tf_tc", "out_attr": "attr_out_tf_tc",
                "thresh": 0.10, "gain": 1.0, "gamma": 1.2, "pos": [260.0, 260.0]
            }
        },
        "links": [
            ["attr_out_abs", "attr_in_tf_abs"],
            ["attr_out_tf_abs", "attr_in_shape_abs"],
            ["attr_out_shape_abs", "attr_in_high"],
            ["attr_out_tc", "attr_in_tf_tc"],
            ["attr_out_tf_tc", "attr_in_low"]
        ]
    },

    "Aggressive": {
        "nodes": {
            "node_tf_abs": {
                "type": "transform", "in_attr": "attr_in_tf_abs", "out_attr": "attr_out_tf_abs",
                "thresh": 0.05, "gain": 1.5, "gamma": 0.7, "pos": [260.0, 40.0]
            },
            "node_shape_abs": {
                "type": "shape", "in_attr": "attr_in_shape_abs", "in_on": "attr_in_shape_abs_on", "in_off": "attr_in_shape_abs_off",
                "out_attr": "attr_out_shape_abs", "shape": "Square (Pulsed)", "on_ms": 15.0, "off_ms": 20.0, "pos": [460.0, 40.0]
            },
            "node_tf_tc": {
                "type": "transform", "in_attr": "attr_in_tf_tc", "out_attr": "attr_out_tf_tc",
                "thresh": 0.05, "gain": 1.5, "gamma": 0.8, "pos": [260.0, 260.0]
            }
        },
        "links": [
            ["attr_out_abs", "attr_in_tf_abs"],
            ["attr_out_tf_abs", "attr_in_shape_abs"],
            ["attr_out_shape_abs", "attr_in_high"],
            ["attr_out_tc", "attr_in_tf_tc"],
            ["attr_out_tf_tc", "attr_in_low"]
        ]
    },

    "Subtle": {
        "nodes": {
            "node_tf_abs": {
                "type": "transform", "in_attr": "attr_in_tf_abs", "out_attr": "attr_out_tf_abs",
                "thresh": 0.25, "gain": 0.5, "gamma": 1.5, "pos": [260.0, 40.0]
            },
            "node_shape_abs": {
                "type": "shape", "in_attr": "attr_in_shape_abs", "in_on": "attr_in_shape_abs_on", "in_off": "attr_in_shape_abs_off",
                "out_attr": "attr_out_shape_abs", "shape": "Sine (Smooth)", "on_ms": 30.0, "off_ms": 45.0, "pos": [460.0, 40.0]
            },
            "node_tf_tc": {
                "type": "transform", "in_attr": "attr_in_tf_tc", "out_attr": "attr_out_tf_tc",
                "thresh": 0.20, "gain": 0.5, "gamma": 1.5, "pos": [260.0, 260.0]
            }
        },
        "links": [
            ["attr_out_abs", "attr_in_tf_abs"],
            ["attr_out_tf_abs", "attr_in_shape_abs"],
            ["attr_out_shape_abs", "attr_in_high"],
            ["attr_out_tc", "attr_in_tf_tc"],
            ["attr_out_tf_tc", "attr_in_low"]
        ]
    },

    "ABS Focus": {
        "nodes": {
            "node_tf_abs": {
                "type": "transform", "in_attr": "attr_in_tf_abs", "out_attr": "attr_out_tf_abs",
                "thresh": 0.08, "gain": 1.8, "gamma": 0.7, "pos": [260.0, 40.0]
            },
            "node_shape_abs": {
                "type": "shape", "in_attr": "attr_in_shape_abs", "in_on": "attr_in_shape_abs_on", "in_off": "attr_in_shape_abs_off",
                "out_attr": "attr_out_shape_abs", "shape": "Square (Pulsed)", "on_ms": 18.0, "off_ms": 25.0, "pos": [460.0, 40.0]
            }
        },
        "links": [
            ["attr_out_abs", "attr_in_tf_abs"],
            ["attr_out_tf_abs", "attr_in_shape_abs"],
            ["attr_out_shape_abs", "attr_in_high"]
        ]
    },

    "Drift": {
        "nodes": {
            "node_tf_over": {
                "type": "transform", "in_attr": "attr_in_tf_over", "out_attr": "attr_out_tf_over",
                "thresh": 0.08, "gain": 1.8, "gamma": 0.7, "pos": [260.0, 140.0]
            },
            "node_shape_over": {
                "type": "shape", "in_attr": "attr_in_shape_over", "in_on": "attr_in_shape_over_on", "in_off": "attr_in_shape_over_off",
                "out_attr": "attr_out_shape_over", "shape": "Sine (Smooth)", "on_ms": 20.0, "off_ms": 30.0, "pos": [460.0, 140.0]
            }
        },
        "links": [
            ["attr_out_over", "attr_in_tf_over"],
            ["attr_out_tf_over", "attr_in_shape_over"],
            ["attr_out_shape_over", "attr_in_low"]
        ]
    }
}

PRESET_NAMES: List[str] = list(_GRAPH_PRESETS.keys())


# =============================================================================
# Graph Profile Model
# =============================================================================
class GraphProfile:
    def __init__(self, name: str, graph_data: dict, created: str = ""):
        self.name = name
        self.graph_data = graph_data
        self.created = created or datetime.now().isoformat(timespec="seconds")
        self.is_preset = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": _VERSION,
            "created": self.created,
            "graph_data": deepcopy(self.graph_data),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GraphProfile":
        return cls(
            name=data["name"],
            graph_data=data.get("graph_data", {"nodes": {}, "links": []}),
            created=data.get("created", ""),
        )

    @classmethod
    def from_preset(cls, preset_name: str) -> "GraphProfile":
        p = cls(name=preset_name, graph_data=deepcopy(_GRAPH_PRESETS.get(preset_name, {"nodes": {}, "links": []})))
        p.is_preset = True
        return p


# =============================================================================
# Graph Profile Manager
# =============================================================================
class GraphProfileManager:
    def __init__(self):
        _PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        self.profiles: Dict[str, GraphProfile] = {}
        self._active_profile_name: str = "Default"

        self.reload_all()

    def reload_all(self):
        self.profiles.clear()
        for name in PRESET_NAMES:
            self.profiles[name] = GraphProfile.from_preset(name)

        for json_path in _PROFILES_DIR.glob("*.json"):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                prof = GraphProfile.from_dict(data)
                self.profiles[prof.name] = prof
            except Exception as e:
                print(f"[ProfileManager] Error loading {json_path}: {e}")

    def list_names(self) -> List[str]:
        return list(self.profiles.keys())

    def get_profile(self, name: str) -> Optional[GraphProfile]:
        return self.profiles.get(name)

    def get_active(self) -> GraphProfile:
        return self.profiles.get(self._active_profile_name, GraphProfile.from_preset("Default"))

    def set_active(self, name: str) -> bool:
        if name in self.profiles:
            self._active_profile_name = name
            return True
        return False

    def save_profile(self, name: str, graph_data: dict) -> GraphProfile:
        prof = GraphProfile(name=name, graph_data=graph_data)
        self.profiles[name] = prof
        self._active_profile_name = name

        file_path = _PROFILES_DIR / f"{name}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(prof.to_dict(), f, indent=2)

        return prof

    def delete_profile(self, name: str) -> bool:
        if name in PRESET_NAMES:
            return False  # Presets cannot be deleted
        if name in self.profiles:
            del self.profiles[name]
            file_path = _PROFILES_DIR / f"{name}.json"
            if file_path.exists():
                file_path.unlink()
            if self._active_profile_name == name:
                self._active_profile_name = "Default"
            return True
        return False
