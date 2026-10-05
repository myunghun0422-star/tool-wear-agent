from pathlib import Path
import json, sys
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core.simulator import RealtimeSensorSimulator
from core.feature_extractor import FeatureExtractor
from core.manual_knowledge import ManualKnowledgeBase
from core.agent import ToolWearAgent

profile=json.loads((ROOT/'config/reference_profile.json').read_text(encoding='utf-8'))
kb=ManualKnowledgeBase(ROOT/'config/manual_knowledge.json')
ex=FeatureExtractor()


def run_auto(steps=100, faults=None, fault_start=None, fault_end=None):
    sim=RealtimeSensorSimulator(ROOT/'config/reference_profile.json',seed=42)
    ag=ToolWearAgent(profile,kb)
    rows=[]; decisions=[]
    for i in range(steps):
        active = faults or []
        if fault_start is not None and not (fault_start <= i < (fault_end if fault_end is not None else steps)):
            active=[]
        sim.set_faults(active)
        f=ex.extract(sim.sample_packet()).to_dict()
        hist=pd.DataFrame(rows)
        valid=hist
        d=ag.evaluate(f,valid).to_dict()
        decisions.append(d)
        rows.append({**f, **d})
    return sim, decisions


if __name__=='__main__':
    sim, ds = run_auto(110)
    levels=[d['wear_level'] for d in ds if d['state']!='SENSOR_FAULT']
    print('AUTO LEVELS:', list(dict.fromkeys(levels)))
    print('AUTO FINAL:', ds[-1]['state'], ds[-1]['wear_level'], ds[-1]['machine_state'], ds[-1]['action'])
    assert '초기 마모' in levels and '마모 진행' in levels and '교체 임박' in levels and '사용 한계' in levels
    assert any(d['machine_state']=='HOLD' for d in ds)

    for faults in [['VIBRATION'],['FORCE'],['SOUND'],['VIBRATION','FORCE'],['VIBRATION','FORCE','SOUND']]:
        sim, fd = run_auto(8,faults=faults)
        last=fd[-1]
        print('FAULT', faults, '=>', last['state'], last['fault_sensor'], 'machine=', last['machine_state'])
        assert last['state']=='SENSOR_FAULT'
        assert last['machine_state']=='RUN'

    sim, mix = run_auto(85,faults=['VIBRATION','SOUND'],fault_start=20,fault_end=35)
    assert any(d['state']=='SENSOR_FAULT' for d in mix[20:35])
    assert any(d['state']!='SENSOR_FAULT' for d in mix[35:])
    print('RECOVERY FINAL:', mix[-1]['state'], mix[-1]['wear_level'], mix[-1]['machine_state'])
