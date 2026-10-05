"""모니터링 시작 후 센서 이상이 지정된 지연 구간에 발생하는지 확인한다."""
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
        rt.set_faults(["VIBRATION", "SOUND", "FORCE"])
        rt.start()

        first_seen = {}
        for step in range(1, 25):
            snap = rt.tick()
            for sensor in snap["faults"]["active"]:
                first_seen.setdefault(sensor, step)

        assert first_seen["VIBRATION"] == 9
        assert first_seen["SOUND"] == 13
        assert first_seen["FORCE"] == 17
        assert rt.running is True


if __name__ == "__main__":
    run()
    print("START / SENSOR FAULT DELAY AFTER 8·12·16 NORMAL WINDOWS: OK")
