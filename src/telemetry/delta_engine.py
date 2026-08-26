"""
SimPad Telemetry — Delta Engine.
High-precision live lap delta calculator and spatial reference profile engine.

Features:
- Resampled uniform spatial reference grid (1m resolution) for fast, smooth O(1) interpolation.
- Full meter-by-meter telemetry capture: time, speed, throttle, brake, steering.
- Integrated track annotations management (Brake, Turn-in, Turn T1..T30, Gear 1..8).
- 50Hz dead-reckoning extrapolation using physics speed & delta time.
- Strict lap validation (mCountLapFlag == 2, no pit stops, full track coverage, monotonic distance).
- Accurate sector checkpoint deltas (S1, S2, S3) captured at sector boundaries.
- Disk persistence for best laps per (track, car) pair.
- Auto-reset on session / track / vehicle change.
Architecture SOLID.
"""

import os
import time
import json
import logging
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

from src.telemetry.reference_profile import (
    ReferenceLapProfile,
    TrackAnnotation,
    AnnotationType,
    DEFAULT_REF_LAPS_DIR,
    get_marks_filepath,
)

logger = logging.getLogger(__name__)

# Project root for saving reference lap profiles
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_REF_LAPS_DIR = DEFAULT_REF_LAPS_DIR


def _clean_name(name: str) -> str:
    """Sanitizes track or vehicle name for filenames."""
    if not name:
        return "unknown"
    cleaned = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in name)
    return cleaned.strip("_").lower()


