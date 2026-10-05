from pathlib import Path
import sys, json
import pandas as pd
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core.agent import ToolWearAgent
from core.manual_knowledge import ManualKnowledgeBase
from core.simulator import RealtimeSensorSimulator
from core.feature_extractor import FeatureExtractor
profile=json.loads((ROOT/'config/reference_profile.json').read_text())
agent=ToolWearAgent(profile,ManualKnowledgeBase(ROOT/'config/manual_knowledge.json'))
ex=FeatureExtractor();sim=RealtimeSensorSimulator(ROOT/'config/reference_profile.json')
base=ex.extract(sim.sample_packet(validation_mode=True)).to_dict()
rows=[]
def tick(f):
    d=agent.evaluate(f,pd.DataFrame(rows)).to_dict()
    rows.append({**f,**d})
    return d
for _ in range(8): tick(base)
spike={**base, 'vibration_rms':base['vibration_rms']*1.9,
       'force_resultant_rms':base['force_resultant_rms']*1.9,
       'sound_rms':base['sound_rms']*1.9,
       'fx_std':base['fx_std']*3,'fy_std':base['fy_std']*3,'fz_std':base['fz_std']*3}
d=tick(spike)
assert d['state']=='NORMAL' and d['machine_state']=='RUN'
for _ in range(5): tick(base)
assert rows[-1]['state']=='NORMAL'
# Threshold chatter should not flip an established level back and forth.
rows=[]
for i in range(60): tick({**base, **{k:base[k]*(1.10 if i%2 else 1.18)
    for k in ['vibration_rms','force_resultant_rms','sound_rms']}})
assert sum(a['wear_level']!=b['wear_level'] for a,b in zip(rows,rows[1:])) <= 2
# Genuine persistent degradation must still reach HOLD; no single-window stop.
rows=[]
for _ in range(8): tick(base)
for i in range(45):
    d=tick(spike)
    if i<2: assert d['machine_state']=='RUN'
assert d['machine_state']=='HOLD'
# Single-window sensor excursion stays pending and is not mixed into wear history.
rows=[]
for _ in range(8): tick(base)
bad={**base,'vibration_rms':base['vibration_rms']*3}
d=tick(bad);assert d['state']!='SENSOR_FAULT' and d['action']=='RECHECK_SENSOR'
d=tick(base);assert d['state']=='NORMAL'
for _ in range(3): d=tick(bad)
assert d['state']=='SENSOR_FAULT' and d['machine_state']=='RUN'
print('SPIKE REJECTION / HYSTERESIS / PERSISTENT HOLD / SENSOR DEBOUNCE: OK')
