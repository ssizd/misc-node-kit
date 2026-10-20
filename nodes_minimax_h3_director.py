"""MiniMax H3 Director guide node."""
import json
import os

from .helper_minimax_h3_director import (
    FPS,
    align_frame_count,
    assemble_prompt,
    audio_duration,
    load_audio,
    load_embedded_video_audio,
    load_image,
    load_video,
    normalize_guide,
    validate_reference_limits,
)
from .helper_minimax_h3_prompt_builder import (
    build_prompt,
    default_builder_state,
    migrate_legacy_prompt,
    normalize_ref_schema,
    validate_builder_state,
)


IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff")
SORT_METHODS = ["Numerical (ASC)", "Numerical (DESC)", "Alphabetical (ASC)", "Alphabetical (DESC)", "Datetime (ASC)", "Datetime (DESC)"]
BASE_MODES = {"T2VA", "I2VA", "FL2VA", "L2VA"}
IMAGE_SOURCE_MODES = ("auto", "source_image", "node_upload_or_folder")


class FlexibleOptionalInputType(dict):
    def __init__(self, fallback_type, data=None):
        super().__init__(data or {})
        self.fallback_type = fallback_type

    def __getitem__(self, key):
        if key in self.keys():
            return super().__getitem__(key)
        return (self.fallback_type,)

    def __contains__(self, key):
        return True


def _parse_frame_rate(frame_rate):
    try:
        frame_rate = float(frame_rate)
    except (TypeError, ValueError):
        frame_rate = float(FPS)
    if not 0.1 <= frame_rate <= 240.0:
        raise ValueError("MiniMax Director frame_rate must be between 0.1 and 240")
    return frame_rate


def _combine_positive_prompt(base, extra):
    base = str(base or "").strip()
    extra = str(extra or "").strip()
    if not extra:
        return base
    if not base:
        return extra
    if extra in base:
        return base
    return f"{base}\n\n{extra}"


def _parse_timeline_state(timeline_data):
    """Restore the hidden UI state without breaking execution on stale widgets."""
    default = {"version": 1, "items": [], "prompt_blocks": []}
    if isinstance(timeline_data, dict):
        state = timeline_data
    else:
        if isinstance(timeline_data, bytes):
            timeline_data = timeline_data.decode("utf-8-sig", errors="replace")
        text = str(timeline_data or "").strip()
        if not text or text.lower() in {"undefined", "null", "none"}:
            return default
        try:
            state = json.loads(text)
        except (TypeError, json.JSONDecodeError) as exc:
            preview = text[:80].replace("\r", " ").replace("\n", " ")
            print(
                "[MiniMax H3 Director] invalid hidden timeline_data was reset "
                f"to an empty timeline ({exc}); value={preview!r}"
            )
            return default
    if not isinstance(state, dict):
        print("[MiniMax H3 Director] non-object hidden timeline_data was reset to an empty timeline")
        return default
    state.setdefault("version", 1)
    if not isinstance(state.get("items"), list):
        state["items"] = []
    if not isinstance(state.get("prompt_blocks"), list):
        state["prompt_blocks"] = []
    return state


def _natural_key(value):
    import re
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(value))]


def _sort_files(items, base_path, method):
    def get_ts(name):
        try:
            return os.path.getmtime(os.path.join(base_path, name))
        except Exception:
            return float("-inf")

    if method == "Alphabetical (ASC)":
        return sorted(items)
    if method == "Alphabetical (DESC)":
        return sorted(items, reverse=True)
    if method == "Numerical (DESC)":
        return sorted(items, key=_natural_key, reverse=True)
    if method == "Datetime (ASC)":
        return sorted(items, key=get_ts)
    if method == "Datetime (DESC)":
        return sorted(items, key=get_ts, reverse=True)
    return sorted(items, key=_natural_key)


def _list_images(folder, include_subfolders=False, sort_method="Numerical (ASC)"):
    folder = os.path.abspath(str(folder).strip())
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"image folder does not exist: {folder}")
    found = []
    if include_subfolders:
        for root, _, files in os.walk(folder):
            for name in files:
                if name.lower().endswith(IMAGE_EXTENSIONS):
                    found.append(os.path.relpath(os.path.join(root, name), folder))
    else:
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if os.path.isfile(path) and name.lower().endswith(IMAGE_EXTENSIONS):
                found.append(name)
    found = _sort_files(found, folder, sort_method)
    if not found:
        raise FileNotFoundError(f"image folder has no images: {folder}")
    return [os.path.abspath(os.path.join(folder, name)) for name in found]


def _load_absolute_image(path):
    import numpy as np
    import torch
    from PIL import Image, ImageOps

    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        array = np.asarray(image, dtype=np.float32) / 255.0
    return torch.from_numpy(array).unsqueeze(0)


