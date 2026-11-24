import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "exclusive_output_prune_test_module",
    Path(__file__).resolve().parents[1] / "exclusive_output_prune.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


OUTPUT_TYPES = {"CameraSampler", "ImageComparer", "Save", "Preview", "OtherSave"}


def is_output(class_type):
    return class_type in OUTPUT_TYPES


def make_prompt(switch):
    return {
        "1": {"class_type": "SharedLoader", "inputs": {}},
        "10": {"class_type": "NormalDecode", "inputs": {"model": ["1", 0]}},
        "20": {"class_type": "NormalTail", "inputs": {"image": ["10", 0]}},
        "30": {"class_type": "CameraSampler", "inputs": {"model": ["1", 0]}},
        "40": {"class_type": "WildcardExclusiveOutputSwitch", "inputs": {
            "switch": switch, "on_false": ["20", 0], "on_true": ["30", 0],
        }},
        "50": {"class_type": "Save", "inputs": {"images": ["40", 0]}},
        "60": {"class_type": "ImageComparer", "inputs": {"image_a": ["10", 0]}},
        "70": {"class_type": "OtherSave", "inputs": {"image": ["71", 0]}},
        "71": {"class_type": "UnrelatedImage", "inputs": {}},
    }


prompt = make_prompt(False)
module.prune_prompt(prompt, is_output)
assert "on_true" not in prompt["40"]["inputs"]
assert "30" not in prompt
assert "60" in prompt
assert "50" in prompt
assert "70" in prompt

prompt = make_prompt(True)
module.prune_prompt(prompt, is_output)
assert "on_false" not in prompt["40"]["inputs"]
assert "30" in prompt
assert "60" not in prompt
assert "50" in prompt
assert "70" in prompt

prompt = make_prompt(False)
prompt["40"]["inputs"]["switch"] = ["80", 0]
before = {node_id: dict(entry) for node_id, entry in prompt.items()}
module.prune_prompt(prompt, is_output)
assert set(prompt) == set(before)
assert "on_true" in prompt["40"]["inputs"]

print("Exclusive output switch prompt pruning tests passed.")
