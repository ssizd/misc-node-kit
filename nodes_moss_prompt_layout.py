"""Compile text layout blocks to the installed MOSS-Image layout contract."""

import json
import math
import re


BLOCK = re.compile(r"@(char|cha|object)\s*\[", re.IGNORECASE)
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
DIRECTIVE = re.compile(r"@(pos|size|box)\s*\((.*?)\)\s*", re.IGNORECASE)
RESOLUTION = re.compile(r"\bresolution\s*:\s*(\d+)\s*[xX\u00d7]\s*(\d+)\b", re.IGNORECASE)


def _fields(text):
    fields, start, brackets, quote = [], 0, [], None
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        # Apostrophes in ordinary descriptions are not string delimiters.
        if char == '"':
            quote = char
        elif char in "([{":
            brackets.append(char)
        elif char in ")]}":
            if not brackets or "([{".index(brackets.pop()) != ")]}".index(char):
                raise ValueError("Unbalanced brackets in a layout block.")
        elif char == "," and not brackets:
            fields.append(text[start:index].strip())
            start = index + 1
    if quote or brackets:
        raise ValueError("Unclosed quote or brackets in a layout block.")
    fields.append(text[start:].strip())
    return fields


def _blocks(text):
    blocks, summary, cursor = [], [], 0
    while match := BLOCK.search(text, cursor):
        summary.append(text[cursor:match.start()])
        depth, end, quote, escaped = 1, match.end(), False, False
        while end < len(text) and depth:
            char = text[end]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = not quote
            elif not quote:
                depth += (char == "[") - (char == "]")
            end += 1
        if depth:
            raise ValueError("A @char/@object block is missing its closing ].")
        blocks.append((match.group(1).lower(), _fields(text[match.end():end - 1])))
        if len(blocks) > 128:
            raise ValueError("At most 128 layout blocks are supported.")
        cursor = end
    summary.append(text[cursor:])
    return blocks, "".join(summary)


def _numbers(value, count, label):
    parts = value.split(",")
    if len(parts) != count or any(not re.fullmatch(NUMBER, part.strip()) for part in parts):
        raise ValueError(f"@{label} requires {count} normalized numbers.")
    numbers = [float(part) for part in parts]
    if any(not math.isfinite(number) or not 0 <= number <= 1 for number in numbers):
        raise ValueError(f"@{label} coordinates must be between 0 and 1.")
    return numbers


def split_layouts(text, action_format="auto"):
    text = str(text)
    if action_format not in ("auto", "lines", "---"):
        raise ValueError("Unknown action format.")
    if action_format == "lines":
        return [line.strip() for line in text.splitlines() if line.strip()]
    separated = re.split(r"(?m)^\s*---\s*$", text)
    if len(separated) > 1 or action_format == "---":
        return [part.strip() for part in separated if part.strip()]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # Wildcard loaders emit one action per line, including plain scene lines.
    # Preserve a hand-written scene followed by standalone character blocks.
    if len(lines) > 1:
        complete = True
        standalone_blocks = False
        for line in lines:
            try:
                blocks, summary = _blocks(line)
            except ValueError:
                complete = False
                break
            if blocks and not summary.strip(" ,\t\r"):
                standalone_blocks = True
            if RESOLUTION.fullmatch(line):
                complete = False
                break
        if complete and not standalone_blocks:
            return lines
    return [text.strip()] if text.strip() else []


def male_identity(value):
    match = re.fullmatch(r"boy([1-9][0-9]*)?", value, re.IGNORECASE)
    return int(match.group(1) or 1) if match else None


def layout_blocks(text, fallback=False, separate_male=False):
    blocks, summary = _blocks(str(text))
    if fallback and not any(kind != "object" for kind, _ in blocks):
        # No character slots always means one wildcard character. The action
        # is not inspected for gender or person counts in this mode.
        blocks.append(("char", ["boy1" if separate_male else "1"]))
    return blocks, summary


