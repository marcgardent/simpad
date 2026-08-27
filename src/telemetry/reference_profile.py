"""
SimPad Telemetry — Modèle de Profil de Tour de Référence et d'Annotations de Piste.
Gère les données spatiales mètre par mètre (vitesse, accélérateur, frein, volant)
et les marqueurs de repères (Frein, Turn-In, Virages T1..T30, Rapports de boîte G1..G8).

Architecture SOLID (SRP, OCP, DIP) :
- Télémétrie du meilleur tour : enregistrée et sauvée automatiquement dans 'ref_<track>_<car>.json'.
- Annotations / Repères : cycle de vie séparé, sauvées automatiquement au fil des modifications
  dans '<nom_fichier>.marks.json'.
"""

from dataclasses import dataclass, field
from enum import Enum
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import uuid

logger = logging.getLogger(__name__)

# Dossier par défaut des profils de tours de référence
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_REF_LAPS_DIR = _PROJECT_ROOT / "profiles" / "ref_laps"


def get_marks_filepath(telemetry_filepath: Path) -> Path:
    """
    Retourne le chemin du fichier d'annotations '.marks.json' associé à un fichier de télémétrie.
    Exemple: 'ref_spa_hypercar.json' -> 'ref_spa_hypercar.marks.json'.
    """
    telemetry_filepath = Path(telemetry_filepath)
    parent = telemetry_filepath.parent
    name = telemetry_filepath.name
    if name.endswith(".json") and not name.endswith(".marks.json"):
        marks_name = name[:-5] + ".marks.json"
    else:
        marks_name = name + ".marks.json"
    return parent / marks_name


def clean_name_identifier(name: str) -> str:
    """Nettoie un nom de circuit ou de véhicule pour nom de fichier sûr."""
    if not name:
        return "unknown"
    return "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in name).strip("_").lower()


def find_marks_filepath_for_track(
    track_name: str,
    vehicle_class: str = "",
    vehicle_name: str = "",
    base_dir: Optional[Path] = None,
) -> Optional[Path]:
    """
    Résolution stricte et déterministe du fichier .marks.json pour un circuit donné.
    Garantit l'isolation absolue par circuit (aucune fuite d'un autre circuit).

    Ordre de priorité :
    1. ref_<track>_<car_class>.marks.json
    2. ref_<track>_<car_name>.marks.json
    3. ref_<track>_default.marks.json
    4. ref_<track>.marks.json
    5. Tout fichier ref_<track>_*.marks.json appartenant strictement à ce circuit.
    """
    if not track_name:
        return None
    t_clean = clean_name_identifier(track_name)
    if not t_clean or t_clean == "unknown":
        return None

    search_dir = Path(base_dir) if base_dir else DEFAULT_REF_LAPS_DIR
    if not search_dir.exists():
        return None

    # 1. Classe exacte
    if vehicle_class:
        v_class_clean = clean_name_identifier(vehicle_class)
        exact_class_path = search_dir / f"ref_{t_clean}_{v_class_clean}.marks.json"
        if exact_class_path.exists():
            return exact_class_path

    # 2. Nom de voiture exact
    if vehicle_name:
        v_name_clean = clean_name_identifier(vehicle_name)
        exact_veh_path = search_dir / f"ref_{t_clean}_{v_name_clean}.marks.json"
        if exact_veh_path.exists():
            return exact_veh_path

    # 3. Marqueurs par défaut du circuit
    track_default = search_dir / f"ref_{t_clean}_default.marks.json"
    if track_default.exists():
        return track_default

    track_generic = search_dir / f"ref_{t_clean}.marks.json"
    if track_generic.exists():
        return track_generic

    # 4. Premier fichier de marqueurs existant pour ce circuit
    candidates = sorted(list(search_dir.glob(f"ref_{t_clean}_*.marks.json")))
    if candidates:
        return candidates[0]

    return None