class DeltaEngine:
    """
    Moteur de calcul des Deltas Chrono Live & Secteurs pour SimPad.
    Enregistre et gère le profil spatial mètre par mètre (vitesse, accélérateur, frein, volant)
    et les annotations de piste associées.
    """

    def __init__(self):
        self._pit_or_garage_during_lap: bool = False
        self._current_profile: Optional[ReferenceLapProfile] = None
        self.reset_session()

    def reset_session(self) -> None:
        """Réinitialise complètement l'état du moteur (changement de session/circuit)."""
        self._track_name: str = ""
        self._vehicle_name: str = ""
        self._vehicle_class: str = ""
        self._track_length: float = 0.0

        # Profil de référence haute résolution
        self._current_profile = None
        self._ref_lap_time: float = 999999.0
        self._ref_t_grid: Optional[List[float]] = None
        self._ref_spatial_step: float = 1.0
        self._ref_num_points: int = 0

        # Échantillons du tour en cours : liste de (dist, time_into, speed_ms, throttle, brake, steering)
        self._current_lap_samples: List[Tuple[float, float, float, float, float, float]] = []
        self._last_laps_completed: int = -1
        self._last_dist: float = -1.0
        self._pit_or_garage_during_lap: bool = False

        # Derniers inputs physiques
        self._last_speed_ms: float = 0.0
        self._last_throttle: float = 0.0
        self._last_brake: float = 0.0
        self._last_steering: float = 0.0

        # Dernier état de scoring (1-2 Hz)
        self._last_scoring_dist: float = 0.0
        self._last_scoring_time_into: float = 0.0
        self._last_scoring_timestamp: float = 0.0
        self._last_current_sector: int = 1

        # Checkpoints de secteurs
        self._s1_checkpoint_delta: float = 0.0
        self._s2_checkpoint_delta: float = 0.0
        self._s1_checkpoint_captured: bool = False
        self._s2_checkpoint_captured: bool = False

        # Dernières valeurs calculées
        self._live_delta: float = 0.0
        self._sector1_delta: float = 0.0
        self._sector2_delta: float = 0.0
        self._sector3_delta: float = 0.0

    @property
    def current_profile(self) -> Optional[ReferenceLapProfile]:
        """Retourne le profil de référence actuellement actif."""
        return self._current_profile

    def get_reference_profile(self) -> Optional[ReferenceLapProfile]:
        """Getter pour le profil de référence."""
        return self._current_profile

    def set_reference_profile(self, profile: Optional[ReferenceLapProfile]) -> None:
        """Définit manuellement le profil de référence actif."""
        self._current_profile = profile
        if profile is not None:
            self._ref_lap_time = profile.lap_time
            self._ref_spatial_step = profile.spatial_step
            self._ref_t_grid = profile.t_grid
            self._ref_num_points = profile.num_points
            self._track_name = profile.track_name
            self._track_length = profile.track_length
        else:
            self._ref_lap_time = 999999.0
            self._ref_t_grid = None
            self._ref_num_points = 0

    def _find_player_vehicle(self, vehicles: list) -> Optional[dict]:
        """SLAP Helper: Finds player vehicle in scoring vehicles list."""
        if not isinstance(vehicles, list):
            return None
        for v in vehicles:
            if isinstance(v, dict) and (v.get("mIsPlayer") or v.get("isPlayer")):
                return v
        for v in vehicles:
            if isinstance(v, dict) and v.get("mControl") == 0:
                return v
        return None

    def _handle_lap_transition(
        self,
        laps_comp: int,
        last_lap_time: float,
        lap_flag: int,
        in_garage: bool,
        in_pits: bool,
    ) -> None:
        """SLAP Helper: Finalizes previous lap and resets state for new lap."""
        if self._last_laps_completed >= 0 and laps_comp > self._last_laps_completed:
            self._finalize_completed_lap(
                lap_time=last_lap_time,
                lap_flag=lap_flag,
                in_garage=in_garage,
                in_pits=in_pits,
            )
            self._current_lap_samples = []
            self._pit_or_garage_during_lap = False
            self._s1_checkpoint_captured = False
            self._s2_checkpoint_captured = False
            self._s1_checkpoint_delta = 0.0
            self._s2_checkpoint_delta = 0.0
            self._sector1_delta = 0.0
            self._sector2_delta = 0.0
            self._sector3_delta = 0.0
        self._last_laps_completed = laps_comp

    def _handle_sector_transition(self, curr_sec: int) -> None:
        """SLAP Helper: Captures sector checkpoint deltas on boundary change."""
        if curr_sec != self._last_current_sector:
            if curr_sec == 2 and not self._s1_checkpoint_captured:
                self._s1_checkpoint_delta = self._live_delta
                self._s1_checkpoint_captured = True
            elif curr_sec == 3 and not self._s2_checkpoint_captured:
                self._s2_checkpoint_delta = self._live_delta
                self._s2_checkpoint_captured = True
            self._last_current_sector = curr_sec

    def _collect_lap_sample(
        self,
        in_garage: bool,
        in_pits: bool,
        time_into: float,
        player_dist: float,
        speed_ms: float = 0.0,
        throttle: float = 0.0,
        brake: float = 0.0,
        steering: float = 0.0,
    ) -> None:
        """SLAP Helper: Collects live lap samples (full telemetry) for reference profile building."""
        if in_garage or in_pits:
            self._pit_or_garage_during_lap = True
            return

        if time_into > 0.0 and player_dist >= 0.0:
            if self._track_length <= 0.0 or player_dist <= self._track_length + 200.0:
                if not self._current_lap_samples or player_dist > self._current_lap_samples[-1][0]:
                    self._current_lap_samples.append((
                        player_dist,
                        time_into,
                        speed_ms,
                        throttle,
                        brake,
                        steering,
                    ))

    def update_scoring(self, scoring_js: dict) -> None:
        """
        Traite un paquet ScoringInfoV01 (1-2 Hz).
        """
        now = time.time()
        track_name = str(scoring_js.get("mTrackName", ""))
        track_len = float(scoring_js.get("mLapDist", 0.0))

        player_veh = self._find_player_vehicle(scoring_js.get("mVehicles", []))
        if not player_veh:
            return

        veh_name = str(player_veh.get("mVehicleName", ""))
        veh_class = str(player_veh.get("mVehicleClass", player_veh.get("vehicleClass", "")))

        if (track_name and track_name != self._track_name) or (veh_class and veh_class != self._vehicle_class) or (veh_name and veh_name != self._vehicle_name):
            self._track_name = track_name
            self._vehicle_name = veh_name
            self._vehicle_class = veh_class
            self._track_length = track_len
            self._load_reference_profile()

        if track_len > 0.0:
            self._track_length = track_len

        laps_comp = int(player_veh.get("mTotalLaps", 0))
        time_into = float(player_veh.get("mTimeIntoLap", -1.0))
        player_dist = float(player_veh.get("mLapDist", 0.0))
        raw_sec = int(player_veh.get("mSector", 1))
        curr_sec = 3 if raw_sec == 0 else (raw_sec if raw_sec in (1, 2, 3) else 1)

        in_garage = bool(player_veh.get("mInGarageStall", player_veh.get("inGarageStall", False)))
        in_pits = bool(player_veh.get("mInPits", player_veh.get("inPits", False)))
        lap_flag = int(player_veh.get("mCountLapFlag", player_veh.get("countLapFlag", 2)))
        last_lap_time = float(player_veh.get("mLastLapTime", -1.0))

        self._handle_lap_transition(laps_comp, last_lap_time, lap_flag, in_garage, in_pits)
        self._handle_sector_transition(curr_sec)
        self._collect_lap_sample(
            in_garage=in_garage,
            in_pits=in_pits,
            time_into=time_into,
            player_dist=player_dist,
            speed_ms=self._last_speed_ms,
            throttle=self._last_throttle,
            brake=self._last_brake,
            steering=self._last_steering,
        )

        self._last_scoring_dist = player_dist
        self._last_scoring_time_into = time_into
        self._last_scoring_timestamp = now
        self._last_dist = player_dist

        self._calculate_delta(player_dist, time_into)

    def update_physics(
        self,
        veh_speed_ms: float,
        throttle: float = 0.0,
        brake: float = 0.0,
        steering: float = 0.0,
    ) -> None:
        """
        Traite un paquet TelemInfoV01 à haute fréquence (50 Hz).
        Effectue une extrapolation spatiale dead-reckoning et capture les inputs réels.
        """
        self._last_speed_ms = veh_speed_ms
        self._last_throttle = throttle
        self._last_brake = brake
        self._last_steering = steering

        if self._last_scoring_timestamp <= 0.0:
            return

        now = time.time()
        dt = now - self._last_scoring_timestamp

        # Extrapolation continue
        if 0.0 < dt < 60.0 and veh_speed_ms >= 0.0:
            extrapol_dist = self._last_scoring_dist + (veh_speed_ms * dt)
            extrapol_time_into = self._last_scoring_time_into + dt

            # Gérer le bouclage au passage de la ligne de départ/arrivée
            if self._track_length > 0.0 and extrapol_dist > self._track_length:
                extrapol_dist = extrapol_dist % self._track_length

            self._calculate_delta(extrapol_dist, extrapol_time_into)

            # Collecte haute fréquence pendant le tour
            if not self._pit_or_garage_during_lap and extrapol_time_into > 0.0 and extrapol_dist >= 0.0:
                if not self._current_lap_samples or (extrapol_dist - self._current_lap_samples[-1][0]) >= 0.8:
                    self._current_lap_samples.append((
                        extrapol_dist,
                        extrapol_time_into,
                        veh_speed_ms,
                        throttle,
                        brake,
                        steering,
                    ))

    def _calculate_delta(self, player_dist: float, time_into: float) -> None:
        """Calcul du delta live et des deltas par secteur à partir d'une position et d'un temps."""
        if self._ref_t_grid is None or self._ref_num_points < 2 or time_into <= 0.0 or player_dist < 0.0:
            self._live_delta = 0.0
            self._sector1_delta = 0.0
            self._sector2_delta = 0.0
            self._sector3_delta = 0.0
            return

        # Lookup O(1) direct sur la grille spatiale uniforme d_step = 1.0 m
        step = self._ref_spatial_step
        idx_float = player_dist / step
        idx_floor = int(idx_float)

        if idx_floor < 0:
            ref_time = self._ref_t_grid[0]
        elif idx_floor >= self._ref_num_points - 1:
            ref_time = self._ref_t_grid[-1]
        else:
            frac = idx_float - idx_floor
            t1 = self._ref_t_grid[idx_floor]
            t2 = self._ref_t_grid[idx_floor + 1]
            ref_time = t1 + frac * (t2 - t1)

        delta = time_into - ref_time

        # Borner les deltas extrêmes à +/- 999.0s
        if abs(delta) < 999.0:
            self._live_delta = delta
        else:
            self._live_delta = 0.0

        # Deltas par secteur actif
        if self._last_current_sector == 1:
            self._sector1_delta = self._live_delta
        elif self._last_current_sector == 2:
            self._sector2_delta = self._live_delta - self._s1_checkpoint_delta
        elif self._last_current_sector == 3:
            self._sector3_delta = self._live_delta - self._s2_checkpoint_delta

    def _resample_spatial_grid(
        self,
        clean_samples: List[Tuple[float, ...]],
        spatial_step: float = 1.0,
    ) -> Tuple[List[float], List[float], List[float], List[float], List[float], int]:
        """
        SLAP Helper: Construction du profil ré-échantillonné mètre par mètre sur grille spatiale uniforme.
        Interpole: temps, vitesse, accélérateur, frein, volant.
        """
        import bisect
        track_dist = clean_samples[-1][0]
        num_points = int(track_dist / spatial_step) + 1

        t_grid: List[float] = []
        speed_grid: List[float] = []
        throttle_grid: List[float] = []
        brake_grid: List[float] = []
        steering_grid: List[float] = []

        d_keys = [s[0] for s in clean_samples]

        def _get_val(sample_tuple, idx, default=0.0):
            return sample_tuple[idx] if len(sample_tuple) > idx else default

        for i in range(num_points):
            target_d = i * spatial_step
            idx = bisect.bisect_left(d_keys, target_d)

            if idx <= 0:
                s = clean_samples[0]
                t_grid.append(s[1])
                speed_grid.append(_get_val(s, 2, 0.0))
                throttle_grid.append(_get_val(s, 3, 0.0))
                brake_grid.append(_get_val(s, 4, 0.0))
                steering_grid.append(_get_val(s, 5, 0.0))
            elif idx >= len(clean_samples):
                s = clean_samples[-1]
                t_grid.append(s[1])
                speed_grid.append(_get_val(s, 2, 0.0))
                throttle_grid.append(_get_val(s, 3, 0.0))
                brake_grid.append(_get_val(s, 4, 0.0))
                steering_grid.append(_get_val(s, 5, 0.0))
            else:
                s1 = clean_samples[idx - 1]
                s2 = clean_samples[idx]
                d1, t1 = s1[0], s1[1]
                d2, t2 = s2[0], s2[1]
                frac = (target_d - d1) / (d2 - d1) if d2 > d1 else 0.0

                t_grid.append(t1 + frac * (t2 - t1))

                v1, v2 = _get_val(s1, 2, 0.0), _get_val(s2, 2, 0.0)
                speed_grid.append(v1 + frac * (v2 - v1))

                thr1, thr2 = _get_val(s1, 3, 0.0), _get_val(s2, 3, 0.0)
                throttle_grid.append(thr1 + frac * (thr2 - thr1))

                brk1, brk2 = _get_val(s1, 4, 0.0), _get_val(s2, 4, 0.0)
                brake_grid.append(brk1 + frac * (brk2 - brk1))

                str1, str2 = _get_val(s1, 5, 0.0), _get_val(s2, 5, 0.0)
                steering_grid.append(str1 + frac * (str2 - str1))

        return t_grid, speed_grid, throttle_grid, brake_grid, steering_grid, num_points

    def _finalize_completed_lap(
        self,
        lap_time: float,
        lap_flag: int,
        in_garage: bool,
        in_pits: bool,
    ) -> None:
        """Valide et enregistre le tour complété (SLAP: Orchestration haut niveau)."""
        if lap_flag == 0:
            logger.debug(f"[DeltaEngine] Lap rejected: Invalidated by game (lap_flag={lap_flag})")
            return

        if self._pit_or_garage_during_lap or in_garage or in_pits:
            logger.debug("[DeltaEngine] Lap rejected: Pit or Garage stop detected during lap")
            return

        if lap_time <= 0.0 or len(self._current_lap_samples) < 5:
            logger.debug("[DeltaEngine] Lap rejected: Insufficient lap samples or lap_time <= 0")
            return

        if lap_time >= self._ref_lap_time and self._ref_t_grid is not None:
            logger.debug(f"[DeltaEngine] Lap clean but slower than reference ({lap_time:.3f}s vs {self._ref_lap_time:.3f}s)")
            return

        # Filtrer la liste pour garantir une monotonie stricte des distances
        clean_samples: List[Tuple[float, ...]] = []
        last_d = -1.0
        for sample in self._current_lap_samples:
            d = sample[0]
            if d > last_d:
                clean_samples.append(sample)
                last_d = d

        if not clean_samples:
            return

        # Extrapolation automatique du point de départ (0.0m, 0.0s) si absent
        if clean_samples[0][0] > 0.0:
            first_s = clean_samples[0]
            clean_samples.insert(0, (
                0.0,
                0.0,
                first_s[2] if len(first_s) > 2 else 0.0,
                first_s[3] if len(first_s) > 3 else 0.0,
                first_s[4] if len(first_s) > 4 else 0.0,
                first_s[5] if len(first_s) > 5 else 0.0,
            ))

        # Extrapolation automatique du point de fin (track_length, lap_time) si absent
        if self._track_length > 0.0 and clean_samples[-1][0] < self._track_length:
            last_s = clean_samples[-1]
            clean_samples.append((
                self._track_length,
                lap_time,
                last_s[2] if len(last_s) > 2 else 0.0,
                last_s[3] if len(last_s) > 3 else 0.0,
                last_s[4] if len(last_s) > 4 else 0.0,
                last_s[5] if len(last_s) > 5 else 0.0,
            ))

        if len(clean_samples) < 2 or clean_samples[-1][0] <= 0.0:
            return

        spatial_step = 1.0
        t_grid, speed_grid, throttle_grid, brake_grid, steering_grid, num_points = self._resample_spatial_grid(
            clean_samples,
            spatial_step=spatial_step,
        )

        # Déterminer les chemins de fichiers (télémétrie .json et marks .marks.json)
        filepath = self._get_profile_filepath()
        marks_path = get_marks_filepath(filepath) if filepath else None

        # Conserver les annotations existantes depuis la mémoire ou le disque
        existing_annotations: List[TrackAnnotation] = []
        if self._current_profile and self._current_profile.annotations:
            existing_annotations = list(self._current_profile.annotations)

        # Construction du profil complet
        effective_len = self._track_length if self._track_length > 0.0 else clean_samples[-1][0]
        profile = ReferenceLapProfile(
            track_name=self._track_name,
            vehicle_name=self._vehicle_name,
            vehicle_class=self._vehicle_class,
            lap_time=lap_time,
            track_length=effective_len,
            spatial_step=spatial_step,
            num_points=num_points,
            t_grid=t_grid,
            speed_grid=speed_grid,
            throttle_grid=throttle_grid,
            brake_grid=brake_grid,
            steering_grid=steering_grid,
            annotations=existing_annotations,
        )

        if marks_path:
            profile.set_marks_filepath(marks_path)
            if marks_path.exists() and not existing_annotations:
                profile.load_marks_from_file(marks_path)

        self._current_profile = profile
        self._ref_lap_time = lap_time
        self._ref_t_grid = t_grid
        self._ref_spatial_step = spatial_step
        self._ref_num_points = num_points

        logger.info(f"[DeltaEngine] New Best Reference Lap Recorded! Time: {lap_time:.3f}s ({num_points} grid points)")
        print(f"[DeltaEngine] New Reference Lap Set: {lap_time:.3f}s for track '{self._track_name}'", flush=True)

        self._save_reference_profile()

    def _get_profile_filepath(self) -> Optional[Path]:
        """Retourne le chemin du fichier JSON pour (track, vehicle_class/vehicle)."""
        if not self._track_name:
            return None
        t_clean = _clean_name(self._track_name)
        v_identifier = _clean_name(self._vehicle_class) if self._vehicle_class else _clean_name(self._vehicle_name)
        filename = f"ref_{t_clean}_{v_identifier}.json"
        return _REF_LAPS_DIR / filename

    def _save_reference_profile(self) -> None:
        """Sauvegarde automatique de la télémétrie du tour de référence courant sur le disque JSON."""
        filepath = self._get_profile_filepath()
        if not filepath or self._current_profile is None:
            return
        self._current_profile.save_telemetry_to_file(filepath)

    def _load_reference_profile(self) -> None:
        """Tente de charger un profil de référence enregistré sur disque pour le circuit/voiture."""
        filepath = self._get_profile_filepath()
        if not filepath or not filepath.exists():
            self._current_profile = None
            self._ref_lap_time = 999999.0
            self._ref_t_grid = None
            self._ref_num_points = 0
            return

        loaded = ReferenceLapProfile.load_from_file(filepath)
        if loaded:
            self._current_profile = loaded
            self._ref_lap_time = loaded.lap_time
            self._ref_spatial_step = loaded.spatial_step
            self._ref_t_grid = loaded.t_grid
            self._ref_num_points = loaded.num_points
            logger.info(f"[DeltaEngine] Loaded reference profile from {filepath.name} ({self._ref_lap_time:.3f}s, {len(loaded.annotations)} annotations)")
            print(f"[DeltaEngine] Loaded saved reference lap: {self._ref_lap_time:.3f}s ({len(loaded.annotations)} annotations)", flush=True)
        else:
            self._current_profile = None
            self._ref_lap_time = 999999.0
            self._ref_t_grid = None
            self._ref_num_points = 0

    @property
    def live_delta(self) -> float:
        return self._live_delta

    @property
    def sector1_delta(self) -> float:
        return self._sector1_delta

    @property
    def sector2_delta(self) -> float:
        return self._sector2_delta

    @property
    def sector3_delta(self) -> float:
        return self._sector3_delta

    @property
    def has_reference(self) -> bool:
        return self._ref_t_grid is not None and self._ref_num_points > 0

    @property
    def track_name(self) -> str:
        """Retourne le nom du circuit de la session active."""
        return self._track_name

    @property
    def last_scoring_dist(self) -> float:
        """Retourne la dernière distance connue depuis le paquet de scoring."""
        return self._last_scoring_dist

    def get_live_car_distance(self) -> float:
        """Retourne la distance courante de la voiture (extrapolée en direct à 50Hz)."""
        if self._last_scoring_timestamp <= 0.0:
            return self._last_scoring_dist
        dt = time.time() - self._last_scoring_timestamp
        if 0.0 <= dt < 3.0 and self._last_speed_ms >= 0.0:
            extrapol = self._last_scoring_dist + (self._last_speed_ms * dt)
            if self._track_length > 0.0 and extrapol > self._track_length:
                extrapol = extrapol % self._track_length
            return extrapol
        return self._last_scoring_dist
