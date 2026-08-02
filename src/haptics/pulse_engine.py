"""
SimPad Haptics — 1000 Hz High-Resolution Haptic Impulse Synthesizer.
Features hard-gated waveform shape envelopes, physical motor activation offset (0.30),
guaranteed hard-zero rest phases, and 50 Hz hardware rate-limiting.
"""

import sys
import time
import math
import ctypes
import threading
import logging
from dataclasses import dataclass
from typing import Tuple, Dict, Any, Optional

logger = logging.getLogger(__name__)

if sys.platform == "win32":
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass


class WaveformShape:
    FLAT = "flat"          # Continuous rumble (no pulsing)
    SQUARE = "square"      # Crisp mechanical pulse (ABS / TC snap)
    SAWTOOTH = "sawtooth"  # Progressive ramp + sudden drop (Tire scrub)
    SINE = "sine"          # Smooth bell curve surge + rest (Weight transfer)
    BURST = "burst"        # Sharp impact decay + rest (Curb impact)

    CHOICES = [
        ("Flat (Continuous)", FLAT),
        ("Square (Pulsed)", SQUARE),
        ("Sawtooth (Scrub)", SAWTOOTH),
        ("Sine (Smooth)", SINE),
        ("Burst (Impact)", BURST),
    ]


@dataclass
class HapticEffectParams:
    """Paramètres d'impulsion configurables depuis l'UI."""
    # Courbe Low Freq → canal lf (low_frequency_rumble)
    low_gain: float = 1.0
    low_gamma: float = 1.0
    # Courbe High Freq → canal hf (high_frequency_rumble)
    high_gain: float = 0.3
    high_gamma: float = 1.0
    # Seuil commun
    cutoff: float = 0.0
    # Forme et timing d'impulsion
    shape: str = WaveformShape.SQUARE
    pulse_on_ms: float = 20.0
    pulse_off_ms: float = 30.0


