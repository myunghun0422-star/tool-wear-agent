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
        r = web_runtime.ToolWearWebRuntime()
        assert not r.snapshot()["runtime"]["started"]
        r.start()
        for _ in range(3):
            s = r.tick()
        assert s["runtime"]["last_packet_id"] >= 3
        r.set_faults(["VIBRATION"])
        assert "VIBRATION" in r.snapshot()["faults"]["selected"]


if __name__ == "__main__":
    run()
    print("WEB RUNTIME BASIC FLOW: OK")
