"""
Unit & Integration Tests for isimotor_rawudp_client domain models, binary packet decoders,
LMUParser, UDPServer, VehicleSensors, DeltaEngine, and EngineerContext.
"""

import time
import pytest
from simpulse.core.telemetry.sensors import VehicleSensors
from simpulse.core.telemetry.lmu_parser import LMUParser, TelemetryData
from simpulse.core.telemetry.delta_engine import DeltaEngine
from simpulse.core.telemetry.udp_server import UDPServer
from simpulse.builtin_plugins.race_engineer.context import EngineerContext

from isimotor_rawudp_client import (
    TelemInfo,
    TelemWheel,
    TelemVect3,
    CompactScoring,
    FullScoringSession,
    VehicleScoring,
    SystemEvent,
    ExtendedState,
    HWControlCommand,
    WeatherControlCommand,
)


def _create_mock_telem_wheel(
    lpv: float = 20.0,
    lgv: float = 20.0,
    lat_pv: float = 0.5,
    lat_gv: float = 0.5,
    susp_deflection: float = 0.05,
) -> TelemWheel:
    return TelemWheel(
        suspension_deflection=susp_deflection,
        ride_height=0.04,
        susp_force=1000.0,
        brake_temp=300.0,
        brake_pressure=0.5,
        rotation=60.0,
        lateral_patch_vel=lat_pv,
        longitudinal_patch_vel=lpv,
        lateral_ground_vel=lat_gv,
        longitudinal_ground_vel=lgv,
        camber=0.0,
        lateral_force=200.0,
        longitudinal_force=300.0,
        tire_load=2500.0,
        grip_fraction=0.98,
        pressure=180.0,
        temperature=(70.0, 75.0, 72.0),
        wear=0.01,
        surface_type=1,
        flat=False,
        detached=False,
    )


def _create_mock_telem_info(speed_mps: float = 50.0, fuel: float = 45.0, slot_id: int = 1) -> TelemInfo:
    wheels = tuple(_create_mock_telem_wheel() for _ in range(4))
    return TelemInfo(
        slot_id=slot_id,
        delta_time=0.01,
        lap_number=3,
        lap_start_et=100.0,
        vehicle_name="Porsche 963 #5",
        track_name="Le Mans",
        pos=TelemVect3(100.0, 10.0, 200.0),
        local_vel=TelemVect3(0.0, 0.0, -speed_mps),
        local_accel=TelemVect3(0.0, 0.0, 2.0),
        ori=(TelemVect3(1.0, 0.0, 0.0), TelemVect3(0.0, 1.0, 0.0), TelemVect3(0.0, 0.0, 1.0)),
        local_rot=TelemVect3(0.0, 0.0, 0.0),
        local_rot_accel=TelemVect3(0.0, 0.0, 0.0),
        gear=4,
        engine_rpm=6500.0,
        engine_water_temp=85.0,
        engine_oil_temp=95.0,
        clutch_rpm=6500.0,
        unfiltered_throttle=0.85,
        unfiltered_brake=0.0,
        filtered_throttle=0.85,
        filtered_brake=0.0,
        unfiltered_steering=0.02,
        unfiltered_clutch=0.0,
        steering_shaft_torque=15.0,
        fuel=fuel,
        engine_max_rpm=8200.0,
        scheduled_stops=1,
        overheating=False,
        detached=False,
        headlights=True,
        front_downforce=120.0,
        rear_downforce=180.0,
        fuel_capacity=90.0,
        current_sector=1,
        speed_limiter=0,
        max_gears=6,
        front_tire_compound_index=0,
        rear_tire_compound_index=0,
        front_tire_compound_name="Medium",
        rear_tire_compound_name="Medium",
        rear_brake_bias=0.48,
        wheels=wheels,
    )


