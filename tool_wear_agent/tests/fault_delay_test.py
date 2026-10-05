from pathlib import Path
import json
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.fault_scheduler import FaultInjectionScheduler
from core.simulator import RealtimeSensorSimulator
from core.feature_extractor import FeatureExtractor
from core.manual_knowledge import ManualKnowledgeBase
from core.agent import ToolWearAgent

if __name__ == '__main__':
    profile = json.loads((ROOT / 'config/reference_profile.json').read_text(encoding='utf-8'))
    sim = RealtimeSensorSimulator(ROOT / 'config/reference_profile.json', seed=9)
    scheduler = FaultInjectionScheduler(delay_windows=8)
    extractor = FeatureExtractor()
    agent = ToolWearAgent(profile, ManualKnowledgeBase(ROOT / 'config/manual_knowledge.json'))
    scheduler.sync_selection(['VIBRATION'], sim.packet_id)

    history = []
    for i in range(8):
        scheduler.update(sim.packet_id + 1)
        sim.set_faults(sorted(scheduler.active))
        p = sim.sample_packet()
        assert 'FAULT' not in p.scenario
        f = extractor.extract(p).to_dict()
        hist = pd.DataFrame(history)
        d = agent.evaluate(f, hist).to_dict()
        assert d['state'] != 'SENSOR_FAULT', f'fault occurred too early at {i+1}'
        history.append({**f, **d})

    for offset in range(3):
        scheduler.update(sim.packet_id + 1)
        sim.set_faults(sorted(scheduler.active))
        p = sim.sample_packet()
        assert 'VIBRATION_FAULT' in p.scenario
        f = extractor.extract(p).to_dict()
        d = agent.evaluate(f, pd.DataFrame(history)).to_dict()
        assert (d['state'] == 'SENSOR_FAULT') == (offset == 2)
        assert d['machine_state'] == 'RUN'
        history.append({**f, **d})
    print('DELAYED INJECTION + THREE CONSECUTIVE FAULT WINDOWS: OK')

    scheduler.sync_selection([], sim.packet_id)
    sim.set_faults(sorted(scheduler.active))
    p = sim.sample_packet()
    assert 'FAULT' not in p.scenario
    print('FAULT CLEAR / RECOVERY: OK')