def select_character_set(text, character_list="", seed=0, action_format="auto", male_character_list=""):
    actions = split_layouts(text, action_format)
    if not actions:
        actions = [""]
    males = [line.strip() for line in str(male_character_list or "").splitlines() if line.strip()]
    characters = [line.strip() for line in str(character_list or "").splitlines() if line.strip()]
    identities, male_ids = [], []
    for action in actions:
        blocks, _ = layout_blocks(action, fallback=True, separate_male=bool(males) and not characters)
        ids = sorted({int(fields[0]) for kind, fields in blocks
                      if kind != "object" and fields and re.fullmatch(r"[0-9]+", fields[0])})
        if 0 in ids:
            raise ValueError("Numeric character IDs start at 1.")
        identities.append(ids)
        male_ids.append(sorted({male_identity(fields[0]) for kind, fields in blocks
                                if kind != "object" and fields and male_identity(fields[0]) is not None}))
    stride = max(map(len, identities), default=0)
    if characters and stride > len(characters):
        raise ValueError(f"This layout needs {stride} characters, but the list has only {len(characters)} lines.")
    female_sets = max(1, len(characters) // stride) if stride else 1
    male_stride = max(map(len, male_ids), default=0)
    if males and male_stride > len(males):
        raise ValueError(f"This layout needs {male_stride} male characters, but the male list has only {len(males)} lines.")
    male_sets = max(1, len(males) // male_stride) if male_stride else 1
    set_count = female_sets * male_sets
    cursor = int(seed) % (len(actions) * set_count)
    set_index, action_index = divmod(cursor, len(actions))
    female_index, male_index = set_index % female_sets, set_index // female_sets
    start = female_index * stride
    selected = {str(identity): characters[start + slot]
                for slot, identity in enumerate(identities[action_index])} if characters else {}
    if males:
        male_start = male_index * male_stride
        selected.update({f"boy{identity}": males[male_start + slot]
                         for slot, identity in enumerate(male_ids[action_index])})
    report = f"Set {set_index + 1}/{set_count}; layout {action_index + 1}/{len(actions)}; characters per set: {stride}; total combinations: {set_count * len(actions)}"
    if characters and stride:
        report += f"; unused trailing lines: {len(characters) % stride}"
    if males and male_stride:
        report += f"; male set {male_index + 1}/{male_sets}; males per set: {male_stride}; unused male lines: {len(males) % male_stride}"
    if selected:
        report += "\n" + "\n".join(f"{identity}: {caption}" for identity, caption in selected.items())
    return actions[action_index], selected, report


def compile_layout(text, width=1024, height=1024, box_width=0.42, box_height=0.85, character_map=None):
    blocks, summary = layout_blocks(text, fallback=bool(character_map),
                                    separate_male=any(male_identity(key) is not None for key in (character_map or {})))
    resolution = RESOLUTION.findall(summary)
    if resolution:
        width, height = map(int, resolution[-1])
        summary = RESOLUTION.sub("", summary)
    width, height = int(width), int(height)
    if not 16 <= width <= 16384 or not 16 <= height <= 16384:
        raise ValueError("Resolution must be between 16 and 16384 pixels per side.")
    if not all(math.isfinite(float(value)) and 0 < float(value) <= 1 for value in (box_width, box_height)):
        raise ValueError("Default box sizes must be greater than 0 and at most 1.")
    summary = re.sub(r",\s*,+", ", ", summary).strip(" ,\n\r\t")
    elements, items, characters = [], [], []
    for index, (kind, fields) in enumerate(blocks):
        if not fields or not fields[0]:
            raise ValueError("Each layout block needs an identifier followed by a description.")
        identity = str(int(fields[0])) if re.fullmatch(r"[0-9]+", fields[0]) else fields[0]
        if male_identity(identity) is not None:
            identity = f"boy{male_identity(identity)}"
        appearance = (character_map or {}).get(identity, "") if kind != "object" else ""
        desc, directives = ([appearance] if appearance else []), {}
        for field in fields[1:]:
            directive = DIRECTIVE.fullmatch(field)
            if directive:
                name = directive.group(1).lower()
                if name in directives:
                    raise ValueError(f"Duplicate @{name} in layout block {index + 1}.")
                directives[name] = _numbers(directive.group(2), 4 if name == "box" else 2, name)
            elif field.startswith(("@pos", "@size", "@box")):
                raise ValueError(f"Malformed layout coordinates in block {index + 1}.")
            elif field:
                desc.append(field)
        caption = ", ".join(desc)
        if not caption:
            raise ValueError(f"Layout block {index + 1} has no description.")
        if "box" in directives:
            if "pos" in directives or "size" in directives:
                raise ValueError("Use @box OR @pos with optional @size in a block.")
            x, y, w, h = directives["box"]
        else:
            cx, cy = directives.get("pos", [(index + 0.5) / len(blocks), 0.5])
            default_width = min(float(box_width), 0.9 / len(blocks)) if "pos" not in directives else float(box_width)
            w, h = directives.get("size", [default_width, float(box_height)])
            # Preserve box size near an edge by shifting it inside the canvas.
            x = max(0.0, min(1.0 - w, cx - w / 2))
            y = max(0.0, min(1.0 - h, cy - h / 2))
        if w <= 0 or h <= 0:
            raise ValueError("Box width and height must be greater than zero.")
        bbox = [round(y * 1000), round(x * 1000), round(min(1, y + h) * 1000), round(min(1, x + w) * 1000)]
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            raise ValueError("A box lies outside the canvas or is too small.")
        elements.append({"type": "obj", "bbox": bbox, "desc": caption})
        label = "object" if kind == "object" else "character"
        if label == "character":
            characters.append(str(index + 1))
        y0, x0, y1, x1 = bbox
        items.append({"label": label, "caption": caption, "bbox": [
            math.floor(round(y0 * height / 1000, 9)) - height // 2,
            math.floor(round(x0 * width / 1000, 9)) - width // 2,
            math.ceil(round(y1 * height / 1000, 9)) - height // 2,
            math.ceil(round(x1 * width / 1000, 9)) - width // 2,
        ]})
    result = json.dumps({"summary": {"caption": summary}, "items": items,
                         "bbox_coord_space": "abs_centralized", "bbox_format": "yxyx"},
                        ensure_ascii=False, separators=(",", ":")) if items else summary
    return result, elements, summary, ", ".join(characters), width, height


def readable_layout(action, result, character_map=None):
    blocks, _ = layout_blocks(action, fallback=True,
                              separate_male=any(male_identity(key) is not None for key in (character_map or {})))
    sections = [f"Resolution: {result[4]} x {result[5]}", "[Scene]\n" + result[2]]
    for index, ((kind, fields), element) in enumerate(zip(blocks, result[1]), 1):
        y0, x0, y1, x1 = [value / 1000 for value in element["bbox"]]
        label = "Object" if kind == "object" else "Character"
        sections.append(
            f"[{label} {fields[0]} | Box {index}]\n"
            f"Position (center): {(x0 + x1) / 2:.3f}, {(y0 + y1) / 2:.3f}\n"
            f"Size: {x1 - x0:.3f} x {y1 - y0:.3f}\n"
            + element["desc"]
        )
    return "\n\n".join(sections)


class MOSSLayoutFromText:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "text": ("STRING", {"multiline": True, "default": "",
                "tooltip": "Scene description, @char[1, @pos(0.3, 0.5), character description]. Optional @size(w,h) or @box(x,y,w,h). Coordinates are 0..1. Without coordinates, boxes are arranged left to right. Optional resolution:1024x1024."}),
            "width": ("INT", {"default": 1024, "min": 16, "max": 16384, "step": 16}),
            "height": ("INT", {"default": 1024, "min": 16, "max": 16384, "step": 16}),
            "box_width": ("FLOAT", {"default": 0.42, "min": 0.01, "max": 1.0, "step": 0.01}),
            "box_height": ("FLOAT", {"default": 0.85, "min": 0.01, "max": 1.0, "step": 0.01}),
            "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff,
                "control_after_generate": True,
                "tooltip": "0 selects the first set/layout. Increment advances layouts first, then character sets, and wraps."}),
            "action_format": (["auto", "lines", "---"], {"default": "auto",
                "tooltip": "auto detects one action per line (with or without @char) or --- separators. lines always treats each nonempty line as one action; use this for wildcard_list. --- preserves multiline layouts."}),
        }, "optional": {
            "character_list": ("STRING", {"forceInput": True,
                "tooltip": "One character description per line. Numeric @char IDs select characters; repeated IDs reuse appearance. Without any @cha/@char slots, always select exactly one character from this list, regardless of action text or gender."}),
            "male_character_list": ("STRING", {"forceInput": True,
                "tooltip": "Optional male wildcard list for boy/boy1/boy2 slots. Without character slots, used only when character_list is empty. All layouts and general character sets run before advancing the male set."}),
        }}

    RETURN_TYPES = ("STRING", "ARRAY", "STRING", "STRING", "INT", "INT", "IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("prompt", "elements", "scene_prompt", "character_boxes", "width", "height", "preview", "report", "readable_prompt")
    FUNCTION = "build"
    CATEGORY = "prompt/layout"

    def build(self, text, width=1024, height=1024, box_width=0.42, box_height=0.85, seed=0, character_list="", action_format="auto", male_character_list=""):
        action, character_map, report = select_character_set(text, character_list, seed, action_format, male_character_list)
        result = compile_layout(action, width, height, box_width, box_height, character_map)
        import numpy as np
        import torch
        from PIL import Image, ImageDraw
        scale = min(1.0, 768 / max(result[4:6]))
        w, h = max(1, round(result[4] * scale)), max(1, round(result[5] * scale))
        image = Image.new("RGB", (w, h), (36, 36, 36))
        draw = ImageDraw.Draw(image)
        colors = [(255, 100, 100), (100, 180, 255), (100, 220, 150), (230, 200, 90)]
        for index, element in enumerate(result[1]):
            y0, x0, y1, x1 = element["bbox"]
            bounds = (min(w - 1, x0 * w / 1000), min(h - 1, y0 * h / 1000), min(w - 1, x1 * w / 1000), min(h - 1, y1 * h / 1000))
            draw.rectangle(bounds, outline=colors[index % len(colors)], width=3)
            draw.text((bounds[0] + 5, bounds[1] + 5), str(index + 1), fill=colors[index % len(colors)])
        preview = torch.from_numpy(np.asarray(image).astype(np.float32) / 255.0).unsqueeze(0)
        return (*result, preview, report, readable_layout(action, result, character_map))


NODE_CLASS_MAPPINGS = {"MOSSLayoutFromText": MOSSLayoutFromText}
NODE_DISPLAY_NAME_MAPPINGS = {"MOSSLayoutFromText": "MOSS Layout From Text"}