def _create_mock_compact_scoring() -> CompactScoring:
    return CompactScoring(
        track_name="Spa Francorchamps",
        lap_dist=7004.0,
        current_et=250.0,
        session=10,
        total_laps=5,
        sector=2,
        in_garage_stall=False,
        in_realtime=True,
        count_lap_flag=2,
        cur_sector1=38.450,
        cur_sector2=85.200,
        last_sector1=38.300,
        last_sector2=84.900,
        last_lap_time=132.500,
        best_sector1=38.100,
        best_sector2=84.500,
        best_lap_time=131.900,
        max_laps=25,
    )


def _create_mock_full_scoring() -> FullScoringSession:
    player = VehicleScoring(
        id=1,
        driver_name="Player Driver",
        vehicle_name="Toyota GR010",
        total_laps=8,
        sector=2,
        finish_status=0,
        lap_dist=3200.0,
        path_lateral=0.0,
        track_edge=6.0,
        best_lap_time=130.500,
        last_lap_time=131.200,
        cur_sector1=37.900,
        cur_sector2=83.800,
        last_sector1=38.000,
        last_sector2=84.100,
        best_sector1=37.800,
        best_sector2=83.500,
        is_player=True,
        control=0,
        in_pits=False,
        place=1,
        vehicle_class="Hypercar",
        time_behind_next=0.0,
        laps_behind_next=0,
        time_behind_leader=0.0,
        laps_behind_leader=0,
        num_pitstops=0,
        in_garage_stall=False,
        count_lap_flag=2,
        pit_state=0,
        pos=TelemVect3(100.0, 0.0, 200.0),
        local_vel=TelemVect3(0.0, 0.0, -72.5),
        lap_start_et=200.0,
    )
    opponent = VehicleScoring(
        id=2,
        driver_name="Opponent Driver",
        vehicle_name="Porsche 963",
        total_laps=8,
        sector=2,
        finish_status=0,
        lap_dist=3100.0,
        path_lateral=0.0,
        track_edge=6.0,
        best_lap_time=131.000,
        last_lap_time=131.500,
        cur_sector1=38.200,
        cur_sector2=84.200,
        last_sector1=38.100,
        last_sector2=84.000,
        best_sector1=38.000,
        best_sector2=83.900,
        is_player=False,
        control=1,
        in_pits=False,
        place=2,
        vehicle_class="Hypercar",
        time_behind_next=1.2,
        laps_behind_next=0,
        time_behind_leader=1.2,
        laps_behind_leader=0,
        num_pitstops=0,
        in_garage_stall=False,
        count_lap_flag=2,
        pit_state=0,
        pos=TelemVect3(100.0, 0.0, 100.0),
        local_vel=TelemVect3(0.0, 0.0, -71.8),
        lap_start_et=201.2,
    )
    return FullScoringSession(
        track_name="Spa Francorchamps",
        lap_dist=7004.0,
        current_et=331.2,
        session=10,
        max_laps=25,
        num_vehicles=2,
        in_realtime=True,
        vehicles=[player, opponent],
    )


def test_vehicle_sensors_from_telem_info():
    """Vérifie la conversion directe TelemInfo -> VehicleSensors avec grip et glissement."""
    telem = _create_mock_telem_info(speed_mps=55.0, fuel=42.5)
    scoring = _create_mock_compact_scoring()

    sensors = VehicleSensors.from_telem_info(telem, scoring=scoring)
    assert sensors is not None
    assert sensors.engine_rpm == 6500.0
    assert sensors.engine_max_rpm == 8200.0
    assert sensors.gear == 4
    assert sensors.unfiltered_throttle == 0.85
    assert sensors.fuel_level == 42.5
    assert sensors.remaining_laps == 20  # 25 - 5
    assert sensors.explicit_aero_load > 0.0
    # Vérification grip fraction natif du modèle pneu
    assert sensors.front_left_grip == 0.98
    assert sensors.grip_intensity == 0.98


