"""
Unit & Integration Tests for SimPad Official LMU Schedule Engine & Setups <Niveau><Classes><Circuit>.
"""

import time
import datetime
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.schedule import (
    RaceSetupConfig,
    RaceTierConfig,
    RaceEvent,
    LMUScheduleManager,
    LMUScheduleClient,
    DEFAULT_RACE_SETUPS,
    clean_series_key,
    make_setup_key,
)
from src.utils.audio import AudioAnnouncer


class TestRaceSetupConfig:
    def test_make_setup_key(self):
        key = make_setup_key("Beginner", "GT3", "Fuji (WEC)")
        assert "beginner" in key
        assert "gt3" in key
        assert "fuji" in key

    def test_display_title_format(self):
        cfg = RaceSetupConfig(
            setup_id="lmgt3_fixed",
            difficulty="Beginner",
            car_classes="GT3",
            circuit="Fuji (WEC)",
            series_name="LMGT3 Fixed",
        )
        assert cfg.display_title == "[Beginner] GT3 @ Fuji (WEC)"
        assert cfg.name == "LMGT3 Fixed"

    def test_default_setups_exist(self):
        assert "lmgt3_fixed" in DEFAULT_RACE_SETUPS
        assert "elms_sprint_trophy" in DEFAULT_RACE_SETUPS
        assert "wec_weekly" in DEFAULT_RACE_SETUPS

    def test_serialization_roundtrip(self):
        cfg = RaceSetupConfig(
            setup_id="lmgt3_fixed",
            difficulty="Beginner",
            car_classes="GT3",
            circuit="Fuji (WEC)",
            series_name="LMGT3 Fixed",
            enabled=True,
            notify_15m=False,
            notify_5m=True,
        )
        data = cfg.to_dict()
        assert data["setup_id"] == "lmgt3_fixed"
        assert data["notify_15m"] is False

        restored = RaceSetupConfig.from_dict(data)
        assert restored.setup_id == "lmgt3_fixed"
        assert restored.notify_15m is False
        assert restored.display_title == "[Beginner] GT3 @ Fuji (WEC)"


class TestAudioAnnouncerFIFOQueue:
    def test_queue_enqueue_and_clear(self):
        AudioAnnouncer.clear_queue()
        assert AudioAnnouncer.get_queue_size() == 0

        AudioAnnouncer.play_phrase("clean_lap")
        AudioAnnouncer.play_phrase("dirty_lap")
        AudioAnnouncer.play_phrase("car")

        AudioAnnouncer.clear_queue()
        assert AudioAnnouncer.get_queue_size() == 0

    @patch.object(AudioAnnouncer, "_play_wav_sync", return_value=True)
    def test_queue_sequential_processing(self, mock_play_sync):
        AudioAnnouncer.clear_queue()
        AudioAnnouncer._is_muted = False

        seq = ["lmgt3_fixed", "five_minutes", "registration_open"]
        AudioAnnouncer.play_sequence(seq, interrupt=False)

        for _ in range(30):
            if mock_play_sync.call_count >= 1:
                break
            time.sleep(0.05)

        assert mock_play_sync.call_count >= 1

    def test_interrupt_clears_queue(self):
        AudioAnnouncer.clear_queue()
        AudioAnnouncer.play_phrase("clean_lap")
        AudioAnnouncer.play_phrase("dirty_lap")

        AudioAnnouncer.play_phrase("alongside", interrupt=True)
        assert AudioAnnouncer.get_queue_size() <= 1

    @patch.object(AudioAnnouncer, "play_sequence")
    def test_play_series_and_race_alert_helpers(self, mock_seq):
        AudioAnnouncer.play_race_alert("lmgt3_fixed", 5)
        mock_seq.assert_called_with(["lmgt3_fixed", "five_minutes"], interrupt=False)

        AudioAnnouncer.play_race_alert("wec_weekly", 15)
        mock_seq.assert_called_with(["wec_weekly", "fifteen_minutes"], interrupt=False)


