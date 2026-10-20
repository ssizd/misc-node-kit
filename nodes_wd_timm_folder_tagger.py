from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageOps


IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".avif",
}
_SOURCE_MODULE = None


def _source_module():
    global _SOURCE_MODULE
    if _SOURCE_MODULE is not None:
        return _SOURCE_MODULE

    source_path = Path(__file__).resolve().parent.parent / "ComfyUI-WD-Timm-Tagger" / "nodes.py"
    if not source_path.is_file():
        raise RuntimeError(
            "ComfyUI-WD-Timm-Tagger is required. Expected: " + str(source_path)
        )
    spec = importlib.util.spec_from_file_location("wildcard_wd_timm_source", source_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load WD Timm Tagger from: {source_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _SOURCE_MODULE = module
    return module


def _model_list():
    try:
        return _source_module().get_model_list()
    except Exception:
        return ["wd-eva02-large-tagger-v3"]


def _natural_key(path: Path):
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", str(path))]


def _load_image(path: Path) -> torch.Tensor:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        array = np.asarray(image, dtype=np.float32) / 255.0
    return torch.from_numpy(array).unsqueeze(0)


def _join_prefix(prefix: str, tags: str) -> str:
    prefix = str(prefix or "").strip().strip(",").strip()
    tags = str(tags or "").strip().strip(",").strip()
    if prefix and tags:
        return f"{prefix}, {tags}"
    return prefix or tags


class WDTimmFolderTagger:
    def __init__(self):
        self._tagger = None

    @classmethod
    def INPUT_TYPES(cls):
        models = _model_list()
        return {
            "required": {
                "image_folder": ("STRING", {"default": "", "multiline": False}),
                "model_name": (models, {"default": models[0]}),
                "dtype": (["auto", "bf16", "fp16"], {"default": "auto"}),
                "general_threshold": ("FLOAT", {
                    "default": 0.35, "min": 0.0, "max": 1.0, "step": 0.01,
                }),
                "character_threshold": ("FLOAT", {
                    "default": 0.75, "min": 0.0, "max": 1.0, "step": 0.01,
                }),
                "add_rating": ("BOOLEAN", {"default": False}),
                "exclude_tags": ("STRING", {"default": "", "multiline": False}),
                "prefix": ("STRING", {
                    "default": "", "multiline": True,
                    "tooltip": "Tags added before the detected WD tags.",
                }),
                "save_text": ("BOOLEAN", {
                    "default": True,
                    "label_on": "save .txt beside image",
                    "label_off": "do not save",
                }),
                "if_text_exists": (["overwrite", "skip"], {"default": "overwrite"}),
                "include_subfolders": ("BOOLEAN", {
                    "default": False,
                    "label_on": "include subfolders",
                    "label_off": "top folder only",
                }),
            },
            "optional": {
                "image": ("IMAGE", {
                    "tooltip": "When connected, tag only the first connected image and ignore image_folder. "
                               "Connected IMAGE data has no source path, so sibling .txt saving is disabled.",
                }),
            },
        }

    OUTPUT_IS_LIST = (True, True, True, False, False)
    RETURN_TYPES = ("STRING", "STRING", "STRING", "INT", "STRING")
    RETURN_NAMES = ("tags", "image_paths", "text_paths", "processed_count", "report")
    FUNCTION = "tag_folder"
    CATEGORY = "wildcard_image_iterator/tagging"
    DESCRIPTION = (
        "Tag every image in a folder with WD Timm Tagger and optionally save matching .txt files."
    )

    def _images(self, folder: Path, recursive: bool) -> list[Path]:
        iterator = folder.rglob("*") if recursive else folder.iterdir()
        return sorted(
            (path for path in iterator if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS),
            key=_natural_key,
        )

    def tag_folder(self, image_folder, model_name, dtype, general_threshold,
                   character_threshold, add_rating, exclude_tags, prefix,
                   save_text, if_text_exists, include_subfolders, image=None):
        if self._tagger is None:
            self._tagger = _source_module().WDTimmTagger()

        if image is not None:
            tagged, _raw = self._tagger.tag(
                image[:1],
                model_name,
                dtype,
                float(general_threshold),
                float(character_threshold),
                bool(add_rating),
                exclude_tags,
                1,
            )
            final_tags = _join_prefix(prefix, tagged[0] if tagged else "")
            save_note = (
                " Connected IMAGE has no source file path, so save_text was ignored."
                if save_text else ""
            )
            return ([final_tags], [], [], 1, "Tagged 1 connected image." + save_note)

        folder = Path(os.path.expandvars(os.path.expanduser(str(image_folder).strip()))).resolve()
        if not folder.is_dir():
            raise FileNotFoundError(f"Image folder does not exist: {folder}")

        image_paths = self._images(folder, bool(include_subfolders))
        if not image_paths:
            raise FileNotFoundError(f"No supported images found in: {folder}")

        tags_out = []
        paths_out = []
        text_paths_out = []
        saved = 0
        skipped = 0
        failed = []

        for index, image_path in enumerate(image_paths, start=1):
            try:
                image = _load_image(image_path)
                tagged, _raw = self._tagger.tag(
                    image,
                    model_name,
                    dtype,
                    float(general_threshold),
                    float(character_threshold),
                    bool(add_rating),
                    exclude_tags,
                    1,
                )
                final_tags = _join_prefix(prefix, tagged[0] if tagged else "")
                text_path = image_path.with_suffix(".txt")
                if save_text:
                    if text_path.exists() and if_text_exists == "skip":
                        skipped += 1
                    else:
                        text_path.write_text(final_tags, encoding="utf-8")
                        saved += 1
                    text_paths_out.append(str(text_path))
                tags_out.append(final_tags)
                paths_out.append(str(image_path))
                print(f"[WD Timm Folder Tagger] {index}/{len(image_paths)}: {image_path.name}")
            except Exception as exc:
                failed.append(f"{image_path.name}: {exc}")

        if not tags_out:
            details = "\n".join(failed[:10])
            raise RuntimeError(f"Every image failed to tag.\n{details}")

        report = (
            f"Tagged {len(tags_out)}/{len(image_paths)} image(s); "
            f"saved {saved} text file(s), skipped {skipped}, failed {len(failed)}."
        )
        if failed:
            report += "\n" + "\n".join(failed[:10])
        return (tags_out, paths_out, text_paths_out, len(tags_out), report)


NODE_CLASS_MAPPINGS = {
    "WDTimmFolderTaggerWildcard": WDTimmFolderTagger,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "WDTimmFolderTaggerWildcard": "WD Timm Folder Tagger + TXT",
}