def test_vehicle_sensors_abs_lockup_calculation():
    """Vérifie le calcul sans dimension du glissement ABS au freinage (lpv - lgv) / speed."""
    # Simulation d'un freinage violent : vitesse 50 m/s, roue avant gauche à 35 m/s (30% glissement / blocage complet)
    from isimotor_rawudp_client import TelemWheel
    w_fl = TelemWheel(longitudinal_patch_vel=35.0, longitudinal_ground_vel=50.0, grip_fraction=0.70)
    w_fr = TelemWheel(longitudinal_patch_vel=50.0, longitudinal_ground_vel=50.0, grip_fraction=0.95)
    w_rl = TelemWheel(longitudinal_patch_vel=50.0, longitudinal_ground_vel=50.0, grip_fraction=0.98)
    w_rr = TelemWheel(longitudinal_patch_vel=50.0, longitudinal_ground_vel=50.0, grip_fraction=0.98)

    telem = _create_mock_telem_info(speed_mps=50.0)
    telem.unfiltered_brake = 1.0
    telem.wheels = (w_fl, w_fr, w_rl, w_rr)

    sensors = VehicleSensors.from_telem_info(telem)
    # Glissement FL brut = (50 - 35) / 50 = 0.30 -> Échelle calibrée: saturation à 0.18 -> lockup saturé à 1.0
    assert sensors.front_left_lock == 1.0
    assert sensors.front_right_lock == 0.0
    assert sensors.lock_intensity == 1.0
    assert sensors.lock_left == 1.0
    assert sensors.lock_right == 0.0
    # Grip natif
    assert sensors.front_left_grip == 0.70
    assert sensors.front_right_grip == 0.95
    assert sensors.grip_left == 0.70


def test_vehicle_sensors_abs_trail_braking_micro_lockup():
    """Vérifie la sensibilité accrue au micro-blocage lors du trail braking (glissement 10%)."""
    from isimotor_rawudp_client import TelemWheel
    w_fl = TelemWheel(longitudinal_patch_vel=45.0, longitudinal_ground_vel=50.0, grip_fraction=0.85)
    w_fr = TelemWheel(longitudinal_patch_vel=50.0, longitudinal_ground_vel=50.0, grip_fraction=0.98)
    w_rl = TelemWheel(longitudinal_patch_vel=50.0, longitudinal_ground_vel=50.0, grip_fraction=0.98)
    w_rr = TelemWheel(longitudinal_patch_vel=50.0, longitudinal_ground_vel=50.0, grip_fraction=0.98)

    telem = _create_mock_telem_info(speed_mps=50.0)
    telem.unfiltered_brake = 0.80
    telem.wheels = (w_fl, w_fr, w_rl, w_rr)

    sensors = VehicleSensors.from_telem_info(telem)
    # Glissement FL brut = (50 - 45) / 50 = 0.10 -> (0.10 - 0.04) / (0.18 - 0.04) = 0.06 / 0.14 ≈ 0.428
    expected = (0.10 - 0.04) / (0.18 - 0.04)
    assert sensors.front_left_lock == pytest.approx(expected, abs=0.01)
    assert sensors.lock_intensity == pytest.approx(expected, abs=0.01)


def test_vehicle_sensors_ecu_abs_and_tc_intervention():
    """Vérifie la détection et le calcul d'intensité des aides électroniques ABS et TC officielles de la voiture."""
    # 1. ABS fallback intervention (legacy / sans extension ECU) :
    # Pédale frein pilote 1.0 (100%), pression régulée par le boîtier ABS = 0.60 (60%)
    telem = _create_mock_telem_info(speed_mps=45.0)
    telem.lmu = None  # Simule une ancienne télémétrie sans extension ECU
    telem.unfiltered_brake = 1.0
    telem.filtered_brake = 0.60
    telem.unfiltered_throttle = 0.0
    telem.filtered_throttle = 0.0

    sensors = VehicleSensors.from_telem_info(telem)
    # Intervention ABS = (1.0 - 0.60) / 1.0 = 0.40 (40%)
    assert sensors.ecu_abs_active == pytest.approx(0.40, abs=0.01)
    assert sensors.ecu_tc_active == 0.0

    # 2. TC intervention sans ECU (fallback coupure papillon 70%) :
    telem.unfiltered_brake = 0.0
    telem.filtered_brake = 0.0
    telem.unfiltered_throttle = 1.0
    telem.filtered_throttle = 0.30
    telem.gear = 2
    telem.engine_rpm = 5000.0
    telem.engine_max_rpm = 7500.0

    sensors_tc = VehicleSensors.from_telem_info(telem)
    assert sensors_tc.ecu_tc_active == pytest.approx(0.70, abs=0.01)
    assert sensors_tc.ecu_abs_active == 0.0