class MiniMaxH3Director:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (["T2VA", "I2VA", "FL2VA", "L2VA", "REF2VA"], {"default": "FL2VA"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "width": ("INT", {"default": 1344, "min": 32, "max": 8192, "step": 32}),
                "height": ("INT", {"default": 768, "min": 32, "max": 8192, "step": 32}),
                "duration": ("INT", {"default": 5, "min": 1, "max": 1000, "tooltip": "Requested seconds. MiniMax H3 is native 24fps and snaps to its 17k+5 frame grid, so actual duration can be slightly longer."}),
                "ref_image_size": (["match", "max"], {"default": "match"}),
                "timeline_data": ("STRING", {"default": "{\"version\":1,\"items\":[],\"prompt_blocks\":[]}", "multiline": False, "hidden": True}),
                "builder_state": ("STRING", {"default": "", "multiline": False, "hidden": True}),
                "frame_rate": ("STRING", {"default": "24.0", "tooltip": "Output FPS. Blank or invalid saved values fall back to 24."}),
            },
            "optional": {
                "fl2va_model": ("MODEL", {"lazy": True}),
                "ref2va_model": ("MODEL", {"lazy": True}),
                "external_width_overwrite": ("INT", {"min": 1, "max": 8192, "step": 1, "forceInput": True}),
                "external_height_overwrite": ("INT", {"min": 1, "max": 8192, "step": 1, "forceInput": True}),
                "external_prompt_overwrite": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
            },
        }

    RETURN_TYPES = ("MINIMAX_H3_DIRECTOR_GUIDE", "INT", "STRING", "INT", "INT", "MODEL", "BOOLEAN", "BOOLEAN", "FLOAT", "FLOAT")
    RETURN_NAMES = ("guide", "frame_count", "positive_prompt", "width", "height", "model", "fl2va_requested", "ref2va_requested", "native_duration", "frame_rate")
    FUNCTION = "build_guide"
    CATEGORY = "image/animation/MiniMax H3"

    @classmethod
    def VALIDATE_INPUTS(cls, input_types=None):
        return True

    def check_lazy_status(self, mode, prompt, width, height, duration, ref_image_size, timeline_data, builder_state="",
                          frame_rate=24.0, fl2va_model=None, ref2va_model=None,
                          external_width_overwrite=None, external_height_overwrite=None,
                          external_prompt_overwrite=None):
        selected_name = "ref2va_model" if mode == "REF2VA" else "fl2va_model"
        selected_model = ref2va_model if mode == "REF2VA" else fl2va_model
        return [selected_name] if selected_model is None else []

    def build_guide(self, mode, prompt, width, height, duration, ref_image_size, timeline_data, builder_state="",
                    frame_rate=24.0, fl2va_model=None, ref2va_model=None,
                    external_width_overwrite=None, external_height_overwrite=None,
                    external_prompt_overwrite=None):
        # Native MiniMax H3 uses a 17k+5 frame grid.  This exact value must be
        # retained in the guide passed to the adapter; returning an aligned UI
        # duration alone leaves native H3 conditioning at an invalid length.
        frame_rate = _parse_frame_rate(frame_rate)
        external_canvas = external_width_overwrite is not None or external_height_overwrite is not None
        if external_canvas:
            if external_width_overwrite is None or external_height_overwrite is None:
                raise ValueError("both external width overwrite and external height overwrite are required")
            width, height = int(external_width_overwrite), int(external_height_overwrite)
            if width < 1 or height < 1:
                raise ValueError("external width overwrite and external height overwrite must be positive")
        length = align_frame_count(round(int(duration) * FPS))
        if builder_state is not None and not isinstance(builder_state, str):
            if fl2va_model is None:
                fl2va_model = builder_state
                builder_state = ""
            else:
                raise ValueError("builder_state must be JSON text")
        state = _parse_timeline_state(timeline_data)
        try:
            builder = json.loads(builder_state) if builder_state else state.get("builder_state", {})
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"MiniMax Director builder_state is invalid JSON: {exc}") from exc
        if not isinstance(builder, dict):
            builder = {}
        merged = default_builder_state(mode)
        merged.update(builder)
        merged["ref"] = {**default_builder_state(mode)["ref"], **(builder.get("ref") or {})}
        normalize_ref_schema(merged["ref"])
        merged["mode"] = mode
        merged["duration"] = duration
        migrated_legacy_prompt = migrate_legacy_prompt(merged, state, prompt)

        items = sorted(enumerate(state.get("items", [])), key=lambda pair: (int(pair[1].get("order", pair[0])), pair[0]))
        # Preserve incompatible REF2VA media in workflow state so it returns when the
        # user switches back, but never feed it to FL2VA.
        if mode in BASE_MODES:
            items = [pair for pair in items if pair[1].get("enabled", True) and pair[1].get("type") == "image"][:2]
        images, videos, audios = [], [], []
        first_frame = last_frame = None
        ref_video_audios, ref_images, ref_videos, ref_audios = {}, {}, {}, {}
        try:
            import folder_paths
            input_directory = folder_paths.get_input_directory()
        except (ImportError, AttributeError):
            input_directory = None
        image_index = 0
        for _, item in items:
            if not item.get("enabled", True):
                continue
            kind = item.get("type")
            value = item.get("value", item.get("tensor"))
            if value is None:
                continue
            trim_start = float(item.get("trim_start", 0.0))
            trim_end = item.get("trim_end")
            video_mode = item.get("media_mode", "video")
            if kind == "video" and video_mode not in {"video", "audio", "video_audio"}:
                raise ValueError(f"unsupported video media mode: {video_mode}")
            include_video = kind != "video" or video_mode in {"video", "video_audio"}
            include_embedded_audio = kind == "video" and video_mode in {"audio", "video_audio"}
            embedded_audio = None
            if isinstance(value, str) and input_directory:
                if kind == "image":
                    value = load_image(value, input_directory)
                elif kind == "audio":
                    trim_start = float(item.get("trim_start", 0.0))
                    trim_end = item.get("trim_end")
                    value = load_audio(value, input_directory, trim_start=trim_start,
                                       trim_end=float(trim_end) if trim_end is not None else None)
                    item = {**item, "duration": audio_duration(value)}
                elif kind == "video":
                    if include_video:
                        value = load_video(value, input_directory, trim_start=trim_start,
                                           trim_end=float(trim_end) if trim_end is not None else None)
                        item = {**item, "duration": float(value.shape[0]) / 24.0}
                    if include_embedded_audio:
                        embedded_audio = load_embedded_video_audio(
                            item["value"], input_directory, trim_start=trim_start,
                            trim_end=float(trim_end) if trim_end is not None else None)
                        item = {**item, "audio_duration": audio_duration(embedded_audio)}
            attached_audio = item.get("audio")
            if isinstance(attached_audio, str) and input_directory:
                attached_audio = load_audio(attached_audio, input_directory, trim_start=trim_start,
                                           trim_end=float(trim_end) if trim_end is not None else None)
                item = {**item, "audio": attached_audio, "audio_duration": audio_duration(attached_audio)}
            if mode in BASE_MODES:
                if kind != "image":
                    continue
                target = "first" if image_index == 0 else "last"
                image_index += 1
                if mode == "T2VA":
                    continue
                if mode == "I2VA":
                    first_frame = value
                elif mode == "L2VA":
                    last_frame = value
                elif target == "last":
                    if last_frame is not None:
                        raise ValueError("FL2VA accepts at most two images")
                    last_frame = value
                else:
                    if first_frame is not None:
                        raise ValueError("FL2VA accepts at most two images")
                    first_frame = value
                images.append(value)
            elif kind == "image":
                key = f"ref_image_{len(ref_images) + 1}"
                ref_images[key] = value
                images.append(item)
            elif kind == "video":
                if include_video:
                    key = f"ref_video_{len(ref_videos) + 1}"
                    ref_videos[key] = value
                    videos.append(item)
                video_audio = embedded_audio if include_embedded_audio else item.get("audio")
                if video_audio is not None:
                    audio_item = {"duration": item.get("audio_duration", item.get("duration"))}
                    if include_video:
                        ref_video_audios[f"ref_video_audio_{len(ref_videos)}"] = video_audio
                    else:
                        ref_audios[f"ref_audio_{len(ref_audios) + 1}"] = video_audio
                    audios.append(audio_item)
            elif kind == "audio":
                ref_audios[f"ref_audio_{len(ref_audios) + 1}"] = value
                audios.append(item)
        if mode == "REF2VA":
            validate_reference_limits(images=images, videos=videos, audios=audios)
        blocks = state.get("prompt_blocks", [])
        external_prompt_active = isinstance(external_prompt_overwrite, str) and external_prompt_overwrite.strip()
        if external_prompt_active:
            resolved = external_prompt_overwrite.strip()
        else:
            resolved = build_prompt(merged)
        if (not migrated_legacy_prompt and not external_prompt_active
                and not any(str(merged.get(key) or "").strip() for key in ("imd", "soundscape")) and mode != "REF2VA"):
            resolved = assemble_prompt(prompt, blocks)
        elif not external_prompt_active:
            resolved = _combine_positive_prompt(resolved, prompt)
        guide = {
            "version": 2, "mode": mode, "prompt": prompt, "prompt_blocks": blocks,
            "timeline": [
                {key: item.get(key) for key in ("id", "type", "start", "duration", "order", "trim_start", "trim_end") if key in item}
                for _, item in items if item.get("enabled", True)
            ],
            "resolved_prompt": resolved, "width": width, "height": height, "length": length,
            "ref_image_size": ref_image_size,
            "first_frame": first_frame, "last_frame": last_frame,
            "ref_images": ref_images if mode == "REF2VA" else {},
            "ref_videos": ref_videos if mode == "REF2VA" else {},
            "ref_video_audios": ref_video_audios if mode == "REF2VA" else {},
            "ref_audios": ref_audios if mode == "REF2VA" else {},
            "builder_state": merged,
            "prompt_payload": {"mode": mode, "full_prompt": resolved, "is_ref_mode": mode == "REF2VA", "subject_definitions": merged["ref"].get("subject_defs", []), "summary": merged["ref"].get("summary_text", ""), "retention_analysis": merged["ref"].get("retention", []), "detailed_description": {"style_line": merged["ref"].get("style_line", ""), "detail": merged["ref"].get("detail", "")}, "overall_soundscape": merged["ref"].get("soundscape", "") if mode == "REF2VA" else merged.get("soundscape", ""), "non_diegetic_music": merged["ref"].get("music", "N/A") if mode == "REF2VA" else merged.get("music", "N/A"), "imd": merged.get("imd", ""), "p2_shot": merged.get("p2_shot", ""), "last_shot": merged.get("last_shot", "")},
        }
        normalize_guide(guide)
        for issue in validate_builder_state(merged):
            print(f"[MiniMax H3 Director] [{issue['level'].upper()}] {issue['msg']}")
        selected_model = ref2va_model if mode == "REF2VA" else fl2va_model
        return (guide, length, resolved, int(width), int(height), selected_model,
                mode in BASE_MODES, mode == "REF2VA", float(length) / FPS, frame_rate)


