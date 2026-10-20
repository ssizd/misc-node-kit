import ast
import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "nodes_ltx_multi_lora.py"


def test_slot_capacity_and_missing_disabled_contract():
    text = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(text)
    assignments = {
        target.id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
        and target.id in {"MAX_LORA_SLOTS", "LORA_NONE_OPTION"}
    }
    assert assignments["MAX_LORA_SLOTS"] >= 32
    assert "if not _is_slot_enabled" in text


def test_node_is_registered_by_package():
    init_text = (ROOT / "__init__.py").read_text(encoding="utf-8")
    assert "LTX_MULTI_LORA_CLASS_MAPPINGS" in init_text
    assert "LTX_MULTI_LORA_DISPLAY_NAME_MAPPINGS" in init_text


def test_frontend_uses_hidden_option_source_and_same_capacity():
    text = (ROOT / "web" / "ltx_multi_lora.js").read_text(encoding="utf-8")
    assert 'const NODE_NAME = "WildcardLTXMultiLoraLoader"' in text
    assert "const MAX_SLOTS = 32;" in text
    assert "optional.lora_catalog" in text
    assert 'hideWidget(getWidget(node, "lora_catalog"))' in text
    assert 'widget.type = "converted-widget"' in text


def test_disabled_missing_lora_does_not_block_validation():
    comfy = types.ModuleType("comfy")
    comfy.__path__ = []
    for name in ("lora", "lora_convert", "utils"):
        module = types.ModuleType(f"comfy.{name}")
        setattr(comfy, name, module)
        sys.modules[f"comfy.{name}"] = module
    sys.modules["comfy"] = comfy

    folder_paths = types.ModuleType("folder_paths")
    folder_paths.get_filename_list = lambda category: ["installed.safetensors"]
    sys.modules["folder_paths"] = folder_paths

    spec = importlib.util.spec_from_file_location("wildcard_ltx_multi_lora_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.WildcardLTXMultiLoraLoader.VALIDATE_INPUTS(
        active_loras=1, enabled_1=False, lora_1="missing.safetensors"
    ) is True
    error = module.WildcardLTXMultiLoraLoader.VALIDATE_INPUTS(
        active_loras=1, enabled_1=True, lora_1="missing.safetensors"
    )
    assert "enabled but not installed" in error
    inputs = module.WildcardLTXMultiLoraLoader.INPUT_TYPES()
    assert inputs["required"]["lora_1"][0] == "STRING"
    assert inputs["optional"]["lora_catalog"][0] == ["__none__", "installed.safetensors"]
    assert "clip" in inputs["optional"]
    assert inputs["optional"]["lora_stack"] == ("WILDCARD_LORA_STACK",)
    loader = module.WildcardLTXMultiLoraLoader()
    assert loader.load_multi_lora("original", active_loras=0, lora_stack=[
        {"enabled": False, "lora_name": "missing.safetensors"},
        {"lora_name": ""},
    ]) == ("original", None)
    applied = []
    loader._load_lora_dict = lambda name: {"name": name}
    comfy.lora.model_lora_keys_unet = lambda model, keys: keys
    comfy.lora_convert.convert_lora = lambda value: value
    comfy.lora.load_lora = lambda value, keys: value
    class Model:
        model = object()
        def clone(self):
            return Model()
        def add_patches(self, patches, strength):
            applied.append((patches["name"], strength))
    loader.load_multi_lora(Model(), active_loras=1, lora_1="installed.safetensors", strength_1=0.4,
                           lora_stack=[{"lora_name": "installed.safetensors", "lora_strength": 0.7}])
    assert applied == [("installed.safetensors", 0.4), ("installed.safetensors", 0.7)]


def test_upstream_deno_files_are_not_the_clone():
    deno_root = ROOT.parent / "deno-custom-nodes"
    backend = (deno_root / "deno_ltx_multi_lora_loader.py").read_text(encoding="utf-8")
    frontend = (deno_root / "web" / "js" / "deno_ltx_multi_lora.js").read_text(encoding="utf-8")
    assert 'MAX_LORA_SLOTS = 8' in backend
    assert 'required[_slot_key("lora", index)] = (lora_options' in backend
    assert "lora_catalog" not in backend
    assert 'const MAX_SLOTS = 8;' in frontend


def main():
    test_slot_capacity_and_missing_disabled_contract()
    test_node_is_registered_by_package()
    test_frontend_uses_hidden_option_source_and_same_capacity()
    test_disabled_missing_lora_does_not_block_validation()
    test_upstream_deno_files_are_not_the_clone()
    print("LTX multi LoRA regression tests passed.")


if __name__ == "__main__":
    main()