def test_vehicle_sensors_native_ecu_state_v020():
    """Vérifie la détection directe via EcuState de isimotor_rawudp_client v0.2.0."""
    from isimotor_rawudp_client.models.ecu import EcuState
    from isimotor_rawudp_client.models.lmu import LMUTelemetryExtension

    telem = _create_mock_telem_info(speed_mps=50.0)
    telem.unfiltered_brake = 1.0
    telem.filtered_brake = 1.0  # Dans LMU, filtered_brake reste à 1.0
    telem.unfiltered_throttle = 1.0
    telem.filtered_throttle = 1.0

    # Attache l'extension native LMU ECU
    ecu = EcuState(
        abs_active=True,
        tc_active=True,
        abs_level=5,
        abs_max=12,
        tc_level=3,
        tc_max=10,
        tc_cut=2,
        tc_slip=4,
        motor_map=1,
        motor_map_max=5,
        brake_migration=3,
        front_arb=2,
        rear_arb=4,
    )
    telem.lmu = LMUTelemetryExtension(ecu=ecu)

    sensors = VehicleSensors.from_telem_info(telem)
    assert sensors.ecu_abs_active == 1.0
    assert sensors.ecu_tc_active == 1.0
    assert sensors.ecu_abs_level == 5
    assert sensors.ecu_abs_max == 12
    assert sensors.ecu_tc_level == 3
    assert sensors.ecu_tc_max == 10
    assert sensors.ecu_tc_cut == 2
    assert sensors.ecu_tc_slip == 4
    assert sensors.ecu_motor_map == 1
    assert sensors.ecu_brake_migration == 3
    assert sensors.ecu_front_arb == 2
    assert sensors.ecu_rear_arb == 4


def test_lmu_parser_process_telemetry():
    """Vérifie le traitement d'une trame TelemInfo par LMUParser."""
    telem = _create_mock_telem_info(speed_mps=60.0, fuel=50.0)
    snap = LMUParser.process_telemetry(telem)

    assert snap is not None
    assert snap.engine_rpm == 6500.0
    assert snap.gear == 4
    assert snap.fuel == 50.0
    assert snap.raw_telemetry is telem
    assert LMUParser.get_latest_telemetry_info() is telem


def test_lmu_parser_process_compact_scoring():
    """Vérifie le traitement d'un paquet CompactScoring par LMUParser."""
    scoring = _create_mock_compact_scoring()
    snap = LMUParser.process_compact_scoring(scoring)

    assert snap is not None
    assert snap.total_laps == 25
    assert snap.laps_completed == 5
    assert snap.in_realtime is True
    assert LMUParser.get_latest_compact_scoring() is scoring


def test_lmu_parser_process_full_scoring():
    """Vérifie le traitement d'une session FullScoringSession multi-voitures."""
    session = _create_mock_full_scoring()
    snap = LMUParser.process_full_scoring(session)

    assert snap is not None
    assert snap.total_laps == 25
    assert snap.laps_completed == 8
    assert snap.in_realtime is True
    assert LMUParser.get_latest_full_scoring() is session
    assert LMUParser.get_latest_scoring() is session


