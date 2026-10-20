"""Named prompt presets with one selected prompt output."""

import json


def _default_state():
    return {
        "version": 2,
        "presets": [{
            "id": "preset-1",
            "name": "Preset 1",
            "prompt": "",
            "pair_enabled": False,
            "prompt_2": "",
        }],
        "selected_id": "preset-1",
    }


def _parse_state(value):
    try:
        state = json.loads(str(value or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return _default_state()
    if not isinstance(state, dict):
        return _default_state()

    presets = state.get("presets")
    if not isinstance(presets, list) or not presets:
        return _default_state()
    presets = [item for item in presets if isinstance(item, dict)]
    if not presets:
        return _default_state()
    state["presets"] = presets
    state["version"] = 2
    return state


class PromptPresetLibrary:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "library_json": (
                    "STRING",
                    {
                        "default": json.dumps(_default_state(), ensure_ascii=False),
                        "multiline": False,
                        "hidden": True,
                    },
                ),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "WILDCARD_LORA_STACK")
    RETURN_NAMES = ("prompt_1", "prompt_2", "lora_stack")
    FUNCTION = "select_prompt"
    CATEGORY = "prompt/string"

    def select_prompt(self, library_json):
        state = _parse_state(library_json)
        presets = state["presets"]
        selected_id = str(state.get("selected_id", ""))
        selected = next(
            (item for item in presets if str(item.get("id", "")) == selected_id),
            presets[0],
        )
        prompt_1 = str(selected.get("prompt", "") or "")
        prompt_2 = str(selected.get("prompt_2", "") or "") if selected.get("pair_enabled", False) else prompt_1
        loras = selected.get("loras")
        if not isinstance(loras, list):
            loras = [selected]
        stack = [dict(lora) for lora in loras if isinstance(lora, dict)] if selected.get("lora_enabled", False) else []
        return (prompt_1, prompt_2, stack)


NODE_CLASS_MAPPINGS = {"PromptPresetLibrary": PromptPresetLibrary}
NODE_DISPLAY_NAME_MAPPINGS = {"PromptPresetLibrary": "Prompt Preset Library"}
