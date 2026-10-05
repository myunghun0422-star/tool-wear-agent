from pathlib import Path
import json
import sys
import tempfile
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.history import HistoryStore
from core.simulator import RealtimeSensorSimulator
from core.feature_extractor import FeatureExtractor
from core.manual_knowledge import ManualKnowledgeBase
from core.agent import ToolWearAgent

profile = json.loads((ROOT / 'config/reference_profile.json').read_text(encoding='utf-8'))
extractor = FeatureExtractor()
kb = ManualKnowledgeBase(ROOT / 'config/manual_knowledge.json')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as td:
        store = HistoryStore(Path(td) / 'history.db')
        store.ensure_tool('T-2026-001')
        store.finish_tool('T-2026-001', '운영자 수동 교체')
        store.ensure_tool('T-2026-002', validation_status='REQUIRED')
        assert store.validation_status('T-2026-002') == 'REQUIRED'
        store.set_validation_status('T-2026-002', 'VALIDATING')
        assert store.validation_status('T-2026-002') == 'VALIDATING'
        store.set_validation_status('T-2026-002', 'VALIDATED')
        assert store.validation_status('T-2026-002') == 'VALIDATED'
        tools = store.tools()
        assert 'validation_status' in tools.columns and 'validated_at' in tools.columns
        print('PERSISTED REVALIDATION STATUS: OK')

    sim = RealtimeSensorSimulator(ROOT / 'config/reference_profile.json', seed=123)
    agent = ToolWearAgent(profile, kb)
    start_wear = sim.latent_wear
    target = int(profile['revalidation']['required_consecutive_windows'])
    streak = 0
    for _ in range(target):
        sim.set_faults([])
        packet = sim.sample_packet(advance_wear=False, validation_mode=True)
        f = extractor.extract(packet).to_dict()
        d = agent.evaluate(f, pd.DataFrame()).to_dict()
        ok = (
            d['state'] == 'NORMAL'
            and d['sensor_integrity'] >= profile['revalidation']['min_sensor_integrity']
            and d['wear_index'] < profile['revalidation']['max_wear_index']
        )
        streak = streak + 1 if ok else 0
    assert streak == target
    assert sim.latent_wear == start_wear
    print('NORMAL REVALIDATION 6/6: OK')

    sim.set_faults(['VIBRATION'])
    rows=[]
    for i in range(3):
        packet = sim.sample_packet(advance_wear=False, validation_mode=True)
        f = extractor.extract(packet).to_dict()
        d = agent.evaluate(f, pd.DataFrame(rows)).to_dict()
        assert d['action'] == 'RECHECK_SENSOR'
        rows.append({**f, **d})
    assert d['state'] == 'SENSOR_FAULT'
    assert '진동' in str(d['fault_sensor'])
    assert sim.latent_wear == start_wear
    print('PERSISTENT FAULT BLOCKS REVALIDATION: OK')
