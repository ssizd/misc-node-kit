import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("preset_test", Path(__file__).resolve().parents[1] / "nodes_prompt_preset_library.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
loader = module.PromptPresetLibrary()
presets = [
    {"id": "off", "prompt": "first", "lora_enabled": False, "lora_name": "missing"},
    {"id": "on", "prompt": "second", "pair_enabled": True, "prompt_2": "last", "lora_enabled": True,
     "loras": [{"enabled": True, "lora_name": "test.safetensors", "lora_strength": 0.5},
               {"enabled": False, "lora_name": "missing"}]},
]

def state(selected):
    return json.dumps({"presets": presets, "selected_id": selected})

assert loader.select_prompt(state("off")) == ("first", "first", [])
assert loader.select_prompt(state("on")) == ("second", "last", presets[1]["loras"])
presets[1].pop("loras")
presets[1]["lora_name"] = "legacy.safetensors"
assert loader.select_prompt(state("on"))[2][0]["lora_name"] == "legacy.safetensors"
assert loader.RETURN_NAMES == ("prompt_1", "prompt_2", "lora_stack")
assert "optional" not in loader.INPUT_TYPES()
print("Prompt preset model-free LoRA selection tests passed.")