class AnnotationType(str, Enum):
    """Types d'annotations de repères de pilotage."""
    BRAKE = "brake"        # Marqueur frein (Touche 'B') -> Audio: "Brake"
    TURN_IN = "turn_in"    # Marqueur point de braquage (Touche 'I') -> Audio: "Turn"
    TURN = "turn"          # Marqueur de virage (Touche 'T') -> Numérotation auto T1..T30 -> Audio: "Turn 1"..
    GEAR = "gear"          # Marqueur de rapport de boîte (Touches '1'..'8') -> Audio: "Gear 1".. "Gear 8"


@dataclass
class TrackAnnotation:
    """Représente une annotation/repère sur le circuit."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    type: AnnotationType = AnnotationType.BRAKE
    distance: float = 0.0  # Distance le long de la piste en mètres
    gear: Optional[int] = None  # Numéro de rapport si type == GEAR (1 à 8)
    label: Optional[str] = None  # Label personnalisé optionnel
    color: Optional[List[int]] = None  # Couleur RGBA personnalisée optionnelle

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise l'annotation en dictionnaire JSON."""
        data: Dict[str, Any] = {
            "id": self.id,
            "type": self.type.value if isinstance(self.type, AnnotationType) else str(self.type),
            "distance": round(float(self.distance), 2),
        }
        if self.gear is not None:
            data["gear"] = int(self.gear)
        if self.label:
            data["label"] = str(self.label)
        if self.color:
            data["color"] = self.color
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrackAnnotation":
        """Désérialise une annotation depuis un dictionnaire JSON."""
        raw_type = data.get("type", AnnotationType.BRAKE.value)
        try:
            ann_type = AnnotationType(raw_type)
        except ValueError:
            ann_type = AnnotationType.BRAKE

        return cls(
            id=str(data.get("id", str(uuid.uuid4())[:8])),
            type=ann_type,
            distance=float(data.get("distance", 0.0)),
            gear=int(data["gear"]) if "gear" in data and data["gear"] is not None else None,
            label=data.get("label"),
            color=data.get("color"),
        )


