from pathlib import Path
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.history import HistoryStore


def fake_features(packet_id=1):
    return {
        "packet_id": packet_id, "scenario": "AUTO_WEAR", "source_mode": "RECORDED_DATA_SIMULATION",
        "sample_rate_hz": 512, "sample_count": 512, "vibration_rms": 1.0, "vibration_peak": 2.0,
        "vibration_energy": 1.0, "force_resultant_rms": 10.0, "sound_rms": 1.0, "sound_peak": 2.0,
        "sound_energy": 1.0, "fx_rms": 1.0, "fy_rms": 1.0, "fz_rms": 1.0, "mz_rms": 1.0,
        "fx_std": 1.0, "fy_std": 1.0, "fz_std": 1.0, "missing_ratio": 0.0,
    }


def fake_decision():
    return {
        "wear_index": 1.0, "tool_health": 99.0, "sensor_integrity": 100.0, "wear_level": "정상",
        "state": "NORMAL", "machine_state": "RUN", "action": "CONTINUE", "confidence": 95.0,
        "rul_text": "충분", "rul_low": 10, "rul_high": 20, "fault_sensor": None,
        "manual_confirmed": False, "reasons": [], "manual_guidance": [], "agent_trace": [],
    }


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as td:
        store = HistoryStore(Path(td) / "history.db")
        tool = "T-2026-001"
        store.add_observation(tool, fake_features(1), fake_decision(), session_id="S-OLD")
        store.add_event(tool, "SYSTEM", "old", session_id="S-OLD")
        store.add_observation(tool, fake_features(1), fake_decision(), session_id="S-NEW")
        assert len(store.observations(tool, session_id="S-NEW")) == 1
        assert len(store.observations(tool)) == 2
        assert len(store.events(tool, session_id="S-NEW")) == 0
        assert len(store.events(tool, session_id="S-OLD")) == 1
        print("SESSION HISTORY PRESERVATION: OK")
