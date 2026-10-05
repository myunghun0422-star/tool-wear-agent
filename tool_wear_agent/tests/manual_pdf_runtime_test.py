from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.manual_knowledge import ManualKnowledgeBase


def run():
    kb = ManualKnowledgeBase(ROOT / "config" / "manual_knowledge.json")
    summary = {x["source"]: x for x in kb.source_summary()}
    for source in ["webdaq-504.pdf", "012-021e.pdf", "machining_titanium_05_2019.pdf"]:
        assert summary[source]["available"], (source, summary[source])
        assert not summary[source]["error"], (source, summary[source])

    items = kb.by_ids(["WEBDAQ-IEPE", "KISTLER-4COMP", "ISCAR-TI-WEAR"])
    assert len(items) == 3
    for item in items:
        assert item["retrieval_mode"] == "ORIGINAL_PDF"
        assert item["guidance"].strip()
        assert item["location"].startswith("원본 PDF p.")


if __name__ == "__main__":
    run()
    print("MANUAL PDF RUNTIME: OK")
