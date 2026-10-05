from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.manual_knowledge import ManualKnowledgeBase
from web_runtime import KB_PATH, runtime


def run():
    kb = ManualKnowledgeBase(KB_PATH)
    ids = ["ISCAR-TI-WEAR", "KISTLER-4COMP", "WEBDAQ-ACQ"]
    items = kb.by_ids(ids)
    assert len(items) == 3
    for item in items:
        assert item.get("verified_from_original") is True
        assert item.get("retrieval_mode") == "ORIGINAL_PDF"
        assert re.search(r"[가-힣]", item.get("guidance_ko", ""))
        assert "original_excerpt" not in item

    runtime.full_reset()
    runtime.start()
    health = []
    seen_korean_manual = False
    final = None
    for _ in range(180):
        final = runtime.tick()
        d = final["decision"]
        if d.get("tool_health") is not None:
            health.append(float(d["tool_health"]))
        for g in d.get("manual_guidance", []):
            if g.get("retrieval_mode") == "ORIGINAL_PDF":
                assert g.get("verified_from_original") is True
                assert re.search(r"[가-힣]", g.get("guidance_ko", ""))
                seen_korean_manual = True
        if d.get("machine_state") == "HOLD":
            break

    assert seen_korean_manual
    assert all(b <= a + 1e-9 for a, b in zip(health, health[1:])), "Tool Health must not rise for the same tool"
    assert final is not None
    assert final["decision"]["machine_state"] == "HOLD"
    assert final["decision"]["action"] == "CHANGE_TOOL_REQUEST"
    print("KOREAN MANUAL / MONOTONIC HEALTH / HOLD REGRESSION: OK")


if __name__ == "__main__":
    run()