class MiniMaxH3DirectorFolderBatch:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (["T2VA", "I2VA", "FL2VA", "L2VA", "REF2VA"], {"default": "FL2VA"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "width": ("INT", {"default": 1344, "min": 32, "max": 8192, "step": 32}),
                "height": ("INT", {"default": 768, "min": 32, "max": 8192, "step": 32}),
                "duration": ("INT", {"default": 5, "min": 1, "max": 1000, "tooltip": "Requested seconds. MiniMax H3 is native 24fps and snaps to its 17k+5 frame grid, so actual duration can be slightly longer."}),
                "ref_image_size": (["match", "max"], {"default": "match"}),
                "timeline_data": ("STRING", {"default": "{\"version\":1,\"items\":[],\"prompt_blocks\":[]}", "multiline": False, "hidden": True}),
                "image_folder": ("STRING", {"default": ""}),
                "end_frame_folder": ("STRING", {"default": ""}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "include_subfolders": ("BOOLEAN", {"default": False}),
                "sort_method": (SORT_METHODS, {"default": "Numerical (ASC)"}),
                "media_prompt": ("STRING", {"default": "", "multiline": True}),
                "autosize_enabled": ("BOOLEAN", {"default": False}),
                "autosize_max_size": ("INT", {"default": 1280, "min": 0, "max": 16384, "step": 8}),
                "autosize_min_size": ("INT", {"default": 720, "min": 0, "max": 16384, "step": 8}),
                "autosize_divisible_by": ("INT", {"default": 32, "min": 1, "max": 512, "step": 1}),
                "builder_state": ("STRING", {"default": "", "multiline": False, "hidden": True}),
                "frame_rate": ("STRING", {"default": "24.0", "tooltip": "Output FPS. Blank or invalid saved values fall back to 24."}),
            },
            "optional": FlexibleOptionalInputType("IMAGE", {
                "source_image": ("IMAGE",),
                "end_frame_image": ("IMAGE",),
                "fl2va_model": ("MODEL", {"lazy": True}),
                "ref2va_model": ("MODEL", {"lazy": True}),
                "external_width_overwrite": ("INT", {"min": 1, "max": 8192, "step": 1, "forceInput": True}),
                "external_height_overwrite": ("INT", {"min": 1, "max": 8192, "step": 1, "forceInput": True}),
                "external_prompt_overwrite": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
            }),
        }

    RETURN_TYPES = (
        "MINIMAX_H3_DIRECTOR_GUIDE", "INT", "STRING", "INT", "INT", "MODEL", "BOOLEAN", "BOOLEAN",
        "IMAGE", "FLOAT", "FLOAT"
    )
    RETURN_NAMES = (
        "guide", "frame_count", "positive_prompt", "width", "height", "model", "fl2va_requested", "ref2va_requested",
        "current_image", "native_duration", "frame_rate"
    )
    FUNCTION = "build_guide"
    CATEGORY = "image/animation/MiniMax H3"

    @classmethod
    def VALIDATE_INPUTS(cls, input_types=None):
        return True

    def check_lazy_status(self, mode, prompt, width, height, duration, ref_image_size, timeline_data,
                          image_folder, end_frame_folder, seed, include_subfolders, sort_method,
                          media_prompt, autosize_enabled=False, autosize_max_size=1280,
                          autosize_min_size=720, autosize_divisible_by=32, builder_state="",
                          frame_rate=24.0, image_source_mode="auto",
                          source_image=None, end_frame_image=None,
                          fl2va_model=None, ref2va_model=None,
                          external_width_overwrite=None, external_height_overwrite=None,
                          external_prompt_overwrite=None, **extra_inputs):
        selected_name = "ref2va_model" if mode == "REF2VA" else "fl2va_model"
        selected_model = ref2va_model if mode == "REF2VA" else fl2va_model
        return [selected_name] if selected_model is None else []

    def _parse_state(self, timeline_data):
        return _parse_timeline_state(timeline_data)

    def _single_image_batch(self, image):
        if image is None:
            return None
        try:
            if len(image.shape) == 3:
                return image.unsqueeze(0)
            if len(image.shape) == 4 and image.shape[0] > 1:
                return image[:1]
        except Exception:
            pass
        return image

    def _uploaded_images_from_state(self, state, input_directory):
        image_items = sorted(
            (
                pair for pair in enumerate(state.get("items", []) or [])
                if pair[1].get("enabled", True) and pair[1].get("type") == "image"
            ),
            key=lambda pair: (pair[1].get("slot", pair[0]), int(pair[1].get("order", pair[0])), pair[0]),
        )
        frames = []
        for _, item in image_items[:2]:
            value = item.get("value", item.get("tensor"))
            if value is None:
                continue
            if isinstance(value, str) and input_directory:
                value = load_image(value, input_directory)
            frame = self._single_image_batch(value)
            if frame is not None:
                frames.append((frame, str(item.get("value", "node_uploaded_image"))))
        if not frames:
            return None, None, "", ""
        first_frame, first_name = frames[0]
        if len(frames) > 1:
            last_frame, last_name = frames[1]
        else:
            last_frame, last_name = None, ""
        return first_frame, last_frame, first_name, last_name

    def _extra_ref_images(self, extra_inputs):
        numbered = []
        for key, value in (extra_inputs or {}).items():
            if not str(key).startswith("ref_image_") or value is None:
                continue
            suffix = str(key).rsplit("_", 1)[-1]
            if not suffix.isdigit():
                continue
            frame = self._single_image_batch(value)
            if frame is not None:
                numbered.append((int(suffix), frame))
        return sorted(numbered, key=lambda pair: pair[0])

    def _selected_images(self, image_folder, end_frame_folder, seed, include_subfolders, sort_method,
                         source_image=None, end_frame_image=None, uploaded_frames=None,
                         image_source_mode="auto", use_end_frame=True):
        source_mode = str(image_source_mode or "auto").strip()
        if source_mode not in IMAGE_SOURCE_MODES:
            source_mode = "auto"
        source_image = self._single_image_batch(source_image)
        end_frame_image = self._single_image_batch(end_frame_image) if use_end_frame else None
        uploaded_first, uploaded_last, uploaded_first_name, uploaded_last_name = uploaded_frames or (None, None, "", "")
        if not use_end_frame:
            uploaded_last, uploaded_last_name = None, ""
        if source_mode in {"auto", "source_image"} and source_image is not None:
            first_frame = source_image
            last_frame = end_frame_image
            print(
                "[MiniMax H3 Director Folder Batch] "
                + ("using connected source_image + end_frame_image" if last_frame is not None else "using connected source_image")
            )
            return first_frame, last_frame, "connected_source_image", "connected_end_frame_image" if last_frame is not None else "", int(seed)
        if source_mode == "source_image":
            raise ValueError("image_source_mode is source_image, but source_image is not connected")

        if source_mode in {"auto", "node_upload_or_folder"} and uploaded_first is not None:
            first_frame = uploaded_first
            last_frame = uploaded_last if uploaded_last is not None else end_frame_image
            last_name = uploaded_last_name if uploaded_last is not None else ("connected_end_frame_image" if end_frame_image is not None else "")
            print(
                "[MiniMax H3 Director Folder Batch] "
                + ("using node-uploaded image + end image" if last_frame is not None else "using node-uploaded image")
            )
            return first_frame, last_frame, uploaded_first_name or "node_uploaded_image", last_name, int(seed)

        if not str(image_folder).strip():
            if end_frame_image is not None:
                raise ValueError(
                    "source_image is not connected. end_frame_image cannot be used alone; "
                    "connect a start image to source_image or set image_folder"
                )
            raise ValueError("source_image is not connected and image_folder is empty")
        images = _list_images(image_folder, include_subfolders, sort_method)
        index = int(seed) % len(images)
        first_path = images[index]
        first_frame = _load_absolute_image(first_path)

        last_frame = None
        last_path = ""
        if end_frame_image is not None:
            last_frame = end_frame_image
            last_path = "connected_end_frame_image"
        elif use_end_frame and str(end_frame_folder).strip():
            try:
                end_images = _list_images(end_frame_folder, include_subfolders, sort_method)
                if end_images:
                    last_path = end_images[index % len(end_images)]
                    last_frame = _load_absolute_image(last_path)
            except FileNotFoundError as exc:
                print(f"[MiniMax H3 Director Folder Batch] end_frame_folder skipped: {exc}")

        print(
            "[MiniMax H3 Director Folder Batch] "
            f"source {index + 1}/{len(images)}: {os.path.basename(first_path)}"
            + (f", end: {os.path.basename(last_path)}" if last_path else "")
        )
        return first_frame, last_frame, first_path, last_path, index

    def _round_to_divisible(self, value, divisible_by):
        divisible_by = max(1, int(divisible_by))
        return max(divisible_by, int(round(float(value) / divisible_by)) * divisible_by)

    def _autosize_dimensions(self, image, width, height, enabled, max_size, min_size, divisible_by):
        if not enabled:
            return int(width), int(height)
        source_height = int(image.shape[1])
        source_width = int(image.shape[2])
        if source_width <= 0 or source_height <= 0:
            return int(width), int(height)

        scale = 1.0
        max_size = int(max_size)
        min_size = int(min_size)
        if max_size > 0:
            scale = float(max_size) / float(max(source_width, source_height))
        if min_size > 0 and min(source_width, source_height) * scale < min_size:
            scale = float(min_size) / float(min(source_width, source_height))

        target_width = self._round_to_divisible(source_width * scale, divisible_by)
        target_height = self._round_to_divisible(source_height * scale, divisible_by)
        print(
            "[MiniMax H3 Director Folder Batch] "
            f"autosize {source_width}x{source_height} -> {target_width}x{target_height}"
        )
        return target_width, target_height

    def _resize_image_exact(self, image, width, height):
        if image is None:
            return None
        source_height = int(image.shape[1])
        source_width = int(image.shape[2])
        width = int(width)
        height = int(height)
        if source_width == width and source_height == height:
            return image
        import torch.nn.functional as F

        resized = F.interpolate(
            image.movedim(-1, 1),
            size=(height, width),
            mode="bicubic",
            align_corners=False,
        )
        return resized.movedim(1, -1).clamp(0.0, 1.0)

    def build_guide(self, mode, prompt, width, height, duration, ref_image_size, timeline_data,
                    image_folder, end_frame_folder, seed, include_subfolders, sort_method,
                    media_prompt, autosize_enabled=False, autosize_max_size=1280,
                    autosize_min_size=720, autosize_divisible_by=32, builder_state="",
                    frame_rate=24.0, image_source_mode="auto",
                    source_image=None, end_frame_image=None,
                    fl2va_model=None, ref2va_model=None,
                    external_width_overwrite=None, external_height_overwrite=None,
                    external_prompt_overwrite=None, **extra_inputs):
        frame_rate = _parse_frame_rate(frame_rate)
        external_canvas = external_width_overwrite is not None or external_height_overwrite is not None
        if external_canvas:
            if external_width_overwrite is None or external_height_overwrite is None:
                raise ValueError("both external width overwrite and external height overwrite are required")
            width, height = int(external_width_overwrite), int(external_height_overwrite)
            if width < 1 or height < 1:
                raise ValueError("external width overwrite and external height overwrite must be positive")
        length = align_frame_count(round(int(duration) * FPS))
        state = self._parse_state(timeline_data)
        try:
            builder = json.loads(builder_state) if builder_state else state.get("builder_state", {})
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"MiniMax Director builder_state is invalid JSON: {exc}") from exc
        if not isinstance(builder, dict):
            builder = {}
        merged = default_builder_state(mode)
        merged.update(builder)
        merged["ref"] = {**default_builder_state(mode)["ref"], **(builder.get("ref") or {})}
        normalize_ref_schema(merged["ref"])
        merged["mode"] = mode
        merged["duration"] = duration
        migrated_legacy_prompt = migrate_legacy_prompt(merged, state, prompt)

        try:
            import folder_paths
            input_directory = folder_paths.get_input_directory()
        except (ImportError, AttributeError):
            input_directory = None
        uploaded_frames = self._uploaded_images_from_state(state, input_directory)
        image_source_mode = state.get("image_source_mode", image_source_mode)
        use_end_frame = bool(state.get("use_end_frame", True))
        first_frame, last_frame, first_path, last_path, index = self._selected_images(
            image_folder, end_frame_folder, seed, include_subfolders, sort_method,
            source_image, end_frame_image, uploaded_frames, image_source_mode, use_end_frame
        )
        width, height = self._autosize_dimensions(
            first_frame, width, height, autosize_enabled and not external_canvas,
            autosize_max_size, autosize_min_size, autosize_divisible_by
        )
        if autosize_enabled and not external_canvas:
            first_frame = self._resize_image_exact(first_frame, width, height)
            last_frame = self._resize_image_exact(last_frame, width, height)

        items = sorted(enumerate(state.get("items", [])), key=lambda pair: (int(pair[1].get("order", pair[0])), pair[0]))
        items = [pair for pair in items if pair[1].get("enabled", True)]

        blocks = list(state.get("prompt_blocks", []) or [])
        if str(media_prompt).strip():
            blocks.append({
                "id": "folder_media_prompt",
                "type": "prompt",
                "start": 0,
                "duration": int(duration),
                "order": 0,
                "enabled": True,
                "text": str(media_prompt),
            })
        external_prompt_active = isinstance(external_prompt_overwrite, str) and external_prompt_overwrite.strip()
        if external_prompt_active:
            resolved = external_prompt_overwrite.strip()
        else:
            resolved = build_prompt(merged)
        if (not migrated_legacy_prompt and not external_prompt_active
                and not any(str(merged.get(key) or "").strip() for key in ("imd", "soundscape")) and mode != "REF2VA"):
            resolved = assemble_prompt(prompt, blocks)
            blocks_already_included = True
        elif not external_prompt_active:
            resolved = _combine_positive_prompt(resolved, prompt)
            blocks_already_included = False
        else:
            blocks_already_included = False
        if blocks and not external_prompt_active and not blocks_already_included:
            block_text = assemble_prompt("", blocks)
            if block_text.strip():
                resolved = f"{resolved}\n\n{block_text}" if resolved.strip() else block_text

        if mode in BASE_MODES:
            ref_images = {}
            ref_videos = {}
            ref_video_audios = {}
            ref_audios = {}
        else:
            ref_images = {"ref_image_1": first_frame}
            ref_videos = {}
            ref_video_audios = {}
            ref_audios = {}
            images, videos, audios = [{"duration": int(duration)}], [], []
            if last_frame is not None:
                ref_images["ref_image_2"] = last_frame
                images.append({"duration": int(duration)})
            for extra_ref_index, extra_ref in self._extra_ref_images(extra_inputs):
                ref_images[f"ref_image_{extra_ref_index}"] = extra_ref
                images.append({"duration": int(duration)})
            selected_uploaded_values = {
                value for value in (first_path, last_path)
                if value and value not in {"connected_source_image", "connected_end_frame_image"}
            }
            using_connected_source = first_path == "connected_source_image"
            type_order = {"image": 0, "video": 1, "audio": 2}
            for _, item in sorted(items, key=lambda pair: (type_order.get(pair[1].get("type"), 3), pair[1].get("slot", pair[0]), pair[0])):
                kind, value = item.get("type"), item.get("value", item.get("tensor"))
                if value is None:
                    continue
                if kind == "image" and using_connected_source:
                    continue
                if kind == "image" and isinstance(value, str) and value in selected_uploaded_values:
                    continue
                trim_start = float(item.get("trim_start", 0))
                trim_end = item.get("trim_end")
                trim_end = float(trim_end) if trim_end is not None else None
                video_mode = item.get("media_mode", "video")
                if kind == "image":
                    value = load_image(value, input_directory) if isinstance(value, str) and input_directory else value
                    ref_images[f"ref_image_{len(ref_images) + 1}"] = value
                    images.append(item)
                elif kind == "audio":
                    value = load_audio(value, input_directory, trim_start=trim_start, trim_end=trim_end) if isinstance(value, str) and input_directory else value
                    ref_audios[f"ref_audio_{len(ref_audios) + 1}"] = value
                    audios.append({**item, "duration": audio_duration(value) if isinstance(value, dict) else item.get("duration")})
                elif kind == "video":
                    if video_mode not in {"video", "audio", "video_audio"}:
                        raise ValueError(f"unsupported video media mode: {video_mode}")
                    if video_mode in {"video", "video_audio"}:
                        video = load_video(value, input_directory, trim_start=trim_start, trim_end=trim_end) if isinstance(value, str) and input_directory else value
                        ref_videos[f"ref_video_{len(ref_videos) + 1}"] = video
                        video_duration = float(video.shape[0]) / FPS if hasattr(video, "shape") else item.get("duration")
                        videos.append({**item, "duration": video_duration})
                    if video_mode in {"audio", "video_audio"}:
                        audio = load_embedded_video_audio(value, input_directory, trim_start=trim_start, trim_end=trim_end) if isinstance(value, str) and input_directory else item.get("audio")
                        if video_mode == "video_audio":
                            ref_video_audios[f"ref_video_audio_{len(ref_videos)}"] = audio
                        else:
                            ref_audios[f"ref_audio_{len(ref_audios) + 1}"] = audio
                        audios.append({**item, "duration": audio_duration(audio) if isinstance(audio, dict) else item.get("duration")})
                    attached_audio = item.get("audio")
                    if attached_audio is not None and video_mode not in {"audio", "video_audio"}:
                        if isinstance(attached_audio, str) and input_directory:
                            attached_audio = load_audio(attached_audio, input_directory, trim_start=trim_start, trim_end=trim_end)
                        if video_mode == "video" and ref_videos:
                            ref_video_audios[f"ref_video_audio_{len(ref_videos)}"] = attached_audio
                        else:
                            ref_audios[f"ref_audio_{len(ref_audios) + 1}"] = attached_audio
                        audios.append({**item, "duration": audio_duration(attached_audio) if isinstance(attached_audio, dict) else item.get("duration")})
            validate_reference_limits(images=images, videos=videos, audios=audios)

        if mode == "T2VA":
            first_for_mode = None
            last_for_mode = None
        elif mode == "I2VA":
            first_for_mode = first_frame
            last_for_mode = None
        elif mode == "L2VA":
            first_for_mode = None
            last_for_mode = last_frame if last_frame is not None else first_frame
        else:
            first_for_mode = first_frame
            last_for_mode = last_frame

        guide = {
            "version": 2,
            "mode": mode,
            "prompt": prompt,
            "prompt_blocks": blocks,
            "timeline": [
                {
                    "id": "folder_image",
                    "type": "image",
                    "start": 0,
                    "duration": int(duration),
                    "order": 0,
                    "path": first_path,
                    "source_index": index,
                },
                *([
                    {
                        "id": "folder_end_frame",
                        "type": "image",
                        "start": 0,
                        "duration": int(duration),
                        "order": 1,
                        "path": last_path,
                        "source_index": index,
                    }
                ] if last_path else []),
                *[
                    {key: item.get(key) for key in ("id", "type", "start", "duration", "order", "trim_start", "trim_end") if key in item}
                    for _, item in items
                ],
            ],
            "resolved_prompt": resolved,
            "width": width,
            "height": height,
                "length": length,
                "ref_image_size": ref_image_size,
                "input_scaling": "external" if external_canvas else "folder_autosize" if autosize_enabled else "Off",
            "first_frame": first_for_mode if mode in BASE_MODES else None,
            "last_frame": last_for_mode if mode in BASE_MODES else None,
            "ref_images": ref_images,
            "ref_videos": ref_videos,
            "ref_video_audios": ref_video_audios,
            "ref_audios": ref_audios,
            "builder_state": merged,
            "prompt_payload": {"mode": mode, "full_prompt": resolved, "is_ref_mode": mode == "REF2VA", "subject_definitions": merged["ref"].get("subject_defs", []), "summary": merged["ref"].get("summary_text", ""), "retention_analysis": merged["ref"].get("retention", []), "detailed_description": {"style_line": merged["ref"].get("style_line", ""), "detail": merged["ref"].get("detail", "")}, "overall_soundscape": merged["ref"].get("soundscape", "") if mode == "REF2VA" else merged.get("soundscape", ""), "non_diegetic_music": merged["ref"].get("music", "N/A") if mode == "REF2VA" else merged.get("music", "N/A"), "imd": merged.get("imd", ""), "p2_shot": merged.get("p2_shot", ""), "last_shot": merged.get("last_shot", "")},
        }
        normalize_guide(guide)
        for issue in validate_builder_state(merged):
            print(f"[MiniMax H3 Director Folder Batch] [{issue['level'].upper()}] {issue['msg']}")
        selected_model = ref2va_model if mode == "REF2VA" else fl2va_model
        return (guide, length, resolved, int(width), int(height), selected_model,
                mode in BASE_MODES, mode == "REF2VA", first_frame, float(length) / FPS, frame_rate)


NODE_CLASS_MAPPINGS = {
    "WildcardMiniMaxH3Director": MiniMaxH3Director,
    "WildcardMiniMaxH3DirectorFolderBatch": MiniMaxH3DirectorFolderBatch,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "WildcardMiniMaxH3Director": "Wildcard MiniMax H3 Director",
    "WildcardMiniMaxH3DirectorFolderBatch": "Wildcard MiniMax H3 Director (Folder Batch)",
}
