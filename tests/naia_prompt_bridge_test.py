from pathlib import Path
import importlib.util


MODULE_PATH = Path(__file__).resolve().parent.parent / "nodes_naia_prompt_bridge.py"
SPEC = importlib.util.spec_from_file_location("nodes_naia_prompt_bridge", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_bridge_contract():
    bridge = MODULE.NAIAPromptBridge()
    assert bridge.emit_prompts(
        True,
        "positive text",
        "negative text",
        "original positive",
        "original negative",
    ) == (
        "positive text",
        "negative text",
        True,
    )
    assert bridge.emit_prompts(
        False,
        "positive text",
        "negative text",
        "original positive",
        "original negative",
    ) == (
        "original positive",
        "original negative",
        False,
    )
    assert MODULE.NODE_CLASS_MAPPINGS["NAIAPromptBridge"] is MODULE.NAIAPromptBridge
    assert MODULE.NAIAPromptBridge.RETURN_NAMES == ("final_positive", "final_negative", "enabled")


if __name__ == "__main__":
    test_bridge_contract()
    print("NAIA prompt bridge tests passed.")
