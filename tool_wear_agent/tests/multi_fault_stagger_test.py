from pathlib import Path
import sys, json
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core.fault_scheduler import FaultInjectionScheduler
from core.simulator import RealtimeSensorSimulator
from core.feature_extractor import FeatureExtractor
from core.agent import ToolWearAgent
from core.manual_knowledge import ManualKnowledgeBase
import pandas as pd
profile=json.loads((ROOT/'config/reference_profile.json').read_text())
delays=profile['fault_injection']['delay_windows_by_sensor']
scheduler=FaultInjectionScheduler(delay_windows=8,delay_by_fault=delays)
scheduler.sync_selection(['VIBRATION','SOUND','FORCE'],0)
events={k:None for k in scheduler.selected}
for packet in range(1,20):
    for fault in scheduler.update(packet): events[fault]=packet
assert events=={'VIBRATION':9,'SOUND':13,'FORCE':17},events

sim=RealtimeSensorSimulator(ROOT/'config/reference_profile.json',seed=19)
extract=FeatureExtractor(); samples={}
for sensor in ['VIBRATION','SOUND','FORCE']:
    sim.reset(wear=5);sim.set_faults([])
    for _ in range(4):sim.sample_packet()
    baseline=extract.extract(sim.sample_packet()).to_dict()
    sim.set_faults([sensor]); values=[]
    for _ in range(3): values.append(extract.extract(sim.sample_packet()).to_dict())
    samples[sensor]=(baseline,values[-1])
ratios={s:{'vibration':v['vibration_rms']/b['vibration_rms'],
           'sound':v['sound_rms']/b['sound_rms'],
           'force':v['force_resultant_rms']/b['force_resultant_rms']}
        for s,(b,v) in samples.items()}
assert ratios['VIBRATION']['vibration']>2 and ratios['VIBRATION']['sound']<1.5
assert ratios['SOUND']['sound']>2 and ratios['SOUND']['vibration']<1.5
assert ratios['FORCE']['force']>2 and ratios['FORCE']['sound']<1.5

agent=ToolWearAgent(profile,ManualKnowledgeBase(ROOT/'config/manual_knowledge.json'))
history=[];decision=None
for _ in range(3):
    sim.set_faults(['FORCE']);f=extract.extract(sim.sample_packet()).to_dict()
    decision=agent.evaluate(f,pd.DataFrame(history)).to_dict();history.append({**f,**decision})
assert decision['state']=='SENSOR_FAULT' and '절삭력' in decision['fault_sensor']
ids={m['id'] for m in decision['manual_guidance']}
assert 'KISTLER-4COMP' in ids and 'WEBDAQ-ACQ' not in ids,ids
fresh=ToolWearAgent(profile,ManualKnowledgeBase(ROOT/'config/manual_knowledge.json'))
fresh_sim=RealtimeSensorSimulator(ROOT/'config/reference_profile.json',seed=7)
base=extract.extract(fresh_sim.sample_packet(validation_mode=True)).to_dict()
d2=fresh.evaluate({**base,'vibration_rms':profile['baseline']['vibration_rms']*10},pd.DataFrame()).to_dict()
assert d2['action']=='RECHECK_SENSOR'
assert {'OPS-SENSOR-FIRST','WEBDAQ-IEPE'} <= {m['id'] for m in d2['manual_guidance']}
print('STAGGERED PER-SENSOR FAULTS / DISTINCT SIGNATURES / MATCHED MANUALS: OK')
