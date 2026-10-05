"""Empirical feature sampling; chronology stays private to the simulator.

No VBmax, cycle or stage number is supplied to the agent. These are synthetic
waveforms matching measured one-second moments, not a 10 kHz signal replay.
"""
import json
from pathlib import Path
import numpy as np


class LifecycleSampler:
    def __init__(self, path: Path):
        self.data = json.loads(Path(path).read_text(encoding='utf-8'))
        self.stages = self.data['stages']
        self.quantiles = np.array([.5, .5])
        if len(self.stages) != 11:
            raise ValueError('공구 일대기 프로파일에는 11개 시점이 필요합니다.')

    def _distribution(self, stage, key):
        # Uncalibrated stage 11 sensor channels explicitly use the previous stage.
        while self.stages[stage][key] is None and stage > 0:
            stage -= 1
        return self.stages[stage][key]['windows']

    def _row(self, stage, key, q):
        rows = self._distribution(stage, key)
        rows = sorted(rows, key=lambda r: r['activity'])
        return rows[min(len(rows)-1, int(q*len(rows)))]

    def parameters(self, progress, sensor_q, force_q):
        position = float(np.clip(progress, 0, 1))*10
        left = min(9, int(position)); alpha = position-left
        result = {}
        for key,q in [('sensor',sensor_q),('force',force_q)]:
            a=self._row(left,key,q); b=self._row(left+1,key,q)
            fields=['vibration_rms','sound_rms'] if key=='sensor' else ['mean','cov']
            result[key]={field:(1-alpha)*np.asarray(a[field])+alpha*np.asarray(b[field])
                         for field in fields}
        return result

    def signals(self, progress, n, rng, validation=False):
        # Shared quantile for the adjacent stages preserves paired channel statistics.
        # Separate sensor/force quantiles deliberately avoid claiming synchronization.
        if validation:
            sensor_q=force_q=.5
        else:
            # Slow load fluctuations instead of choosing an unrelated load each second.
            self.quantiles = np.clip(.85*self.quantiles + .15*rng.uniform(.05,.95,2), .05, .95)
            sensor_q,force_q=self.quantiles
        p=self.parameters(progress,sensor_q,force_q)
        def centered(target):
            z=rng.normal(size=n);z-=z.mean()
            return z/(z.std()+1e-12)*float(target)
        vibration=centered(p['sensor']['vibration_rms'])
        sound=centered(p['sensor']['sound_rms'])
        cov=p['force']['cov'];cov=(cov+cov.T)/2
        eig,vec=np.linalg.eigh(cov)
        # Whiten a random matrix, then color it to the measured joint covariance.
        z=rng.normal(size=(n,4));z-=z.mean(0)
        ze,zv=np.linalg.eigh(z.T@z/n)
        z=z@(zv@np.diag(1/np.sqrt(np.maximum(ze,1e-12)))@zv.T)
        force=z@(vec@np.diag(np.sqrt(np.maximum(eig,0)))@vec.T)+p['force']['mean']
        return vibration,sound,*force.T