def test_lmu_parser_system_events():
    """Vérifie la mise à jour de l'état temps-réel via SystemEvent."""
    enter_event = SystemEvent(event_id=1)  # Enter realtime
    snap = LMUParser.process_system_event(enter_event)
    assert snap.in_realtime is True

    exit_event = SystemEvent(event_id=2)  # Exit realtime
    snap_exit = LMUParser.process_system_event(exit_event)
    assert snap_exit.in_realtime is False


def test_delta_engine_with_sdk_models():
    """Vérifie les mises à jour DeltaEngine avec TelemInfo et FullScoringSession."""
    delta_eng = DeltaEngine()
    session = _create_mock_full_scoring()
    delta_eng.update_scoring(session)

    assert delta_eng.track_name == "Spa Francorchamps"
    assert delta_eng.track_length == 7004.0

    telem = _create_mock_telem_info(speed_mps=65.0)
    delta_eng.update_physics(telem)
    assert delta_eng._last_speed_ms == telem.speed_mps


def test_engineer_context_with_sdk_models():
    """Vérifie toutes les requêtes EngineerContext avec des modèles typés."""
    session = _create_mock_full_scoring()
    telem = _create_mock_telem_info(speed_mps=72.5)

    ctx = EngineerContext(telemetry=telem, scoring=session)
    assert ctx.get_session_type() == 10
    assert ctx.get_track_name() == "Spa Francorchamps"
    assert ctx.get_track_length() == 7004.0

    player = ctx.get_player_vehicle()
    assert player is not None
    assert player.driver_name == "Player Driver"
    assert ctx.is_player_in_pits() is False
    assert ctx.is_player_in_garage() is False

    opponents = ctx.get_track_opponents()
    assert len(opponents) == 1
    assert opponents[0].driver_name == "Opponent Driver"

    speed = ctx.get_player_speed_mps()
    assert speed == 72.5

    dist_behind = ctx.compute_distance_behind(player, opponents[0])
    assert dist_behind == pytest.approx(100.0, 0.1)

    euc_dist = ctx.compute_euclidean_distance(player, opponents[0])
    assert euc_dist == pytest.approx(100.0, 0.1)


def test_udp_server_lifecycle_and_controls():
    """Vérifie le cycle de vie de UDPServer et ses méthodes de contrôle."""
    server = UDPServer(host="127.0.0.1", port=15888, target_port=15889)
    assert server.is_running is False

    server.start()
    assert server.is_running is True
    assert server.client is not None

    # Test transmission de commandes (pas de crash / signature valide)
    hw_cmd = HWControlCommand(control_name="Throttle", control_value=1.0)
    server.send_hw_control(hw_cmd)

    weather_cmd = WeatherControlCommand(ambient_temp=22.0)
    server.send_weather_override(weather_cmd)

    server.send_unfreeze_physics()
    server.send_pit_lane_speed_limit(True)
    server.send_tc_override(3)
    server.send_abs_override(2)

    server.stop()
    assert server.is_running is False


def test_lmu_parser_binary_simp_packet_decode():
    """Vérifie le décodage binaire d'un paquet SIMP via LMUParser.parse."""
    from isimotor_rawudp_client.constants import PKT_TYPE_SYSTEM_EVENT
    from isimotor_rawudp_client.decoder.header import encode_header

    hdr = encode_header(packet_type=PKT_TYPE_SYSTEM_EVENT, payload_size=6)
    payload = bytes([1, 0, 0, 0, 0, 0])  # event_id=1 (EnterRealtime)
    data = hdr + payload

    snap = LMUParser.parse(data)
    assert snap is not None
    assert snap.in_realtime is True


