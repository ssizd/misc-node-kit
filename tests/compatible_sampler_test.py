import importlib.util
import sys
import types
from pathlib import Path


spec = importlib.util.spec_from_file_location("compatible_sampler_test_module", Path(__file__).resolve().parents[1] / "nodes_compatible_sampler.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
calls = []
nodes = types.ModuleType("nodes")


class Spectrum:
    def sample(self, **kwargs):
        calls.append(("spectrum", kwargs))
        return ({"samples": "accelerated"},)


def standard(*args, **kwargs):
    calls.append(("standard", args, kwargs))
    return ({"samples": "standard", "metadata": "kept"},)


nodes.NODE_CLASS_MAPPINGS = {"SpectrumKSampler": Spectrum}
nodes.common_ksampler = standard
sys.modules["nodes"] = nodes
Anima = type("Anima", (), {"final_layer": object()})
MOSSImage = type("MOSSImage", (), {})


def model(dit):
    return types.SimpleNamespace(get_model_object=lambda name: dit)


sampler = module.WildcardCompatibleKSampler()
args = dict(seed=15, steps=20, cfg=4.5, sampler_name="euler", scheduler="simple",
            positive=object(), negative=object(), latent_image={"samples": "noise", "noise_mask": object()}, denoise=0.7)
result = sampler.sample(model(MOSSImage()), **args)
assert calls[-1][0] == "standard"
assert result[0]["metadata"] == "kept"
assert "no Spectrum acceleration" in result[1]
assert calls[-1][1][8] is args["latent_image"]
assert calls[-1][2]["denoise"] == 0.7
result = sampler.sample(model(Anima()), refresh_ratio=0.35, **args)
assert calls[-1][0] == "spectrum"
assert calls[-1][1]["refresh_ratio"] == 0.35
assert calls[-1][1]["mod_w_profile"] == "off"
assert calls[-1][1]["latent_image"] is args["latent_image"]
assert result[0]["samples"] == "accelerated"
sampler.sample(model(types.SimpleNamespace(_orig_mod=Anima())), **args)
assert calls[-1][0] == "spectrum"
sampler.sample(model(Anima()), backend="standard", **args)
assert calls[-1][0] == "standard"
try:
    sampler.sample(model(MOSSImage()), backend="spectrum", **args)
except ValueError as error:
    assert "does not support MOSSImage" in str(error)
else:
    raise AssertionError("Unsafe MOSS Spectrum execution accepted")
nodes.NODE_CLASS_MAPPINGS.clear()
sampler.sample(model(Anima()), **args)
assert calls[-1][0] == "standard"
try:
    sampler.sample(model(Anima()), backend="spectrum", **args)
except ValueError as error:
    assert "not installed" in str(error)
else:
    raise AssertionError("Missing Spectrum accepted")
class BrokenSpectrum:
    def sample(self, **kwargs):
        raise RuntimeError("sampling failed")
nodes.NODE_CLASS_MAPPINGS["SpectrumKSampler"] = BrokenSpectrum
try:
    sampler.sample(model(Anima()), **args)
except RuntimeError as error:
    assert str(error) == "sampling failed"
else:
    raise AssertionError("A real sampling failure was hidden")
print("Compatible sampler model routing and parameter forwarding tests passed.")