@dataclass
class ReferenceLapProfile:
    """
    Profil spatial mètre par mètre d'un tour de référence.
    Contient la grille d'échantillonnage 1m (temps, vitesse, frein, accélérateur, volant)
    et la collection d'annotations de pilotage associées au circuit.
    """
    track_name: str = ""
    vehicle_name: str = ""
    vehicle_class: str = ""
    lap_time: float = 0.0
    track_length: float = 0.0
    spatial_step: float = 1.0
    num_points: int = 0
    t_grid: List[float] = field(default_factory=list)
    speed_grid: List[float] = field(default_factory=list)        # Vitesse en m/s
    throttle_grid: List[float] = field(default_factory=list)     # Accélérateur [0.0 - 1.0]
    brake_grid: List[float] = field(default_factory=list)        # Frein [0.0 - 1.0]
    steering_grid: List[float] = field(default_factory=list)     # Volant [-1.0 - 1.0]
    annotations: List[TrackAnnotation] = field(default_factory=list)
    _marks_filepath: Optional[Path] = None

    def get_turn_number(self, annotation_id: str) -> Optional[int]:
        """
        Calcule le numéro automatique du virage (1-indexed) pour une annotation de type TURN.
        La numérotation est recalculée dynamiquement selon l'ordre croissant de la distance sur le circuit.
        """
        turn_anns = [a for a in self.annotations if a.type == AnnotationType.TURN]
        turn_anns.sort(key=lambda a: a.distance)
        for idx, ann in enumerate(turn_anns, start=1):
            if ann.id == annotation_id:
                return idx
        return None

    def get_sorted_turns(self) -> List[Tuple[int, TrackAnnotation]]:
        """Retourne la liste des virages triés par distance avec leur numéro séquentiel (1, 2, 3...)."""
        turn_anns = [a for a in self.annotations if a.type == AnnotationType.TURN]
        turn_anns.sort(key=lambda a: a.distance)
        return [(idx, ann) for idx, ann in enumerate(turn_anns, start=1)]

    def get_annotation_display_label(self, annotation: TrackAnnotation) -> str:
        """Retourne le libellé d'affichage court et clair pour l'annotation."""
        if annotation.label:
            return annotation.label

        if annotation.type == AnnotationType.BRAKE:
            return "Brake"
        elif annotation.type == AnnotationType.TURN_IN:
            return "Turn-in"
        elif annotation.type == AnnotationType.TURN:
            turn_num = self.get_turn_number(annotation.id)
            return f"T{turn_num}" if turn_num is not None else "Turn"
        elif annotation.type == AnnotationType.GEAR:
            g = annotation.gear if annotation.gear is not None else 1
            return f"G{g}"
        return "Marker"

    def get_annotation_phrase_key(self, annotation: TrackAnnotation) -> str:
        """Retourne la clé audio (phrase_key) à prononcer pour le Race Engineer."""
        if annotation.type == AnnotationType.BRAKE:
            return "brake"
        elif annotation.type == AnnotationType.TURN_IN:
            return "turn"
        elif annotation.type == AnnotationType.TURN:
            turn_num = self.get_turn_number(annotation.id)
            num = turn_num if turn_num is not None else 1
            num_clamped = min(30, max(1, num))
            return f"turn_{num_clamped}"
        elif annotation.type == AnnotationType.GEAR:
            g = annotation.gear if annotation.gear is not None else 1
            g_clamped = min(8, max(1, g))
            return f"gear_{g_clamped}"
        return "lap"

    def set_marks_filepath(self, filepath: Optional[Path]) -> None:
        """Définit le chemin cible pour la persistance automatique des annotations."""
        self._marks_filepath = Path(filepath) if filepath else None

    def get_default_marks_filepath(self) -> Path:
        """Génère le chemin par défaut du fichier .marks.json pour ce circuit/véhicule."""
        if self._marks_filepath:
            return self._marks_filepath
        t_clean = clean_name_identifier(self.track_name or "track")
        v_clean = clean_name_identifier(self.vehicle_class or self.vehicle_name or "car")
        return DEFAULT_REF_LAPS_DIR / f"ref_{t_clean}_{v_clean}.marks.json"

    def add_annotation(
        self,
        ann_type: AnnotationType,
        distance: float,
        gear: Optional[int] = None,
        label: Optional[str] = None,
        color: Optional[List[int]] = None,
        auto_save: bool = True,
    ) -> TrackAnnotation:
        """Ajoute une annotation et la persiste automatiquement sur disque."""
        max_dist = self.track_length if self.track_length > 0 else 50000.0
        d_clamped = max(0.0, min(max_dist, distance))

        ann = TrackAnnotation(
            type=ann_type,
            distance=d_clamped,
            gear=gear,
            label=label,
            color=color,
        )
        self.annotations.append(ann)
        self.sort_annotations()

        if auto_save:
            self.save_marks_to_file()

        return ann

    def remove_annotation(self, annotation_id: str, auto_save: bool = True) -> bool:
        """Supprime une annotation par son ID et met à jour le fichier .marks.json."""
        orig_len = len(self.annotations)
        self.annotations = [a for a in self.annotations if a.id != annotation_id]
        if len(self.annotations) < orig_len:
            if auto_save:
                self.save_marks_to_file()
            return True
        return False

    def move_annotation(self, annotation_id: str, new_distance: float, auto_save: bool = True) -> bool:
        """Déplace une annotation et persiste automatiquement la nouvelle position."""
        max_dist = self.track_length if self.track_length > 0 else 50000.0
        d_clamped = max(0.0, min(max_dist, new_distance))
        for ann in self.annotations:
            if ann.id == annotation_id:
                ann.distance = d_clamped
                self.sort_annotations()
                if auto_save:
                    self.save_marks_to_file()
                return True
        return False

    def sort_annotations(self) -> None:
        """Trie la collection d'annotations par ordre de distance croissante."""
        self.annotations.sort(key=lambda a: a.distance)

    def get_value_at_dist(self, player_dist: float) -> Dict[str, float]:
        """
        Effectue une interpolation linéaire O(1) de toutes les grandeurs de télémétrie
        (temps, vitesse km/h, accélérateur, frein, angle volant) à une position donnée.
        """
        if self.num_points < 2 or not self.t_grid:
            return {
                "time_into": 0.0,
                "speed_ms": 0.0,
                "speed_kmh": 0.0,
                "throttle": 0.0,
                "brake": 0.0,
                "steering": 0.0,
            }

        step = self.spatial_step if self.spatial_step > 0 else 1.0
        idx_float = player_dist / step
        idx_floor = int(idx_float)

        if idx_floor < 0:
            idx1 = 0
            idx2 = 0
            frac = 0.0
        elif idx_floor >= self.num_points - 1:
            idx1 = self.num_points - 1
            idx2 = self.num_points - 1
            frac = 0.0
        else:
            idx1 = idx_floor
            idx2 = idx_floor + 1
            frac = idx_float - idx_floor

        def _interp(grid: List[float], default: float = 0.0) -> float:
            if not grid or idx1 >= len(grid):
                return default
            v1 = grid[idx1]
            v2 = grid[idx2] if idx2 < len(grid) else v1
            return v1 + frac * (v2 - v1)

        t_val = _interp(self.t_grid, 0.0)
        v_ms = _interp(self.speed_grid, 0.0)
        thr = _interp(self.throttle_grid, 0.0)
        brk = _interp(self.brake_grid, 0.0)
        steer = _interp(self.steering_grid, 0.0)

        return {
            "time_into": t_val,
            "speed_ms": v_ms,
            "speed_kmh": v_ms * 3.6,
            "throttle": thr,
            "brake": brk,
            "steering": steer,
        }

    # ── Sérialisation & Persistance Télémetrie (ref_*.json) ────────────────────
    def telemetry_to_dict(self) -> Dict[str, Any]:
        """Sérialise uniquement la télémétrie du tour de référence."""
        return {
            "track_name": self.track_name,
            "vehicle_name": self.vehicle_name,
            "vehicle_class": self.vehicle_class,
            "lap_time": float(self.lap_time),
            "track_length": float(self.track_length),
            "spatial_step": float(self.spatial_step),
            "num_points": int(self.num_points),
            "t_grid": [round(x, 4) for x in self.t_grid],
            "speed_grid": [round(x, 3) for x in self.speed_grid],
            "throttle_grid": [round(x, 3) for x in self.throttle_grid],
            "brake_grid": [round(x, 3) for x in self.brake_grid],
            "steering_grid": [round(x, 4) for x in self.steering_grid],
        }

    def save_telemetry_to_file(self, filepath: Path) -> bool:
        """Sauvegarde automatique de la télémétrie du tour de référence sur disque."""
        try:
            filepath = Path(filepath)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            data = self.telemetry_to_dict()
            filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")
            logger.info(f"[ReferenceLapProfile] Auto-saved telemetry to {filepath.name} ({self.lap_time:.3f}s)")
            return True
        except Exception as e:
            logger.error(f"[ReferenceLapProfile] Failed to save telemetry to {filepath}: {e}", exc_info=True)
            return False

    # ── Sérialisation & Persistance Annotations (ref_*.marks.json) ────────────
    def marks_to_dict(self) -> Dict[str, Any]:
        """Sérialise les annotations de piste avec métadonnées."""
        return {
            "track_name": self.track_name,
            "vehicle_class": self.vehicle_class,
            "annotations": [a.to_dict() for a in self.annotations],
        }

    def save_marks_to_file(self, filepath: Optional[Path] = None) -> bool:
        """Sauvegarde automatique au fur et à mesure des modifications dans le fichier .marks.json."""
        target_path = Path(filepath) if filepath else self.get_default_marks_filepath()
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            data = self.marks_to_dict()
            target_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            self._marks_filepath = target_path
            logger.info(f"[ReferenceLapProfile] Auto-saved marks to {target_path.name} ({len(self.annotations)} annotations)")
            return True
        except Exception as e:
            logger.error(f"[ReferenceLapProfile] Failed to auto-save marks to {target_path}: {e}", exc_info=True)
            return False

    def load_marks_from_file(self, filepath: Path) -> bool:
        """Charge les annotations depuis un fichier .marks.json dédié."""
        try:
            filepath = Path(filepath)
            if not filepath.exists():
                return False
            content = filepath.read_text(encoding="utf-8")
            data = json.loads(content)
            raw_anns = data.get("annotations", [])
            self.annotations = [TrackAnnotation.from_dict(a) for a in raw_anns if isinstance(a, dict)]
            self.sort_annotations()
            self._marks_filepath = filepath
            logger.info(f"[ReferenceLapProfile] Loaded {len(self.annotations)} marks from {filepath.name}")
            return True
        except Exception as e:
            logger.error(f"[ReferenceLapProfile] Failed to load marks from {filepath}: {e}", exc_info=True)
            return False

    # ── Chargement Combiné (Télémétrie + Marks) ──────────────────────────────
    @classmethod
    def load_from_file(cls, filepath: Path) -> Optional["ReferenceLapProfile"]:
        """
        Charge un profil de référence depuis le fichier télémétrie '.json'
        et charge automatiquement les annotations depuis le fichier '.marks.json' associé.
        """
        try:
            filepath = Path(filepath)
            if not filepath.exists():
                return None
            content = filepath.read_text(encoding="utf-8")
            data = json.loads(content)

            t_grid = [float(x) for x in data.get("t_grid", [])]
            num_pts = len(t_grid) if t_grid else int(data.get("num_points", 0))

            speed_grid = [float(x) for x in data.get("speed_grid", [])]
            throttle_grid = [float(x) for x in data.get("throttle_grid", [])]
            brake_grid = [float(x) for x in data.get("brake_grid", [])]
            steering_grid = [float(x) for x in data.get("steering_grid", [])]

            profile = cls(
                track_name=str(data.get("track_name", "")),
                vehicle_name=str(data.get("vehicle_name", "")),
                vehicle_class=str(data.get("vehicle_class", "")),
                lap_time=float(data.get("lap_time", 0.0)),
                track_length=float(data.get("track_length", 0.0)),
                spatial_step=float(data.get("spatial_step", 1.0)),
                num_points=num_pts,
                t_grid=t_grid,
                speed_grid=speed_grid,
                throttle_grid=throttle_grid,
                brake_grid=brake_grid,
                steering_grid=steering_grid,
                annotations=[],
            )

            # Charger les marks associés si existants
            marks_path = get_marks_filepath(filepath)
            profile.set_marks_filepath(marks_path)
            if marks_path.exists():
                profile.load_marks_from_file(marks_path)

            logger.info(f"[ReferenceLapProfile] Loaded profile from {filepath.name} ({profile.lap_time:.3f}s, {len(profile.annotations)} marks)")
            return profile
        except Exception as e:
            logger.error(f"[ReferenceLapProfile] Failed to load profile from {filepath}: {e}", exc_info=True)
            return None

    def save_to_file(self, filepath: Path) -> bool:
        """Sauvegarde la télémétrie dans filepath et les annotations dans get_marks_filepath(filepath)."""
        ok_telem = self.save_telemetry_to_file(filepath)
        marks_path = get_marks_filepath(filepath)
        ok_marks = self.save_marks_to_file(marks_path)
        return ok_telem and ok_marks
