from pathlib import Path
from tempfile import TemporaryDirectory
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import web_runtime


def run():
    with TemporaryDirectory() as td:
        web_runtime.DB_PATH = Path(td) / "test.db"
        rt = web_runtime.ToolWearWebRuntime()
        assert rt.display_tool_id == "T-2026-001"

        rt.start()
        for _ in range(4):
            rt.tick()
        wear = rt.sim.latent_wear
        old_tool = rt.tool_id
        old_obs = len(rt.store.observations(old_tool))
        rt.reset_session()
        assert rt.display_tool_id == "T-2026-001"
        assert abs(rt.sim.latent_wear - wear) < 1e-9
        assert len(rt.store.observations(old_tool)) == old_obs

        rt.full_reset()
        assert rt.run_id == "RUN-002"
        assert rt.display_tool_id == "T-2026-001"
        assert len(rt.store.observations(old_tool)) == old_obs

        # A selected fault must appear after its delay, but machining must continue.
        rt.set_faults(["VIBRATION"])
        rt.start()
        fault_seen = False
        wear_before_fault = None
        wear_after_fault = None
        for _ in range(35):
            snap = rt.tick()
            if snap["decision"].get("state") == "SENSOR_FAULT":
                if not fault_seen:
                    wear_before_fault = rt.sim.latent_wear
                fault_seen = True
                assert rt.running is True
                assert rt.workflow == "MONITORING"
                assert snap["decision"].get("machine_state") == "RUN"
                assert snap["decision"].get("action") == "RECHECK_SENSOR"
                assert snap["decision"].get("wear_index") is None
                assert snap["decision"].get("tool_health") is None
                # Keep ticking with fault active to prove latent wear keeps progressing.
                for _ in range(4):
                    rt.tick()
                wear_after_fault = rt.sim.latent_wear
                break
        assert fault_seen, "delayed sensor fault did not occur"
        assert wear_after_fault is not None and wear_before_fault is not None
        assert wear_after_fault > wear_before_fault, "machining/wear progression must continue during sensor fault"

        # Clearing the fault lets wear judgment recover without reset/restart.
        rt.set_faults([])
        recovered = False
        for _ in range(8):
            snap = rt.tick()
            if snap["decision"].get("state") != "SENSOR_FAULT":
                recovered = True
                break
        assert recovered
        assert rt.running is True
        assert rt.workflow == "MONITORING"

        # Tool change still requires validation, then explicit resume.
        rt.replace_tool()
        assert rt.display_tool_id == "T-2026-002"
        assert rt.workflow == "REVALIDATION_REQUIRED"
        rt.start_revalidation()
        for _ in range(30):
            rt.tick()
            if rt.workflow == "REVALIDATION_PASSED":
                break
        assert rt.workflow == "REVALIDATION_PASSED"
        assert rt.resume_ready
        rt.resume()
        assert rt.running and rt.workflow == "MONITORING"


if __name__ == "__main__":
    run()
    print("FULL_RESET_FAULT_CONTINUE_TEST_OK")
