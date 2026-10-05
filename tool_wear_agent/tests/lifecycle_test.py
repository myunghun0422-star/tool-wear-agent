from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.lifecycle import LifecycleSampler
from core.simulator import RealtimeSensorSimulator
from core.feature_extractor import FeatureExtractor

life = LifecycleSampler(ROOT/'config/lifecycle_profile.json')
assert len(life.stages) == 11
for stage in range(11):
    progress=stage/10
    params=life.parameters(progress,.5,.5)
    rng=np.random.default_rng(stage)
    v,s,*forces=life.signals(progress,512,rng,validation=True)
    force=np.array(forces).T
    np.testing.assert_allclose(np.sqrt(np.mean(v*v)),params['sensor']['vibration_rms'],rtol=1e-8)
    np.testing.assert_allclose(np.sqrt(np.mean(s*s)),params['sensor']['sound_rms'],rtol=1e-8)
    np.testing.assert_allclose(force.mean(0),params['force']['mean'],atol=1e-8)
    np.testing.assert_allclose(np.cov(force,rowvar=False,bias=True),params['force']['cov'],atol=1e-8)
    assert np.isfinite(force).all()
# Unknown mV calibration must not be silently treated as physical units.
for q in [.1,.5,.9]:
    a=life.parameters(.9,q,q)['sensor'];b=life.parameters(1,q,q)['sensor']
    for key in a: np.testing.assert_allclose(a[key],b[key])
# Raw signals and sampled feature windows remain stochastic and reproducible.
a=RealtimeSensorSimulator(ROOT/'config/reference_profile.json',seed=90)
b=RealtimeSensorSimulator(ROOT/'config/reference_profile.json',seed=90)
for _ in range(20):
    pa=a.sample_packet();pb=b.sample_packet()
    np.testing.assert_array_equal(pa.fx,pb.fx)
    np.testing.assert_array_equal(pa.vibration,pb.vibration)
wear=a.latent_wear
a.sample_packet(validation_mode=True)
assert a.latent_wear == wear
a.reset()
assert a.latent_wear == a.start_wear
print('11 STAGE MOMENTS / FORCE COVARIANCE / mV FALLBACK / SEED / RESET: OK')
