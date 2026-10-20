from io import BytesIO
from pathlib import Path
import importlib.util
import sys

from PIL import Image
import piexif
import piexif.helper


NODE_ROOT = Path(__file__).resolve().parent.parent
COMFY_ROOT = NODE_ROOT.parent.parent
sys.path.insert(0, str(COMFY_ROOT))

spec = importlib.util.spec_from_file_location(
    "save_image_extended_base", NODE_ROOT / "save_image_extended_base.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_webp_metadata_with_and_without_workflow():
    saver = module.SaveImageExtended()
    image = Image.new("RGB", (2, 2), "white")
    prompt = {"1": {"class_type": "NAIAPromptBridge", "inputs": {"positive": "test"}}}

    for extra_pnginfo, expect_workflow in ((None, False), ({"workflow": prompt}, True)):
        buffer = BytesIO()
        image.save(
            buffer,
            format="WEBP",
            exif=saver.get_metadata_exif(image, prompt, extra_pnginfo),
        )
        buffer.seek(0)
        exif_values = list(Image.open(buffer).getexif().values())
        assert any(str(value).startswith("Prompt: ") for value in exif_values)
        assert any(str(value).startswith("Workflow: ") for value in exif_values) == expect_workflow


def test_generation_info_contains_final_prompts_and_active_loras():
    saver = module.SaveImageExtended()
    prompt = {
        "style": {
            "class_type": "EasyUseAnimaLoraPreset",
            "inputs": {
                "profile_index": 2,
                "profile_data": '{"1":{"loras":[]},"2":{"loras":['
                                '{"name":"style\\\\active.safetensors","on":true,"strength":0.8},'
                                '{"name":"style\\\\disabled.safetensors","on":false,"strength":1.0}'
                                ']}}',
            },
        }
    }
    positive = "final positive, <lora:character_lora:0.7>"
    negative = "final negative"
    generation_info = saver.build_generation_info(prompt, positive, negative)

    assert generation_info.startswith(positive)
    assert "Negative prompt: final negative" in generation_info
    assert "character_lora (0.7)" in generation_info
    assert "style\\active.safetensors (0.8)" in generation_info
    assert "disabled.safetensors" not in generation_info

    image = Image.new("RGB", (2, 2), "white")
    buffer = BytesIO()
    image.save(
        buffer,
        format="WEBP",
        exif=saver.get_metadata_exif(image, prompt, {"parameters": generation_info}),
    )
    buffer.seek(0)
    saved = Image.open(buffer)
    exif_dict = piexif.load(saved.info["exif"])
    user_comment = piexif.helper.UserComment.load(
        exif_dict["Exif"][piexif.ExifIFD.UserComment]
    )
    assert user_comment == generation_info


if __name__ == "__main__":
    test_webp_metadata_with_and_without_workflow()
    test_generation_info_contains_final_prompts_and_active_loras()
    print("Save image metadata tests passed.")