class TestLMUScheduleManagerSetups:
    def test_all_setups_loaded_from_cache(self, tmp_path):
        cfg_file = tmp_path / "test_sched.json"
        cache_file = tmp_path / "test_cache.json"

        mock_series_data = [
            {
                "raceType": "Daily Races",
                "series": "LMGT3 Fixed",
                "difficulty": "Beginner",
                "circuit": "Fuji (WEC)",
                "carClasses": ["GT3"],
                "setup": "fixed",
                "raceLength": 20,
                "times": ["2026-08-27T14:00:00.000Z", "2026-08-27T14:45:00.000Z"]
            },
            {
                "raceType": "Daily Races",
                "series": "ELMS Sprint Trophy",
                "difficulty": "Intermediate",
                "circuit": "Silverstone (ELMS)",
                "carClasses": ["LMP2", "GT3"],
                "setup": "open",
                "raceLength": 30,
                "times": ["2026-08-27T14:10:00.000Z", "2026-08-27T15:10:00.000Z"]
            },
        ]
        LMUScheduleClient.save_cached_schedule(mock_series_data, cache_file)

        mgr = LMUScheduleManager(config_file=cfg_file, cache_file=cache_file, auto_fetch=False)

        assert "lmgt3_fixed" in mgr.setups
        assert "elms_sprint_trophy" in mgr.setups
        assert mgr.setups["lmgt3_fixed"].display_title == "[Beginner] GT3 @ Fuji (WEC)"

        # Verify enabling / disabling setups
        mgr.enable_all_races(False)
        assert all(not s.enabled for s in mgr.setups.values())

        mgr.enable_all_races(True)
        assert all(s.enabled for s in mgr.setups.values())

    def test_setup_events_and_countdown(self, tmp_path):
        cfg_file = tmp_path / "test_sched.json"
        cache_file = tmp_path / "test_cache.json"

        mock_data = [{
            "raceType": "Daily Races",
            "series": "LMGT3 Fixed",
            "difficulty": "Beginner",
            "circuit": "Fuji (WEC)",
            "carClasses": ["GT3"],
            "setup": "fixed",
            "raceLength": 20,
            "times": ["2026-08-27T14:00:00.000Z", "2026-08-27T14:45:00.000Z"]
        }]
        LMUScheduleClient.save_cached_schedule(mock_data, cache_file)

        mgr = LMUScheduleManager(config_file=cfg_file, cache_file=cache_file, auto_fetch=False)

        ref_dt = datetime.datetime(2026, 8, 27, 14, 0, 0, tzinfo=datetime.timezone.utc)
        ref_ts = ref_dt.timestamp()

        # In progress
        ev_in_prog = mgr.get_next_event("lmgt3_fixed", now=ref_ts + 300)
        assert ev_in_prog is not None
        assert ev_in_prog.status == "IN_PROGRESS"
        assert ev_in_prog.car_classes == "GT3"
        assert ev_in_prog.track_name == "Fuji (WEC)"

        # Upcoming
        ev_upcoming = mgr.get_next_event("lmgt3_fixed", now=ref_ts + 1500)
        assert ev_upcoming is not None
        assert ev_upcoming.status == "UPCOMING"

    @patch.object(AudioAnnouncer, "play_sequence")
    def test_setup_alert_triggering_with_fifo_queue(self, mock_seq, tmp_path):
        cfg_file = tmp_path / "test_sched.json"
        cache_file = tmp_path / "test_cache.json"

        mock_data = [{
            "raceType": "Daily Races",
            "series": "LMGT3 Fixed",
            "difficulty": "Beginner",
            "circuit": "Fuji (WEC)",
            "carClasses": ["GT3"],
            "setup": "fixed",
            "raceLength": 20,
            "times": ["2026-08-27T16:00:00.000Z"]
        }]
        LMUScheduleClient.save_cached_schedule(mock_data, cache_file)

        mgr = LMUScheduleManager(config_file=cfg_file, cache_file=cache_file, auto_fetch=False)
        mgr.setups["lmgt3_fixed"].enabled = True
        mgr.setups["lmgt3_fixed"].notify_15m = True
        mgr.setups["lmgt3_fixed"].notify_5m = True

        event = mgr.get_next_event("lmgt3_fixed", now=datetime.datetime(2026, 8, 27, 15, 0, 0, tzinfo=datetime.timezone.utc).timestamp())
        assert event is not None

        # T-15 min
        t_15m = event.start_time - (15 * 60)
        alerts = mgr.update(now=t_15m)
        assert len(alerts) >= 1
        assert any(a["alert_type"] == "15m" and a["setup_id"] == "lmgt3_fixed" for a in alerts)
        mock_seq.assert_any_call(["lmgt3_fixed", "fifteen_minutes"], interrupt=False)

        # No duplicate on next second
        mock_seq.reset_mock()
        alerts_dup = mgr.update(now=t_15m + 1)
        assert len(alerts_dup) == 0
        mock_seq.assert_not_called()

        # T-5 min
        t_5m = event.start_time - (5 * 60)
        alerts_5m = mgr.update(now=t_5m)
        assert any(a["alert_type"] == "5m" and a["setup_id"] == "lmgt3_fixed" for a in alerts_5m)
        mock_seq.assert_any_call(["lmgt3_fixed", "five_minutes"], interrupt=False)

    @patch.object(AudioAnnouncer, "play_sequence")
    def test_disabled_setup_prevents_alert(self, mock_seq, tmp_path):
        cfg_file = tmp_path / "test_sched.json"
        cache_file = tmp_path / "test_cache.json"

        mock_data = [{
            "raceType": "Daily Races",
            "series": "LMGT3 Fixed",
            "difficulty": "Beginner",
            "circuit": "Fuji (WEC)",
            "carClasses": ["GT3"],
            "setup": "fixed",
            "raceLength": 20,
            "times": ["2026-08-27T16:00:00.000Z"]
        }]
        LMUScheduleClient.save_cached_schedule(mock_data, cache_file)

        mgr = LMUScheduleManager(config_file=cfg_file, cache_file=cache_file, auto_fetch=False)
        mgr.setups["lmgt3_fixed"].enabled = False

        event = mgr.get_next_event("lmgt3_fixed", now=datetime.datetime(2026, 8, 27, 15, 0, 0, tzinfo=datetime.timezone.utc).timestamp())
        t_10m = event.start_time - (10 * 60)

        alerts = mgr.update(now=t_10m)
        assert len(alerts) == 0
        mock_seq.assert_not_called()

    def test_save_and_load_setups_persistence(self, tmp_path):
        cfg_file = tmp_path / "custom_setups_schedule.json"
        mgr = LMUScheduleManager(config_file=cfg_file, auto_fetch=False)

        mgr.master_enabled = False
        mgr.setups["lmgt3_fixed"].notify_1m = False
        mgr.setups["lmgt3_fixed"].enabled = False
        mgr.save_config()

        assert cfg_file.exists()

        mgr2 = LMUScheduleManager(config_file=cfg_file, auto_fetch=False)
        assert mgr2.master_enabled is False
        assert mgr2.setups["lmgt3_fixed"].notify_1m is False
        assert mgr2.setups["lmgt3_fixed"].enabled is False
