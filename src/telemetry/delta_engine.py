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
_DEBUG_LOG_PATH = _PROJECT_ROOT / "delta_debug.log"


def log_delta_debug(msg: str) -> None:
    """Écrit une ligne de log dans delta_debug.log pour diagnostic en direct."""
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


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
        self._last_gear: int = 0

        # Dernier état de scoring (1-2 Hz)
        self._last_scoring_dist: float = 0.0
        self._last_scoring_time_into: float = 0.0
        self._last_scoring_timestamp: float = 0.0
        self._last_current_sector: int = 1
        self._last_lap_start_et: float = 0.0

        # Checkpoints de secteurs dynamiques (temps & distance du pilote aux coupures S1/S2)
        self._s1_captured: bool = False
        self._s2_captured: bool = False
        self._player_s1_time: float = 0.0
        self._player_s1_dist: float = 0.0
        self._player_s2_time: float = 0.0
        self._player_s2_dist: float = 0.0
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

        log_delta_debug(
            f"[APPLY_MODE] mode={self._ref_mode.value}, target_present={target_prof is not None}, "
            f"has_ref={self.has_reference}, ref_lap_time={self._ref_lap_time:.3f}s, points={self._ref_num_points}"
        )

        # Recalcul dynamique immédiat des deltas contre la nouvelle référence
        if self._last_scoring_dist >= 0.0 and self._last_scoring_time_into > 0.0:
            self._calculate_delta(self._last_scoring_dist, self._last_scoring_time_into)
        else:
            self._live_delta = 0.0
            self._sector1_delta = 0.0
            self._sector2_delta = 0.0
            self._sector3_delta = 0.0

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
            return

        # Cas 1 : Réinitialisation de session / Relance (mTotalLaps repasse à 0 ou diminue)
        if laps_comp < self._last_laps_completed:
            logger.info(f"[DeltaEngine] Session reset detected: laps completed went from {self._last_laps_completed} to {laps_comp}")
            print(f"[DeltaEngine] Session réinitialisée : compteur de tours remis à {laps_comp}", flush=True)
            log_delta_debug(f"[SESSION_RESET] laps_completed went from {self._last_laps_completed} to {laps_comp}")
            self._current_lap_samples = []
            self._s1_captured = False
            self._s2_captured = False
            self._player_s1_time = 0.0
            self._player_s1_dist = 0.0
            self._player_s2_time = 0.0
            self._player_s2_dist = 0.0
            self._sector1_delta = 0.0
            self._sector2_delta = 0.0
            self._sector3_delta = 0.0
            self._last_laps_completed = laps_comp
            return

        # Cas 2 : Franchissement de la ligne de départ/arrivée (nouveau tour complété)
        if laps_comp > self._last_laps_completed:
            log_delta_debug(
                f"[LAP_LINE_CROSS] lap_completed={laps_comp} (was {self._last_laps_completed}), "
                f"last_lap_time={last_lap_time:.3f}s, flag={lap_flag}, in_pits={in_pits}, in_garage={in_garage}"
            )
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
            self._s1_captured = False
            self._s2_captured = False
            self._player_s1_time = 0.0
            self._player_s1_dist = 0.0
            self._player_s2_time = 0.0
            self._player_s2_dist = 0.0
            self._sector1_delta = 0.0
            self._sector2_delta = 0.0
            self._sector3_delta = 0.0

        self._last_laps_completed = laps_comp

    def _handle_sector_transition(self, curr_sec: int, time_into: float = 0.0, player_dist: float = 0.0) -> None:
        """SLAP Helper: Mémorise le temps et la distance exacts de passage aux coupures S1/S2."""
        if curr_sec != self._last_current_sector:
            if curr_sec == 2 and not self._s1_captured and time_into > 0.0:
                self._player_s1_time = time_into
                self._player_s1_dist = player_dist
                self._s1_captured = True
                log_delta_debug(f"[SECTOR_CUT_S1] t_into={time_into:.3f}s, dist={player_dist:.1f}m")
            elif curr_sec == 3 and not self._s2_captured and time_into > 0.0:
                self._player_s2_time = time_into
                self._player_s2_dist = player_dist
                self._s2_captured = True
                log_delta_debug(f"[SECTOR_CUT_S2] t_into={time_into:.3f}s, dist={player_dist:.1f}m")
            self._last_current_sector = curr_sec

    def _collect_lap_sample(
        self,
        time_into: float,
        player_dist: float,
        speed_ms: float = 0.0,
        throttle: float = 0.0,
        brake: float = 0.0,
        steering: float = 0.0,
        gear: int = 0,
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
                        gear,
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
            log_delta_debug(f"[TRACK_CHANGE] track='{track_name}', veh='{veh_name}', class='{veh_class}', laps={laps_comp}")
            self._track_name = track_name
            self._vehicle_name = veh_name
            self._vehicle_class = veh_class
            self._current_lap_samples = []
            self._last_laps_completed = laps_comp
            self._last_checkpoint_idx = -1
            self._s1_captured = False
            self._s2_captured = False
            self._player_s1_time = 0.0
            self._player_s1_dist = 0.0
            self._player_s2_time = 0.0
            self._player_s2_dist = 0.0
            self._sector1_delta = 0.0
            self._sector2_delta = 0.0
            self._sector3_delta = 0.0
            self._last_scoring_timestamp = 0.0

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

        current_et = float(scoring_info.get("mCurrentET", scoring_info.get("currentET", 0.0)))
        lap_start_et = float(player_veh.get("mLapStartET", player_veh.get("lapStartET", 0.0)))
        time_into_lap = float(player_veh.get("mTimeIntoLap", -1.0))

        # Calcul autoritaire du temps écoulé dans le tour : mCurrentET - mLapStartET
        # (mTimeIntoLap du SDK rF2/LMU est une simple estimation basée sur la distance,
        # non continue et insensible aux arrêts ou rythmes lents)
        if lap_start_et > 0.0 and current_et >= lap_start_et:
            time_into = current_et - lap_start_et
            self._last_lap_start_et = lap_start_et
        else:
            time_into = time_into_lap if time_into_lap > 0.0 else 0.0

        player_dist = float(player_veh.get("mLapDist", 0.0))
        raw_sec = int(player_veh.get("mSector", 1))
        curr_sec = 3 if raw_sec == 0 else (raw_sec if raw_sec in (1, 2, 3) else 1)

        in_garage = bool(player_veh.get("mInGarageStall", player_veh.get("inGarageStall", False)))
        in_pits = bool(player_veh.get("mInPits", player_veh.get("inPits", False)))
        lap_flag = int(player_veh.get("mCountLapFlag", player_veh.get("countLapFlag", 2)))
        last_lap_time = float(player_veh.get("mLastLapTime", -1.0))

        self._last_lap_flag = lap_flag

        self._handle_lap_transition(laps_comp, last_lap_time, lap_flag, in_garage, in_pits)
        self._handle_sector_transition(curr_sec, time_into=time_into, player_dist=player_dist)

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
                gear=self._last_gear,
            )

        self._last_scoring_dist = player_dist
        self._last_scoring_time_into = time_into
        self._last_scoring_timestamp = now
        self._last_dist = player_dist

        # Si tour lancé en cours, mise à jour de la position et calcul du delta au checkpoint
        if is_flying_lap:
            # Calcul du delta avec les données exactes du jeu (mLapDist, temps écoulé réel)
            self._calculate_delta(player_dist, time_into)
        else:
            # Out-lap / Stands / Avant le départ : pas de delta de tour lancé
            self._live_delta = 0.0
            self._last_checkpoint_idx = -1
            log_delta_debug(
                f"[SCORING_NOT_FLYING] dist={player_dist:.1f}m, t_into={time_into:.3f}s, flag={lap_flag}, "
                f"sec={curr_sec}, laps={laps_comp}, in_pits={in_pits}, in_garage={in_garage}"
            )

    def update_physics(
        self,
        veh_speed_ms: float,
        throttle: float = 0.0,
        brake: float = 0.0,
        steering: float = 0.0,
        gear: int = 0,
        dt: float = 0.0,
        elapsed_time: float = 0.0,
        lap_start_et: float = 0.0,
    ) -> None:
        """
        Traite un paquet TelemInfoV01 à haute fréquence (50-100 Hz).
        Met à jour le delta live en direct à 100 Hz avec le chrono continu (elapsed_time - lap_start_et).
        """
        self._last_speed_ms = veh_speed_ms
        self._last_throttle = throttle
        self._last_brake = brake
        self._last_steering = steering
        self._last_gear = gear

        if self._last_lap_flag == 2 and self._last_scoring_dist >= 0.0:
            effective_start_et = lap_start_et if lap_start_et > 0.0 else self._last_lap_start_et
            if effective_start_et > 0.0 and elapsed_time >= effective_start_et:
                phys_time_into = elapsed_time - effective_start_et
                self._calculate_delta(self._last_scoring_dist, phys_time_into)

    def _get_ref_time_at_dist(self, dist: float) -> Optional[float]:
        """Retourne le temps de référence interpolé à une distance donnée sur le profil actif."""
        if not self.has_reference or self._ref_t_grid is None or self._ref_num_points < 2 or dist < 0.0:
            return None
        step = self._ref_spatial_step if self._ref_spatial_step > 0.0 else 1.0
        idx_float = dist / step
        idx_floor = int(idx_float)
        if idx_floor < 0:
            return self._ref_t_grid[0]
        elif idx_floor >= self._ref_num_points - 1:
            return self._ref_t_grid[-1]
        else:
            frac = idx_float - idx_floor
            t1 = self._ref_t_grid[idx_floor]
            t2 = self._ref_t_grid[idx_floor + 1]
            return t1 + frac * (t2 - t1)

    def _calculate_delta(self, player_dist: float, time_into: float) -> None:
        """Calcul du delta live et des deltas par secteur à partir d'une position et d'un temps."""
        if not self.has_reference or time_into <= 0.0 or player_dist < 0.0:
            self._live_delta = 0.0
            self._sector1_delta = 0.0
            self._sector2_delta = 0.0
            self._sector3_delta = 0.0
            log_delta_debug(
                f"[DELTA_NO_REF] dist={player_dist:.1f}m, t_into={time_into:.3f}s, has_ref={self.has_reference}, "
                f"flag={self._last_lap_flag}, mode={self._ref_mode.value}"
            )
            return

        ref_time = self._get_ref_time_at_dist(player_dist)
        if ref_time is None:
            self._live_delta = 0.0
            self._sector1_delta = 0.0
            self._sector2_delta = 0.0
            self._sector3_delta = 0.0
            log_delta_debug(
                f"[DELTA_REF_LOOKUP_FAIL] dist={player_dist:.1f}m, t_into={time_into:.3f}s, "
                f"ref_num_points={self._ref_num_points}"
            )
            return

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

        # Calcul dynamique des deltas de secteurs contre le profil ACTIF
        ref_s1 = self._get_ref_time_at_dist(self._player_s1_dist) if self._s1_captured else None
        ref_s2 = self._get_ref_time_at_dist(self._player_s2_dist) if self._s2_captured else None

        delta_s1_end = (self._player_s1_time - ref_s1) if (self._s1_captured and ref_s1 is not None) else 0.0
        delta_s2_end = (self._player_s2_time - ref_s2) if (self._s2_captured and ref_s2 is not None) else 0.0

        if self._last_current_sector == 1:
            self._sector1_delta = self._live_delta
            self._sector2_delta = 0.0
            self._sector3_delta = 0.0
        elif self._last_current_sector == 2:
            self._sector1_delta = delta_s1_end
            self._sector2_delta = self._live_delta - delta_s1_end
            self._sector3_delta = 0.0
        elif self._last_current_sector == 3:
            self._sector1_delta = delta_s1_end
            self._sector2_delta = delta_s2_end - delta_s1_end
            self._sector3_delta = self._live_delta - delta_s2_end

        log_delta_debug(
            f"[DELTA_CALC] dist={player_dist:.1f}m, t_into={time_into:.3f}s, ref_t={ref_time:.3f}s, "
            f"raw_delta={raw_delta:+.3f}s, live_delta={self._live_delta:+.3f}s, "
            f"S1={self._sector1_delta:+.3f}s, S2={self._sector2_delta:+.3f}s, S3={self._sector3_delta:+.3f}s, "
            f"mode={self._ref_mode.value}, ref_lap_time={self._ref_lap_time:.3f}s"
        )

    def _resample_spatial_grid(
        self,
        clean_samples: List[Tuple[float, ...]],
        spatial_step: float = 1.0,
    ) -> Tuple[List[float], List[float], List[float], List[float], List[float], List[int], int]:
        """
        SLAP Helper: Construction du profil ré-échantillonné mètre par mètre sur grille spatiale uniforme.
        Interpole: temps, vitesse, accélérateur, frein, volant, rapport engagé (gear).
        """
        import bisect
        track_dist = clean_samples[-1][0]
        num_points = int(track_dist / spatial_step) + 1

        t_grid: List[float] = []
        speed_grid: List[float] = []
        throttle_grid: List[float] = []
        brake_grid: List[float] = []
        steering_grid: List[float] = []
        gear_grid: List[int] = []

        d_keys = [s[0] for s in clean_samples]

        def _get_val(sample_tuple, idx, default=0.0):
            return sample_tuple[idx] if len(sample_tuple) > idx else default

        def _get_gear_val(sample_tuple, idx, default=0):
            return int(round(sample_tuple[idx])) if len(sample_tuple) > idx else default

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
                gear_grid.append(_get_gear_val(s, 6, 0))
            elif idx >= len(clean_samples):
                s = clean_samples[-1]
                t_grid.append(s[1])
                speed_grid.append(_get_val(s, 2, 0.0))
                throttle_grid.append(_get_val(s, 3, 0.0))
                brake_grid.append(_get_val(s, 4, 0.0))
                steering_grid.append(_get_val(s, 5, 0.0))
                gear_grid.append(_get_gear_val(s, 6, 0))
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

                g1, g2 = _get_gear_val(s1, 6, 0), _get_gear_val(s2, 6, 0)
                gear_grid.append(g1 if frac < 0.5 else g2)

        return t_grid, speed_grid, throttle_grid, brake_grid, steering_grid, gear_grid, num_points

    def _finalize_completed_lap(
        self,
        lap_time: float,
        lap_flag: int,
        in_garage: bool,
        in_pits: bool,
    ) -> None:
        """Valide et enregistre le tour complété (SLAP: Orchestration haut niveau)."""
        # 1. Seul un tour où le jeu confirme lap_flag == 2 (propre et chronométré) peut être enregistré
        if lap_flag != 2:
            logger.info(f"[DeltaEngine] Lap rejected: Not a clean timed lap (lap_flag={lap_flag})")
            print(f"[DeltaEngine] Tour non enregistré : Statut jeu invalide / Dirty / Out-lap (lap_flag={lap_flag})", flush=True)
            log_delta_debug(f"[LAP_REJECTED] Statut jeu invalide (lap_flag={lap_flag})")
            return

        # 2. Le temps au tour officiel transmis par le jeu (mLastLapTime) doit être strictement positif (> 0)
        # Si mLastLapTime <= 0 (ex: -1.0 sur un Out-lap ou sortie des stands), REJET
        if lap_time <= 0.0:
            logger.info(f"[DeltaEngine] Lap rejected: Invalid official lap time ({lap_time:.3f}s)")
            print(f"[DeltaEngine] Tour non enregistré : Pas de temps officiel chronométré ({lap_time:.3f}s, Out-lap)", flush=True)
            log_delta_debug(f"[LAP_REJECTED] Pas de temps officiel chronométré (lap_time={lap_time:.3f}s)")
            return

        sample_count = len(self._current_lap_samples)
        logger.info(f"[DeltaEngine] Lap completed: lap_time={lap_time:.3f}s, flag={lap_flag}, samples={sample_count}")
        print(f"[DeltaEngine] Tour complété : {lap_time:.3f}s (drapeau={lap_flag}, échantillons={sample_count})", flush=True)

        # 3. Vérification de plausibilité physique (temps minimum selon longueur du circuit, max 400 km/h)
        if self._track_length > 500.0:
            min_possible_time = self._track_length / 110.0  # 110 m/s = 396 km/h de vitesse moyenne max
            if lap_time < min_possible_time:
                logger.warning(f"[DeltaEngine] Lap rejected: Impossible lap time ({lap_time:.3f}s < min {min_possible_time:.1f}s)")
                print(f"[DeltaEngine] Tour non enregistré : Temps physiquement impossible ({lap_time:.3f}s pour {self._track_length:.0f}m)", flush=True)
                log_delta_debug(f"[LAP_REJECTED] Temps impossible ({lap_time:.3f}s < min {min_possible_time:.1f}s)")
                return
        elif lap_time <= 15.0:
            logger.info(f"[DeltaEngine] Lap rejected: Lap time too short ({lap_time:.3f}s)")
            log_delta_debug(f"[LAP_REJECTED] Lap time too short ({lap_time:.3f}s)")
            return

        if sample_count < 10:
            logger.info(f"[DeltaEngine] Lap rejected: Insufficient samples ({sample_count})")
            print(f"[DeltaEngine] Tour non enregistré : Échantillons insuffisants ({sample_count} pts)", flush=True)
            log_delta_debug(f"[LAP_REJECTED] Échantillons insuffisants ({sample_count} pts)")
            return

        # Filtrer la liste pour garantir une monotonie stricte des distances
        clean_samples: List[Tuple[float, ...]] = []
        last_d = -1.0
        for sample in self._current_lap_samples:
            d = sample[0]
            if d > last_d:
                clean_samples.append(sample)
                last_d = d

        if len(clean_samples) < 10 or clean_samples[-1][0] <= 0.0:
            print(f"[DeltaEngine] Tour non enregistré : Échantillons filtrés invalides ({len(clean_samples)} pts)", flush=True)
            log_delta_debug(f"[LAP_REJECTED] Échantillons filtrés invalides ({len(clean_samples)} pts)")
            return

        # 4. Vérification de la couverture spatiale complète de la piste
        if self._track_length > 500.0:
            first_d = clean_samples[0][0]
            last_d = clean_samples[-1][0]
            if first_d > 250.0 or last_d < (self._track_length - 350.0):
                print(f"[DeltaEngine] Tour non enregistré : Couverture de piste incomplète ({first_d:.0f}m -> {last_d:.0f}m / {self._track_length:.0f}m)", flush=True)
                log_delta_debug(f"[LAP_REJECTED] Couverture incomplète ({first_d:.0f}m -> {last_d:.0f}m / {self._track_length:.0f}m)")
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
                first_s[6] if len(first_s) > 6 else 0,
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
                last_s[6] if len(last_s) > 6 else 0,
            ))

        spatial_step = 1.0
        t_grid, speed_grid, throttle_grid, brake_grid, steering_grid, gear_grid, num_points = self._resample_spatial_grid(
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
            gear_grid=gear_grid,
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

        log_delta_debug(
            f"[LAP_FINALIZED] lap_time={lap_time:.3f}s, flag={lap_flag}, samples={len(clean_samples)}, "
            f"grid_points={num_points}, AllTimeBest={self._all_time_best_lap_time:.3f}s, "
            f"SessionBest={self._session_best_lap_time:.3f}s, StintBest={self._stint_best_lap_time:.3f}s, "
            f"LastLap={self._last_lap_time:.3f}s"
        )

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
            log_delta_debug(f"[REF_SAVE_OK] file='{filepath.name}'")
        else:
            print(f"[DeltaEngine] ERREUR : Impossible d'écrire le fichier de référence : {filepath}", flush=True)
            log_delta_debug(f"[REF_SAVE_ERROR] file='{filepath}'")

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
                log_delta_debug(
                    f"[REF_LOAD_FULL] file='{filepath.name}', lap_time={loaded.lap_time:.3f}s, "
                    f"points={loaded.num_points}, marks={len(loaded.annotations)}"
                )
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
            log_delta_debug(f"[REF_LOAD_MARKS_ONLY] marks_file='{marks_filepath.name}', marks={len(placeholder.annotations)}")
            return

        # 3. Aucun fichier trouvé pour ce circuit : état vierge (0 annotations, aucune fuite d'un autre circuit)
        self._all_time_best_profile = None
        self._all_time_best_lap_time = 999999.0
        self._apply_active_profile()
        fname = filepath.name if filepath else "aucun"
        print(f"[DeltaEngine] Aucun tour de référence ni repères pour '{self._track_name}' ({fname}). En attente du 1er tour lancé.", flush=True)
        log_delta_debug(f"[REF_LOAD_NONE] track='{self._track_name}', searched_file='{fname}'")

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
        return self._last_scoring_dist
