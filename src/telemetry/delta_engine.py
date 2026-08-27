"""
SimPad Telemetry — Delta Engine.
High-precision live lap delta calculator and spatial reference profile engine.

Features:
- Resampled uniform spatial reference grid (1m resolution) for fast, smooth O(1) interpolation.
- Full meter-by-meter telemetry capture: time, speed, throttle, brake, steering.
- Integrated track annotations management (Brake, Turn-in, Turn T1..T30, Gear 1..8).
- 50Hz continuous incremental trapezoidal dead-reckoning integration (no braking/acceleration jitter).
- Multi-Reference Profile Hierarchy: All-Time Best (disk), Session Best, Stint Best, and Last Lap.
- Finish-line Delta Freeze (configurable duration, default 3.5s) for clear HUD driver feedback.
- Live Estimated Lap Time projection (ref_lap_time + live_delta) formatted as M:SS.mmm.
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
from enum import Enum
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

from src.telemetry.reference_profile import (
    ReferenceLapProfile,
    TrackAnnotation,
    AnnotationType,
    DEFAULT_REF_LAPS_DIR,
    get_marks_filepath,
    find_marks_filepath_for_track,
    find_telemetry_filepath_for_track,
    clean_name_identifier,
)

logger = logging.getLogger(__name__)

# Project root for saving reference lap profiles
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_REF_LAPS_DIR = DEFAULT_REF_LAPS_DIR


class DeltaReferenceMode(str, Enum):
    """Modes de référence chrono pour le calcul des deltas."""
    ALL_TIME_BEST = "all_time_best"  # Meilleur tour absolu enregistré sur disque
    SESSION_BEST = "session_best"    # Meilleur tour de la session active
    STINT_BEST = "stint_best"        # Meilleur tour du relais en cours (remis à zéro au pit-stop)
    LAST_LAP = "last_lap"            # Tour immédiatement précédent


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
        self._current_profile: Optional[ReferenceLapProfile] = None
        self._freeze_duration: float = 3.5  # Durée de gel du delta à la ligne d'arrivée (secondes)
        self._ema_samples: int = 0  # 0 = direct/non filtré, > 1 = lissage EMA
        self.reset_session()

    def reset_session(self) -> None:
        """Réinitialise complètement l'état du moteur (changement de session/circuit)."""
        self._track_name: str = ""
        self._vehicle_name: str = ""
        self._vehicle_class: str = ""
        self._track_length: float = 0.0

        # Mode de référence actif
        self._ref_mode: DeltaReferenceMode = DeltaReferenceMode.ALL_TIME_BEST

        # Multi-profils de référence
        self._current_profile: Optional[ReferenceLapProfile] = None
        self._all_time_best_profile: Optional[ReferenceLapProfile] = None
        self._session_best_profile: Optional[ReferenceLapProfile] = None
        self._stint_best_profile: Optional[ReferenceLapProfile] = None
        self._last_lap_profile: Optional[ReferenceLapProfile] = None

        self._ref_lap_time: float = 999999.0
        self._all_time_best_lap_time: float = 999999.0
        self._session_best_lap_time: float = 999999.0
        self._stint_best_lap_time: float = 999999.0
        self._last_lap_time: float = 999999.0

        self._ref_t_grid: Optional[List[float]] = None
        self._ref_spatial_step: float = 1.0
        self._ref_num_points: int = 0

        # Échantillons du tour en cours : liste de (dist, time_into, speed_ms, throttle, brake, steering)
        self._current_lap_samples: List[Tuple[float, float, float, float, float, float]] = []
        self._last_laps_completed: int = -1
        self._last_dist: float = -1.0
        self._last_lap_flag: int = 2

        # Derniers inputs physiques
        self._last_speed_ms: float = 0.0
        self._last_throttle: float = 0.0
        self._last_brake: float = 0.0
        self._last_steering: float = 0.0

        # Estimateur de position et temps continu (Intégration trapézoïdale 50Hz)
        self._est_dist: float = 0.0
        self._est_time_into: float = 0.0
        self._last_physics_timestamp: float = 0.0
        self._last_physics_elapsed: float = 0.0

        # Dernier état de scoring (1-2 Hz)
        self._last_scoring_dist: float = 0.0
        self._last_scoring_time_into: float = 0.0
        self._last_scoring_timestamp: float = 0.0
        self._last_current_sector: int = 1

        # Checkpoints spatiaux et secteurs
        self._s1_checkpoint_delta: float = 0.0
        self._s2_checkpoint_delta: float = 0.0
        self._s1_checkpoint_captured: bool = False
        self._s2_checkpoint_captured: bool = False
        self._last_checkpoint_idx: int = -1

        # Gel du Delta au passage de ligne
        self._frozen_final_delta: float = 0.0
        self._freeze_delta_until: float = 0.0

        # Lissage EMA
        self._ema_live_delta: float = 0.0

        # Dernières valeurs calculées
        self._live_delta: float = 0.0
        self._sector1_delta: float = 0.0
        self._sector2_delta: float = 0.0
        self._sector3_delta: float = 0.0

    @property
    def reference_mode(self) -> DeltaReferenceMode:
        """Retourne le mode de référence actif."""
        return self._ref_mode

    @reference_mode.setter
    def reference_mode(self, mode: DeltaReferenceMode) -> None:
        """Modifie le mode de référence et applique le profil correspondant."""
        if isinstance(mode, str):
            try:
                mode = DeltaReferenceMode(mode)
            except ValueError:
                mode = DeltaReferenceMode.ALL_TIME_BEST
        self._ref_mode = mode
        self._apply_active_profile()

    @property
    def freeze_duration(self) -> float:
        """Durée de gel du delta à la ligne d'arrivée en secondes."""
        return self._freeze_duration

    @freeze_duration.setter
    def freeze_duration(self, val: float) -> None:
        self._freeze_duration = max(0.0, float(val))

    @property
    def ema_samples(self) -> int:
        """Nombre d'échantillons pour le filtre EMA (0 = désactivé)."""
        return self._ema_samples

    @ema_samples.setter
    def ema_samples(self, samples: int) -> None:
        self._ema_samples = max(0, int(samples))

    @property
    def current_profile(self) -> Optional[ReferenceLapProfile]:
        """Retourne le profil de référence actuellement actif."""
        return self._current_profile

    @property
    def all_time_best_profile(self) -> Optional[ReferenceLapProfile]:
        return self._all_time_best_profile

    @property
    def session_best_profile(self) -> Optional[ReferenceLapProfile]:
        return self._session_best_profile

    @property
    def stint_best_profile(self) -> Optional[ReferenceLapProfile]:
        return self._stint_best_profile

    @property
    def last_lap_profile(self) -> Optional[ReferenceLapProfile]:
        return self._last_lap_profile

    def get_reference_profile(self) -> Optional[ReferenceLapProfile]:
        """Getter pour le profil de référence."""
        return self._current_profile

    def set_reference_profile(self, profile: Optional[ReferenceLapProfile]) -> None:
        """Définit manuellement le profil de référence actif."""
        self._all_time_best_profile = profile
        if profile is not None:
            self._all_time_best_lap_time = profile.lap_time
        else:
            self._all_time_best_lap_time = 999999.0
        self._apply_active_profile()

    def _apply_active_profile(self) -> None:
        """Applique le profil de référence selon le mode sélectionné (strictement sans repli non désiré)."""
        target_prof = None

        if self._ref_mode == DeltaReferenceMode.LAST_LAP:
            target_prof = self._last_lap_profile
        elif self._ref_mode == DeltaReferenceMode.STINT_BEST:
            target_prof = self._stint_best_profile
        elif self._ref_mode == DeltaReferenceMode.SESSION_BEST:
            target_prof = self._session_best_profile
        elif self._ref_mode == DeltaReferenceMode.ALL_TIME_BEST:
            target_prof = self._all_time_best_profile

        self._current_profile = target_prof
        if target_prof is not None and target_prof.t_grid and len(target_prof.t_grid) > 1:
            self._ref_lap_time = target_prof.lap_time
            self._ref_spatial_step = target_prof.spatial_step
            self._ref_t_grid = target_prof.t_grid
            self._ref_num_points = target_prof.num_points
            self._track_name = target_prof.track_name
            self._track_length = target_prof.track_length
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
        # Initialisation au premier paquet reçu
        if self._last_laps_completed < 0:
            self._last_laps_completed = laps_comp
            self._current_lap_samples = []
            self._pit_or_garage_during_lap = False
            return

        # Cas 1 : Réinitialisation de session / Relance (mTotalLaps repasse à 0 ou diminue)
        if laps_comp < self._last_laps_completed:
            logger.info(f"[DeltaEngine] Session reset detected: laps completed went from {self._last_laps_completed} to {laps_comp}")
            print(f"[DeltaEngine] Session réinitialisée : compteur de tours remis à {laps_comp}", flush=True)
            self._current_lap_samples = []
            self._pit_or_garage_during_lap = False
            self._s1_checkpoint_captured = False
            self._s2_checkpoint_captured = False
            self._s1_checkpoint_delta = 0.0
            self._s2_checkpoint_delta = 0.0
            self._sector1_delta = 0.0
            self._sector2_delta = 0.0
            self._sector3_delta = 0.0
            self._est_dist = 0.0
            self._est_time_into = 0.0
            self._last_laps_completed = laps_comp
            return

        # Cas 2 : Franchissement de la ligne de départ/arrivée (nouveau tour complété)
        if laps_comp > self._last_laps_completed:
            # Capture et gel du delta final avant réinitialisation
            self._frozen_final_delta = self._live_delta
            if self._freeze_duration > 0.0:
                self._freeze_delta_until = time.time() + self._freeze_duration

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
        time_into: float,
        player_dist: float,
        speed_ms: float = 0.0,
        throttle: float = 0.0,
        brake: float = 0.0,
        steering: float = 0.0,
    ) -> None:
        """SLAP Helper: Collects live lap samples (full telemetry) for reference profile building."""
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
        Gère les changements de tours, réinitialisations de sessions et transitions de secteurs.
        """
        now = time.time()
        scoring_info = scoring_js.get("mScoringInfo", scoring_js)
        track_name = str(scoring_info.get("mTrackName", scoring_info.get("trackName", ""))).strip()
        track_len = float(scoring_info.get("mLapDist", scoring_info.get("lapDist", 0.0)))

        vehicles = scoring_info.get("mVehicles", scoring_info.get("vehicles", []))
        player_veh = self._find_player_vehicle(vehicles)
        if not player_veh:
            return

        veh_name = str(player_veh.get("mVehicleName", player_veh.get("vehicleName", ""))).strip()
        veh_class = str(player_veh.get("mVehicleClass", player_veh.get("vehicleClass", ""))).strip()
        laps_comp = int(player_veh.get("mTotalLaps", player_veh.get("totalLaps", 0)))

        # Changement de session/circuit/véhicule
        if track_name and (track_name != self._track_name or (veh_name and veh_name != self._vehicle_name)):
            logger.info(f"[DeltaEngine] Reset session: track='{track_name}', veh='{veh_name}', class='{veh_class}'")
            print(f"[DeltaEngine] Changement de circuit/session détecté : '{track_name}' (Voiture: {veh_name})", flush=True)
            self._track_name = track_name
            self._vehicle_name = veh_name
            self._vehicle_class = veh_class
            self._current_lap_samples = []
            self._last_laps_completed = laps_comp
            self._last_checkpoint_idx = -1
            self._s1_checkpoint_captured = False
            self._s2_checkpoint_captured = False
            self._s1_checkpoint_delta = 0.0
            self._s2_checkpoint_delta = 0.0
            self._sector1_delta = 0.0
            self._sector2_delta = 0.0
            self._sector3_delta = 0.0
            self._last_scoring_timestamp = 0.0
            self._last_physics_timestamp = 0.0
            self._est_dist = 0.0
            self._est_time_into = 0.0

            # Réinitialiser session et stint best
            self._session_best_profile = None
            self._stint_best_profile = None
            self._last_lap_profile = None
            self._session_best_lap_time = 999999.0
            self._stint_best_lap_time = 999999.0
            self._last_lap_time = 999999.0

            # Charger le profil de référence pour ce circuit/voiture depuis le disque
            self._load_reference_profile()

        if track_len > 0.0:
            self._track_length = track_len

        time_into = float(player_veh.get("mTimeIntoLap", -1.0))
        player_dist = float(player_veh.get("mLapDist", 0.0))
        raw_sec = int(player_veh.get("mSector", 1))
        curr_sec = 3 if raw_sec == 0 else (raw_sec if raw_sec in (1, 2, 3) else 1)

        in_garage = bool(player_veh.get("mInGarageStall", player_veh.get("inGarageStall", False)))
        in_pits = bool(player_veh.get("mInPits", player_veh.get("inPits", False)))
        lap_flag = int(player_veh.get("mCountLapFlag", player_veh.get("countLapFlag", 2)))
        last_lap_time = float(player_veh.get("mLastLapTime", -1.0))

        self._last_lap_flag = lap_flag

        self._handle_lap_transition(laps_comp, last_lap_time, lap_flag, in_garage, in_pits)
        self._handle_sector_transition(curr_sec)

        is_flying_lap = (lap_flag == 2 and time_into > 0.0)

        # Réinitialiser le stint best si arrêt complet aux stands
        if in_pits and self._stint_best_lap_time != 999999.0 and self._last_speed_ms < 0.1:
            self._stint_best_profile = None
            self._stint_best_lap_time = 999999.0
            self._apply_active_profile()

        # Enregistrement des échantillons de référence uniquement si tour valide en cours
        if is_flying_lap:
            self._collect_lap_sample(
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

        # Si tour lancé en cours, mise à jour de la position et calcul du delta au checkpoint
        if is_flying_lap:
            # Recalage doux de l'estimateur de position continue
            if self._est_dist <= 0.0 or abs(self._est_dist - player_dist) > 15.0 or (self._track_length > 0.0 and player_dist < 50.0 and self._est_dist > self._track_length - 100.0):
                self._est_dist = player_dist
                self._est_time_into = time_into
            else:
                self._est_dist = 0.85 * player_dist + 0.15 * self._est_dist
                self._est_time_into = time_into

            # Détection du checkpoint spatial
            step = self._ref_spatial_step if self._ref_spatial_step > 0.0 else 1.0
            checkpoint_idx = int(self._est_dist / step)
            if checkpoint_idx != self._last_checkpoint_idx:
                self._last_checkpoint_idx = checkpoint_idx
                self._calculate_delta(self._est_dist, self._est_time_into)
        else:
            # Out-lap / Stands / Avant le départ : pas de delta de tour lancé
            self._live_delta = 0.0
            self._last_checkpoint_idx = -1
            self._est_dist = player_dist
            self._est_time_into = max(0.0, time_into)

    def update_physics(
        self,
        veh_speed_ms: float,
        throttle: float = 0.0,
        brake: float = 0.0,
        steering: float = 0.0,
        dt: float = 0.0,
        elapsed_time: float = 0.0,
    ) -> None:
        """
        Traite un paquet TelemInfoV01 à haute fréquence (50 Hz).
        Utilise prioritairement le pas de simulation du moteur physique du jeu (mDeltaTime / mElapsedTime).
        """
        self._last_throttle = throttle
        self._last_brake = brake
        self._last_steering = steering

        if self._last_scoring_timestamp <= 0.0:
            self._last_speed_ms = veh_speed_ms
            return

        # Priorité absolue au delta de temps fourni directement par le moteur physique de LMU (mDeltaTime)
        if 0.0 < dt < 0.5:
            dt_phys = dt
        elif elapsed_time > 0.0 and self._last_physics_elapsed > 0.0 and 0.0 < (elapsed_time - self._last_physics_elapsed) < 0.5:
            dt_phys = elapsed_time - self._last_physics_elapsed
        else:
            now = time.time()
            first_phys_tick = (self._last_physics_timestamp <= 0.0)
            if first_phys_tick:
                dt_phys = (now - self._last_scoring_timestamp) if (0.0 < now - self._last_scoring_timestamp < 0.5) else 0.02
            else:
                dt_phys = now - self._last_physics_timestamp
            self._last_physics_timestamp = now

        if elapsed_time > 0.0:
            self._last_physics_elapsed = elapsed_time

        # Intégration spatiale et temporelle continue basée sur la physique du jeu
        if 0.0 < dt_phys < 0.5 and veh_speed_ms >= 0.0:
            avg_speed = veh_speed_ms if self._last_speed_ms <= 0.0 else 0.5 * (veh_speed_ms + self._last_speed_ms)
            self._est_dist += avg_speed * dt_phys
            self._est_time_into += dt_phys

            # Bouclage en bout de circuit
            if self._track_length > 0.0 and self._est_dist > self._track_length:
                self._est_dist = self._est_dist % self._track_length

            # Checkpoint spatial franchi ?
            step = self._ref_spatial_step if self._ref_spatial_step > 0.0 else 1.0
            checkpoint_idx = int(self._est_dist / step)

            # Mise à jour du delta UNIQUEMENT au franchissement d'un nouveau checkpoint spatial !
            if checkpoint_idx != self._last_checkpoint_idx:
                self._last_checkpoint_idx = checkpoint_idx
                self._calculate_delta(self._est_dist, self._est_time_into)

                # Collecte haute fréquence pendant un tour valide
                if self._last_lap_flag == 2 and self._est_time_into > 0.0 and self._est_dist >= 0.0:
                    if not self._current_lap_samples or (self._est_dist - self._current_lap_samples[-1][0]) >= 0.8:
                        self._current_lap_samples.append((
                            self._est_dist,
                            self._est_time_into,
                            veh_speed_ms,
                            throttle,
                            brake,
                            steering,
                        ))

        self._last_speed_ms = veh_speed_ms

    def _calculate_delta(self, player_dist: float, time_into: float) -> None:
        """Calcul du delta live et des deltas par secteur à partir d'une position et d'un temps."""
        if not self.has_reference or self._ref_t_grid is None or self._ref_num_points < 2 or time_into <= 0.0 or player_dist < 0.0:
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

        raw_delta = time_into - ref_time

        # Borner les deltas extrêmes à +/- 999.0s
        if abs(raw_delta) < 999.0:
            # Lissage optionnel par Moyenne Mobile Exponentielle (EMA)
            if self._ema_samples > 1:
                factor = 2.0 / (self._ema_samples + 1.0)
                self._ema_live_delta += factor * (raw_delta - self._ema_live_delta)
                self._live_delta = self._ema_live_delta
            else:
                self._live_delta = raw_delta
                self._ema_live_delta = raw_delta
        else:
            self._live_delta = 0.0

        # Sauvegarde du delta pour maintien figé à l'arrêt
        self._frozen_checkpoint_delta = self._live_delta

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
        # Seul un tour où le jeu confirme lap_flag == 2 (propre et chronométré) peut être enregistré
        if lap_flag != 2:
            logger.info(f"[DeltaEngine] Lap rejected: Not a clean timed lap (lap_flag={lap_flag})")
            print(f"[DeltaEngine] Tour non enregistré : Statut jeu invalide / Dirty / Out-lap (lap_flag={lap_flag})", flush=True)
            return

        # Repli : si lap_time n'est pas transmis par le jeu (<= 0), utiliser le temps du dernier échantillon
        if lap_time <= 0.0 and len(self._current_lap_samples) >= 5:
            lap_time = float(self._current_lap_samples[-1][1])

        sample_count = len(self._current_lap_samples)
        logger.info(f"[DeltaEngine] Lap completed: lap_time={lap_time:.3f}s, flag={lap_flag}, samples={sample_count}")
        print(f"[DeltaEngine] Tour complété : {lap_time:.3f}s (drapeau={lap_flag}, échantillons={sample_count})", flush=True)

        if lap_time <= 10.0 or sample_count < 5:
            logger.info(f"[DeltaEngine] Lap rejected: Insufficient samples ({sample_count}) or invalid time ({lap_time:.3f}s)")
            print(f"[DeltaEngine] Tour non enregistré : Échantillons insuffisants ({sample_count} pts) ou temps invalide ({lap_time:.3f}s)", flush=True)
            return

        # Filtrer la liste pour garantir une monotonie stricte des distances
        clean_samples: List[Tuple[float, ...]] = []
        last_d = -1.0
        for sample in self._current_lap_samples:
            d = sample[0]
            if d > last_d:
                clean_samples.append(sample)
                last_d = d

        if len(clean_samples) < 2 or clean_samples[-1][0] <= 0.0:
            print(f"[DeltaEngine] Tour non enregistré : Échantillons filtrés invalides ({len(clean_samples)} pts)", flush=True)
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

        spatial_step = 1.0
        t_grid, speed_grid, throttle_grid, brake_grid, steering_grid, num_points = self._resample_spatial_grid(
            clean_samples,
            spatial_step=spatial_step,
        )

        # Déterminer les chemins de fichiers (télémétrie .json et marks .marks.json)
        filepath = self._get_profile_filepath()
        marks_path = get_marks_filepath(filepath) if filepath else None

        # Conserver les annotations existantes UNIQUEMENT si elles appartiennent à CE circuit
        existing_annotations: List[TrackAnnotation] = []
        if self._current_profile and self._current_profile.annotations:
            prof_track = getattr(self._current_profile, "track_name", "")
            if not prof_track or clean_name_identifier(prof_track) == clean_name_identifier(self._track_name):
                existing_annotations = list(self._current_profile.annotations)

        # Si aucune annotation en mémoire, chercher rigoureusement sur le disque pour CE circuit
        if not existing_annotations:
            disk_marks_path = find_marks_filepath_for_track(
                self._track_name,
                self._vehicle_class,
                self._vehicle_name,
                base_dir=_REF_LAPS_DIR,
            )
            if disk_marks_path and disk_marks_path.exists():
                temp_prof = ReferenceLapProfile(track_name=self._track_name)
                temp_prof.load_marks_from_file(disk_marks_path)
                existing_annotations = temp_prof.annotations

        # Construction du profil complet du tour complété
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

        # Mise à jour de la hiérarchie Multi-Références
        self._last_lap_profile = profile
        self._last_lap_time = lap_time

        if self._stint_best_profile is None or lap_time < self._stint_best_lap_time:
            self._stint_best_profile = profile
            self._stint_best_lap_time = lap_time

        if self._session_best_profile is None or lap_time < self._session_best_lap_time:
            self._session_best_profile = profile
            self._session_best_lap_time = lap_time

        # Mise à jour du meilleur tour absolu (disque)
        if self._all_time_best_profile is None or lap_time < self._all_time_best_lap_time:
            self._all_time_best_profile = profile
            self._all_time_best_lap_time = lap_time
            logger.info(f"[DeltaEngine] New All-Time Best Reference Lap Recorded! Time: {lap_time:.3f}s ({num_points} grid points, {len(existing_annotations)} marks)")
            print(f"[DeltaEngine] ★ NOUVEAU TOUR DE RÉFÉRENCE ABSOLU : {lap_time:.3f}s sur '{self._track_name}' ({len(existing_annotations)} annotations)", flush=True)
            self._save_reference_profile()
        else:
            logger.info(f"[DeltaEngine] Lap clean ({lap_time:.3f}s) -> Stored in Last/Session/Stint references.")
            print(f"[DeltaEngine] Tour propre ({lap_time:.3f}s) enregistré dans la session (Best absolu: {self._all_time_best_lap_time:.3f}s)", flush=True)

        # Appliquer la référence active en fonction du mode configuré
        self._apply_active_profile()

    def _get_profile_filepath(self) -> Optional[Path]:
        """Retourne le chemin du fichier JSON pour (track, vehicle_class/vehicle)."""
        if not self._track_name:
            return None
        t_clean = _clean_name(self._track_name)
        v_identifier = _clean_name(self._vehicle_class) if self._vehicle_class else _clean_name(self._vehicle_name)
        if not v_identifier:
            v_identifier = "default"
        filename = f"ref_{t_clean}_{v_identifier}.json"
        return _REF_LAPS_DIR / filename

    def _save_reference_profile(self) -> None:
        """Sauvegarde automatique de la télémétrie du tour de référence absolu sur le disque JSON."""
        filepath = self._get_profile_filepath()
        if not filepath or self._all_time_best_profile is None:
            return
        ok = self._all_time_best_profile.save_telemetry_to_file(filepath)
        if ok:
            print(f"[DeltaEngine] Fichier sauvegardé sur le disque : {filepath}", flush=True)
        else:
            print(f"[DeltaEngine] ERREUR : Impossible d'écrire le fichier de référence : {filepath}", flush=True)

    def _load_reference_profile(self) -> None:
        """Tente de charger un profil de référence et les repères enregistrés sur disque pour le circuit/voiture."""
        filepath = self._get_profile_filepath()
        if not filepath or not filepath.exists():
            filepath = find_telemetry_filepath_for_track(
                self._track_name,
                self._vehicle_class,
                self._vehicle_name,
                base_dir=_REF_LAPS_DIR,
            )

        marks_filepath = find_marks_filepath_for_track(
            self._track_name,
            self._vehicle_class,
            self._vehicle_name,
            base_dir=_REF_LAPS_DIR,
        )

        # 1. Cas idéal : Télémétrie complète existante pour ce circuit
        if filepath and filepath.exists():
            loaded = ReferenceLapProfile.load_from_file(filepath)
            if loaded and loaded.t_grid and len(loaded.t_grid) > 1:
                self._all_time_best_profile = loaded
                self._all_time_best_lap_time = loaded.lap_time
                self._apply_active_profile()
                logger.info(f"[DeltaEngine] Loaded reference profile from {filepath.name} ({self._ref_lap_time:.3f}s, {len(loaded.annotations)} annotations)")
                print(f"[DeltaEngine] Tour de référence et repères chargés : {filepath.name} ({self._ref_lap_time:.3f}s, {len(loaded.annotations)} annotations)", flush=True)
                return

        # 2. Cas sans tour chrono enregistré mais avec fichier de repères (.marks.json) existant pour ce circuit
        if marks_filepath and marks_filepath.exists():
            placeholder = ReferenceLapProfile(
                track_name=self._track_name,
                vehicle_name=self._vehicle_name,
                vehicle_class=self._vehicle_class,
                track_length=self._track_length,
            )
            placeholder.set_marks_filepath(marks_filepath)
            placeholder.load_marks_from_file(marks_filepath)
            self._all_time_best_profile = placeholder
            self._all_time_best_lap_time = 999999.0
            self._apply_active_profile()
            print(f"[DeltaEngine] Repères de piste chargés pour '{self._track_name}' : {marks_filepath.name} ({len(placeholder.annotations)} annotations). En attente du 1er tour chrono.", flush=True)
            return

        # 3. Aucun fichier trouvé pour ce circuit : état vierge (0 annotations, aucune fuite d'un autre circuit)
        self._all_time_best_profile = None
        self._all_time_best_lap_time = 999999.0
        self._apply_active_profile()
        fname = filepath.name if filepath else "aucun"
        print(f"[DeltaEngine] Aucun tour de référence ni repères pour '{self._track_name}' ({fname}). En attente du 1er tour lancé.", flush=True)

    @property
    def live_delta(self) -> float:
        """Delta brut en direct."""
        return self._live_delta

    @property
    def display_delta(self) -> float:
        """Delta pour affichage HUD (gelé pendant freeze_duration secondes après franchissement)."""
        if time.time() < self._freeze_delta_until:
            return self._frozen_final_delta
        return self._live_delta

    @property
    def estimated_lap_time(self) -> float:
        """Projection du temps au tour final (ref_lap_time + live_delta)."""
        if self.has_reference and self._ref_lap_time < 999999.0:
            return max(0.0, self._ref_lap_time + self._live_delta)
        return 0.0

    @property
    def estimated_lap_time_str(self) -> str:
        """Projection du chrono formatée 'M:SS.mmm'."""
        est = self.estimated_lap_time
        if est > 0.0:
            m = int(est // 60)
            s = est % 60
            return f"{m}:{s:06.3f}"
        return "--:--.---"

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

    @property
    def is_pit_lap(self) -> bool:
        """Retourne True si le tour en cours est un Out-lap / in-lap (lap_flag == 1)."""
        return self._last_lap_flag == 1

    def get_live_car_distance(self) -> float:
        """Retourne la distance courante estimée de la voiture."""
        if self._est_dist > 0.0:
            return self._est_dist
        return self._last_scoring_dist