class HapticPulseSynthesizer:
    """
    Synthétiseur haptique 1000 Hz (1 ms).
    Génère des signaux haptiques modulés en millisecondes (Pulse ON ms / Pulse OFF ms).
    """

    def __init__(self, haptics_controller=None):
        self.controller = haptics_controller
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Raw telemetry inputs
        self._raw_lock: float = 0.0
        self._raw_spin: float = 0.0
        self._raw_oversteer: float = 0.0
        self._raw_understeer: float = 0.0

        # Calibrated default effect parameters in ms
        # Paramètres LRA (Linear Resonant Actuator — Gulikit/DualSense)
        self.params: Dict[str, HapticEffectParams] = {
            "lock":       HapticEffectParams(low_gain=1.0, low_gamma=1.0,  high_gain=1.0, high_gamma=1.5, cutoff=0.0, shape=WaveformShape.SQUARE,   pulse_on_ms=20.0, pulse_off_ms=30.0),
            "spin":       HapticEffectParams(low_gain=1.0, low_gamma=1.0,  high_gain=0.2, high_gamma=2.0, cutoff=0.0, shape=WaveformShape.SAWTOOTH, pulse_on_ms=15.0, pulse_off_ms=25.0),
            "oversteer":  HapticEffectParams(low_gain=1.0, low_gamma=1.2,  high_gain=0.4, high_gamma=1.0, cutoff=0.0, shape=WaveformShape.SINE,     pulse_on_ms=25.0, pulse_off_ms=35.0),
            "understeer": HapticEffectParams(low_gain=0.5, low_gamma=1.5,  high_gain=0.8, high_gamma=1.0, cutoff=0.0, shape=WaveformShape.SAWTOOTH, pulse_on_ms=15.0, pulse_off_ms=20.0),
        }

        # Internal phase accumulators (0.0 to 1.0)
        self._phases = {"lock": 0.0, "spin": 0.0, "oversteer": 0.0, "understeer": 0.0}
        self._last_time = time.perf_counter()

        # Rate limiting hardware updates (max 50 Hz = 20 ms)
        self._last_hw_time: float = 0.0
        self._last_hw_vib: Tuple[float, float] = (-1.0, -1.0)
        self._hw_interval: float = 0.005  # 200 Hz hardware output (5 ms)

    def set_controller(self, controller):
        with self._lock:
            self.controller = controller

    def update_telemetry(self, lock: float, spin: float, oversteer: float, understeer: float):
        """Met à jour les intensités brutes issues des capteurs VehicleSensors."""
        with self._lock:
            self._raw_lock = max(0.0, min(1.0, lock))
            self._raw_spin = max(0.0, min(1.0, spin))
            self._raw_oversteer = max(0.0, min(1.0, oversteer))
            self._raw_understeer = max(0.0, min(1.0, understeer))

    def update_effect_params(self, effect_id: str, **kwargs):
        """Met à jour les paramètres d'impulsion d'un effet."""
        with self._lock:
            if effect_id in self.params:
                p = self.params[effect_id]
                for k, v in kwargs.items():
                    if hasattr(p, k):
                        setattr(p, k, float(v) if isinstance(v, (int, float)) else v)

    def _eval_waveform(self, shape: str, phase: float, duty: float) -> float:
        """
        Évalue la forme d'onde avec pause à ZÉRO STRICT (HARD ZERO REST PHASE).
        Phase (0.0 à 1.0). Si phase >= duty, retourne 0.0 (arrêt du moteur).
        Pour FLAT, retourne 1.0 continu sans pulsation.
        """
        if shape == WaveformShape.FLAT:
            return 1.0

        phase = phase % 1.0

        # Phase de repos (OFF) -> Zéro strict pour permettre le débrayage du moteur
        if phase >= duty:
            return 0.0

        # Phase active (ON) normalisée entre 0.0 et 1.0
        norm_phase = phase / max(0.001, duty)

        if shape == WaveformShape.SQUARE:
            return 1.0
        elif shape == WaveformShape.SAWTOOTH:
            return norm_phase  # Montée progressive puis chute brute à 0
        elif shape == WaveformShape.SINE:
            return math.sin(math.pi * norm_phase)  # Cloche fluide 0 -> 1 -> 0
        elif shape == WaveformShape.BURST:
            return math.exp(-4.0 * norm_phase)  # Impulsion initiale forte puis décroissance
        return 1.0

    def start(self):
        if self._running:
            return
        self._running = True
        self._last_time = time.perf_counter()
        self._thread = threading.Thread(target=self._loop_1000hz, daemon=True)
        self._thread.start()
        logger.info("[PulseSynthesizer] Started 1000 Hz Haptic Loop (ms precision + Hard Zero)")

    def _loop_1000hz(self):
        """Boucle sub-milliseconde haute précision à 1000 Hz (1 ms)."""
        target_step = 0.001
        t_next = time.perf_counter() + target_step

        while self._running:
            t0 = time.perf_counter()
            dt = t0 - self._last_time
            self._last_time = t0
            dt = max(0.0001, min(0.010, dt))

            with self._lock:
                raw_lock = self._raw_lock
                raw_spin = self._raw_spin
                raw_over = self._raw_oversteer
                raw_under = self._raw_understeer

            lf_raw, hf_raw = 0.0, 0.0

            for eid, raw_val in [
                ("lock", raw_lock),
                ("spin", raw_spin),
                ("oversteer", raw_over),
                ("understeer", raw_under),
            ]:
                p = self.params[eid]
                if raw_val <= p.cutoff:
                    continue

                # Calcul de la période globale (ON ms + OFF ms)
                total_ms = max(5.0, p.pulse_on_ms + p.pulse_off_ms)
                pulse_freq = 1000.0 / total_ms
                duty_cycle = p.pulse_on_ms / total_ms

                # Avancer la phase à 1000 Hz : phase += freq * dt
                self._phases[eid] = (self._phases[eid] + pulse_freq * dt) % 1.0
                mod = self._eval_waveform(p.shape, self._phases[eid], duty_cycle)

                # Signal brut 0.0-1.0 (sans seuil physique — appliqué par moteur ensuite)
                # Calcul séparé lf/hf depuis les courbes de réponse UI :
                #   low_gain/low_gamma  → lf_raw (canal grave)
                #   high_gain/high_gamma → hf_raw (canal aigu)
                norm_val = max(0.0, min(1.0, (raw_val - p.cutoff) / max(0.001, 1.0 - p.cutoff)))

                lf_sig = math.pow(norm_val, p.low_gamma)  * p.low_gain  * mod
                hf_sig = math.pow(norm_val, p.high_gamma) * p.high_gain * mod

                lf_raw = max(lf_raw, max(0.0, min(1.0, lf_sig)))
                hf_raw = max(hf_raw, max(0.0, min(1.0, hf_sig)))

            # LRA (Gulikit/DualSense) : pas de seuil de démarrage.
            # Réponse linéaire directe depuis 0%, hard zero réel sur OFF.
            lf_out = max(0.0, min(1.0, lf_raw))
            hf_out = max(0.0, min(1.0, hf_raw))

            # Transmettre au contrôleur matériel à 50 Hz (toutes les 18 ms)
            # Pour les signaux non-nuls : toujours rafraîchir SDL3 pour éviter
            # que duration_ms expire avant la prochaine commande (sinon: silence au milieu d'une phase ON).
            # Pour le zéro : seulement envoyer si changement (éviter le spam de silences).
            if self.controller and (t0 - self._last_hw_time >= self._hw_interval):
                self._last_hw_time = t0
                target_vib = (round(lf_out, 2), round(hf_out, 2))
                is_silent = (lf_out == 0.0 and hf_out == 0.0)
                if not is_silent or target_vib != self._last_hw_vib:
                    self._last_hw_vib = target_vib
                    try:
                        # duration_ms = pulse_on_ms de l'effet dominant (couvre la phase ON complète)
                        dominant_on_ms = max(
                            (self.params[eid].pulse_on_ms for eid in self.params if not is_silent),
                            default=20.0
                        )
                        dur_ms = 10 if is_silent else max(20, int(dominant_on_ms))
                        self.controller.set_vibration(lf_out, 0.0, 0.0, hf_out, duration_ms=dur_ms)
                    except Exception:
                        pass

            now = time.perf_counter()
            sleep_sec = t_next - now
            if sleep_sec > 0.0005:
                time.sleep(sleep_sec - 0.0003)
            while time.perf_counter() < t_next:
                pass
            t_next += target_step

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
        if sys.platform == "win32":
            try:
                ctypes.windll.winmm.timeEndPeriod(1)
            except Exception:
                pass
        logger.info("[PulseSynthesizer] Stopped 1000 Hz Haptic Loop")