def test_udp_server_binary_simp_socket_transfer():
    """Vérifie la réception réseau UDP d'un paquet binaire SIMP par UDPServer."""
    from isimotor_rawudp_client.constants import PKT_TYPE_SYSTEM_EVENT
    from isimotor_rawudp_client.decoder.header import encode_header
    import socket

    port = 17992
    server = UDPServer(host="127.0.0.1", port=port)
    server.start()
    time.sleep(0.05)

    hdr = encode_header(packet_type=PKT_TYPE_SYSTEM_EVENT, payload_size=6)
    payload = bytes([1, 0, 0, 0, 0, 0])  # event_id=1 (EnterRealtime)
    data = hdr + payload

    client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_sock.sendto(data, ("127.0.0.1", port))
    client_sock.close()

    time.sleep(0.08)
    assert server.is_receiving() is True
    snap = server.get_latest_data()
    assert snap is not None
    server.stop()


def test_lmu_parser_auto_realtime_recovery():
    """Vérifie que la télémétrie de roulage active rétablit automatiquement in_realtime=True même après un événement garage."""
    from isimotor_rawudp_client import SystemEvent

    # Sortie vers les menus / garage
    LMUParser.process_system_event(SystemEvent(event_id=2))
    assert LMUParser._last_in_realtime is False

    # Arrivée de télémétrie de roulage active (vitesse 40 m/s, rapport 3, accélérateur 0.8)
    telem = _create_mock_telem_info(speed_mps=40.0)
    snap = LMUParser.process_telemetry(telem)

    assert snap.in_realtime is True
    sensors = snap.to_sensors()
    assert sensors.in_realtime is True


def test_garage_stall_preserves_inactive_realtime():
    """Vérifie que le statut garage reste inactif (in_realtime=False) même si la voiture a un rapport engagé (gear=1) à l'arrêt."""
    from isimotor_rawudp_client import CompactScoring

    # Détection de box / garage stall
    scoring = CompactScoring(
        in_realtime=True,
        in_garage_stall=True,
        sector=1,
        total_laps=5,
    )
    snap_sc = LMUParser.process_compact_scoring(scoring)
    assert snap_sc.in_realtime is False
    assert LMUParser._in_garage_trap is True

    # Réception d'un paquet TelemInfo dans le garage (vitesse 0, boîte en 1ère vitesse, gaz au repos)
    telem_garage = _create_mock_telem_info(speed_mps=0.0)
    snap_telem = LMUParser.process_telemetry(telem_garage)

    assert snap_telem.in_realtime is False
    sensors = snap_telem.to_sensors()
    assert sensors.in_realtime is False


def test_multicar_opponent_telemetry_isolation():
    """Vérifie que les trames TelemInfo des véhicules adverses sont strictement ignorées dans une session multi-voitures."""
    from isimotor_rawudp_client import FullScoringSession, VehicleScoring

    veh_player = VehicleScoring(
        id=3,
        driver_name="Player Driver",
        vehicle_name="Porsche 963 #5",
        is_player=True,
        control=0,
    )
    veh_opponent = VehicleScoring(
        id=7,
        driver_name="AI Opponent",
        vehicle_name="Ferrari 499P #50",
        is_player=False,
        control=1,
    )
    session = FullScoringSession(
        track_name="Spa",
        vehicles=[veh_player, veh_opponent],
    )
    LMUParser.process_full_scoring(session)

    # 1. Réception de la télémétrie d'un adversaire au garage (slot_id=7, frein=100%, vitesse=0)
    telem_opp = _create_mock_telem_info(speed_mps=0.0, slot_id=7)
    telem_opp.unfiltered_brake = 1.0
    snap_opp = LMUParser.process_telemetry(telem_opp)
    assert snap_opp is None  # Rejeté !

    # 2. Réception de la télémétrie du joueur en piste (slot_id=3, vitesse=60 m/s, gaz=80%)
    telem_player = _create_mock_telem_info(speed_mps=60.0, slot_id=3)
    telem_player.unfiltered_throttle = 0.8
    snap_player = LMUParser.process_telemetry(telem_player)
    assert snap_player is not None  # Accepté !
    assert snap_player.unfiltered_throttle == 0.8




