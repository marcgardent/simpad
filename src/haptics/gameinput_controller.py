import math
import time
import ctypes
import threading
import logging
from ctypes import c_void_p, c_float, c_uint32, c_int32, c_ulong, Structure, POINTER, WINFUNCTYPE
from typing import Optional

from src.haptics.base import HapticController

logger = logging.getLogger(__name__)

# ─── Constantes GameInput ───────────────────────────────────────────────────
# Valeurs correctes du SDK Microsoft GameInput (GameInput.h)
GameInputKindGamepad = 0x00040000  # NB: PAS 0x00000001 — c'est RawDeviceReport
GameInputKindAny     = 0xFFFFFFFF


# ─── Structure native GameInput ───────────────────────────────────────────────
class GameInputRumbleParams(Structure):
    """
    Correspond à GameInputRumbleParams du SDK Microsoft GameInput.

    lowFrequency  → moteur gauche  (lourd, basse fréquence)  — 0.0 à 1.0
    highFrequency → moteur droit   (léger, haute fréquence)  — 0.0 à 1.0
    leftTrigger / rightTrigger → pas de moteur physique sur manette standard,
                                  toujours transmis à 0.0.
    """
    _fields_ = [
        ('lowFrequency',  c_float),
        ('highFrequency', c_float),
        ('leftTrigger',   c_float),
        ('rightTrigger',  c_float),
    ]


# ─── Helper vtable COM ────────────────────────────────────────────────────────
HRESULT = c_int32


def _vtfunc(obj_addr: int, idx: int, restype, *argtypes):
    """
    Extrait et retourne la méthode COM à l'indice `idx` dans la vtable
    de l'objet pointé par `obj_addr` (valeur entière du pointeur COM).

    Principe :
      obj_addr → [vtable_ptr]  (premier champ de tout objet COM)
      vtable_ptr → [fn0, fn1, fn2, ...]
    """
    obj_as_pp = ctypes.cast(obj_addr, POINTER(c_void_p))
    vtable_addr = obj_as_pp[0]                              # déréférencement → vtable
    vtable = ctypes.cast(vtable_addr, POINTER(c_void_p))
    fn_addr = vtable[idx]
    fn_type = WINFUNCTYPE(restype, c_void_p, *argtypes)
    return fn_type(fn_addr)


# ─── Contrôleur ──────────────────────────────────────────────────────────────
class GameInputHapticController(HapticController):
    """
    Retour haptique via Microsoft GameInput (gameinput.dll) — appels COM vtable directs.

    Mapping 4 canaux logiques → 2 moteurs physiques :
      left_low  + left_high  →  lowFrequency  (moteur gauche)
      right_low + right_high →  highFrequency (moteur droit)
    """

    # ── Indices vtable (SDK GDK / GameInput 2024) ─────────────────────────
    # IUnknown
    _VT_RELEASE                 = 2
    # IGameInput
    _VT_GI_GET_CURRENT_READING  = 4
    # IGameInputReading
    _VT_READING_GET_DEVICE      = 6
    # IGameInputDevice
    _VT_DEVICE_SET_RUMBLE       = 10

    def __init__(self, device_index: int = 0, invert_sides: bool = False):
        self.device_index  = device_index
        self.invert_sides  = invert_sides
        self._lock         = threading.Lock()

        # Consignes 4 canaux (0.0 à 1.0)
        self.left_low   = 0.0   # Grave Gauche  (TC / Traction)
        self.left_high  = 0.0   # Aigu Gauche   (ABS / Freinage)
        self.right_low  = 0.0   # Grave Droit   (TC / Traction)
        self.right_high = 0.0   # Aigu Droit    (ABS / Freinage)

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._gi_dll  = None
        self._gi_addr: Optional[int]     = None  # IGameInput*
        self._device_addr: Optional[int] = None  # IGameInputDevice* (ref comptée)

        self._init_gameinput()

    # ── Initialisation ─────────────────────────────────────────────────────

    def _init_gameinput(self):
        try:
            self._gi_dll = ctypes.windll.LoadLibrary("gameinput.dll")

            gi_out = c_void_p()
            hr = self._gi_dll.GameInputCreate(ctypes.byref(gi_out))

            if hr == 0 and gi_out.value:
                self._gi_addr = gi_out.value
                logger.info("GameInput (gameinput.dll) initialisé avec succès.")
            else:
                logger.error(
                    f"GameInputCreate a échoué — HRESULT=0x{hr & 0xFFFFFFFF:08X}"
                )
        except OSError as e:
            logger.error(f"Impossible de charger gameinput.dll : {e}")

        self._start_modulation_thread()

    # ── Acquisition / libération du device ────────────────────────────────

    def _acquire_device(self) -> bool:
        """
        Acquiert IGameInputDevice* depuis la première lecture gamepad disponible.
        Le pointeur est mis en cache dans self._device_addr.
        Retourne True si le device est prêt.
        """
        if self._device_addr:
            return True
        if not self._gi_addr:
            return False

        try:
            reading_out = c_void_p()

            # IGameInput::GetCurrentReading(GameInputKindGamepad, NULL, &reading)
            # GameInputKindGamepad = 0x00040000  (et non 0x00000001 = RawDeviceReport)
            get_reading = _vtfunc(
                self._gi_addr,
                self._VT_GI_GET_CURRENT_READING,
                HRESULT,
                c_uint32,            # inputKind
                c_void_p,            # device (nullable → NULL)
                POINTER(c_void_p),   # reading (out)
            )
            hr = get_reading(
                self._gi_addr, GameInputKindGamepad, None, ctypes.byref(reading_out)
            )

            if hr != 0 or not reading_out.value:
                return False  # manette non connectée ou non disponible

            reading_addr = reading_out.value

            # IGameInputReading::GetDevice(IGameInputDevice**)  → void
            # Signature réelle : void GetDevice(_COM_Outptr_ IGameInputDevice**)
            # Le device retourné a déjà AddRef — on le garde, on libère la lecture.
            device_out = c_void_p()
            get_device = _vtfunc(
                reading_addr,
                self._VT_READING_GET_DEVICE,
                None,              # void (pas de valeur de retour)
                POINTER(c_void_p), # IGameInputDevice** (out)
            )
            get_device(reading_addr, ctypes.byref(device_out))

            # Libère la lecture — on conserve le device séparément
            _vtfunc(reading_addr, self._VT_RELEASE, c_ulong)(reading_addr)

            if device_out.value:
                self._device_addr = device_out.value
                logger.info(f"IGameInputDevice acquis à 0x{self._device_addr:016X}")
                return True

        except Exception as exc:
            logger.debug(f"_acquire_device exception : {exc}")

        return False

    def _release_device(self):
        """Libère la référence COM sur IGameInputDevice*."""
        if self._device_addr:
            try:
                _vtfunc(self._device_addr, self._VT_RELEASE, c_ulong)(self._device_addr)
            except Exception:
                pass
            self._device_addr = None

    # ── Envoi du rumble ────────────────────────────────────────────────────

    def _send_rumble(self, lf: float, hf: float) -> None:
        """
        Envoie les intensités aux deux moteurs via IGameInputDevice::SetRumbleState.

        lf → lowFrequency  (moteur gauche — grave)
        hf → highFrequency (moteur droit  — aigu)
        """
        if not self._acquire_device():
            return

        try:
            params = GameInputRumbleParams(
                lowFrequency=lf,
                highFrequency=hf,
                leftTrigger=0.0,   # pas de moteur physique sur les gâchettes
                rightTrigger=0.0,
            )

            # IGameInputDevice::SetRumbleState(const GameInputRumbleParams*) → void
            set_rumble = _vtfunc(
                self._device_addr,
                self._VT_DEVICE_SET_RUMBLE,
                None,                           # void
                POINTER(GameInputRumbleParams),  # params*
            )
            set_rumble(self._device_addr, ctypes.byref(params))

        except Exception as exc:
            # Device débranché ou vtable invalide → on relâche pour réacquérir
            logger.warning(f"SetRumbleState échoué, device réinitialisé : {exc}")
            self._release_device()

    # ── Thread de modulation ───────────────────────────────────────────────

    def _start_modulation_thread(self):
        self._running = True
        self._thread = threading.Thread(target=self._modulation_loop, daemon=True)
        self._thread.start()

    def _modulation_loop(self):
        """
        Boucle de rendu haptique à 100 Hz.

        Chaque moteur physique (gauche / droit) reçoit un signal ADDITIF
        combinant les deux textures simultanément :

          lowFrequency  (moteur gauche) = l_low  × slow_sine  +  l_high  × fast_pulse
          highFrequency (moteur droit)  = r_low  × slow_sine  +  r_high  × fast_pulse

        slow_sine  : 10 Hz — texture grave (TC, traction, secousses)
        fast_pulse : 80 Hz — texture aiguë (ABS, pulsations de freinage)

        Le mix additif permet aux deux textures de coexister sur le même moteur
        (ex : ABS + glissement latéral simultanés) contrairement à max() qui
        efface la texture dominée.
        """
        start_time = time.time()
        last_lf = last_hf = -1.0

        while self._running:
            t = time.time() - start_time

            with self._lock:
                l_low  = self.left_low
                l_high = self.left_high
                r_low  = self.right_low
                r_high = self.right_high

            # Arrêt immédiat si toutes les consignes sont nulles
            if l_low == 0.0 and l_high == 0.0 and r_low == 0.0 and r_high == 0.0:
                if last_lf != 0.0 or last_hf != 0.0:
                    self._send_rumble(0.0, 0.0)
                    last_lf = last_hf = 0.0
                time.sleep(0.01)
                continue

            # ── Modulateurs de texture ────────────────────────────────────────
            # slow_sine  : onde 10 Hz, toujours positive (0.0 → 1.0)
            slow_sine  = max(0.0, 0.3 + 0.7 * math.sin(2.0 * math.pi * 10.0 * t))
            # fast_pulse : créneau 80 Hz (rapport cyclique 50 %)
            fast_pulse = 1.0 if (int(t * 80) % 2 == 0) else 0.3

            right_out = min(1.0, r_low * slow_sine + r_high * fast_pulse)  # → moteur droit
            left_out  = min(1.0, l_low * slow_sine + l_high * fast_pulse)  # → moteur gauche

            if self.invert_sides:
                left_out, right_out = right_out, left_out

            self._send_rumble(max(0.0, left_out), max(0.0, right_out))
            last_lf, last_hf = left_out, right_out

            time.sleep(0.01)  # 100 Hz

    # ── Interface publique ─────────────────────────────────────────────────

    def set_vibration(
        self,
        left_low:   float = 0.0,
        left_high:  float = 0.0,
        right_low:  float = 0.0,
        right_high: float = 0.0,
        duration_ms: int  = 0,
    ) -> None:
        with self._lock:
            self.left_low   = max(0.0, min(1.0, float(left_low)))
            self.left_high  = max(0.0, min(1.0, float(left_high)))
            self.right_low  = max(0.0, min(1.0, float(right_low)))
            self.right_high = max(0.0, min(1.0, float(right_high)))

    def stop(self) -> None:
        self.set_vibration(0.0, 0.0, 0.0, 0.0)
        self._send_rumble(0.0, 0.0)

    def close(self):
        self._running = False
        self.stop()
        self._release_device()
        if self._gi_addr:
            try:
                _vtfunc(self._gi_addr, self._VT_RELEASE, c_ulong)(self._gi_addr)
            except Exception:
                pass
            self._gi_addr = None
