import re


_GIRL_COUNT_RE = re.compile(r"(?<![A-Za-z0-9_])(\d+)\s*\+?\s*girls?(?![A-Za-z0-9_])", re.IGNORECASE)
_MULTIPLE_GIRLS_RE = re.compile(r"(?<![A-Za-z0-9_])multiple\s+girls?(?![A-Za-z0-9_])", re.IGNORECASE)


def split_nonempty_lines(value):
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def girl_count(prompt):
    counts = [int(match.group(1)) for match in _GIRL_COUNT_RE.finditer(str(prompt or ""))]
    if _MULTIPLE_GIRLS_RE.search(str(prompt or "")):
        counts.append(2)
    return max(counts, default=0)


def build_action_character_sets(action_text, character_text):
    actions = split_nonempty_lines(action_text)
    characters = split_nonempty_lines(character_text)
    if not actions:
        raise ValueError("Action list is empty.")

    # An action without an explicit Ngirls tag is a normal single-character action.
    counts = [max(1, girl_count(action)) for action in actions]
    max_girls = max(counts, default=1)
    if characters and len(characters) < max_girls:
        raise ValueError(
            f"Character list needs at least {max_girls} lines, but only {len(characters)} were provided."
        )

    set_count = max(1, len(characters) // max_girls)
    entries = []
    for set_zero_index in range(set_count):
        start = set_zero_index * max_girls
        for action_zero_index, (action, count) in enumerate(zip(actions, counts)):
            clean_action = action.rstrip(" ,")
            selected = characters[start : start + count] if characters else []
            marker_numbers = range(1, count + 1)
            markers = ", ".join(f"girl{number}" for number in marker_numbers)
            combined_parts = [clean_action, *selected]
            marked_parts = [clean_action] + ([markers] if markers else [])
            entries.append(
                {
                    "action": clean_action,
                    "characters": selected,
                    "markers": markers,
                    "combined": ", ".join(part for part in combined_parts if part),
                    "marked": ", ".join(part for part in marked_parts if part),
                    "set_index": set_zero_index + 1,
                    "action_index": action_zero_index + 1,
                    "max_girls": max_girls,
                }
            )

    return entries


def build_combiner_inputs(action_text, character_text, max_slots=9):
    entries = build_action_character_sets(action_text, character_text)
    max_girls = entries[0]["max_girls"]
    if max_girls > max_slots:
        raise ValueError(
            f"The largest action needs {max_girls} character slots, but this node provides {max_slots}."
        )

    actions = []
    for entry in entries:
        if entry["set_index"] != 1:
            break
        actions.append(entry["marked"])

    characters = split_nonempty_lines(character_text)
    set_count = len(characters) // max_girls
    slot_lists = []
    for slot_zero_index in range(max_slots):
        if slot_zero_index >= max_girls:
            slot_lists.append("")
            continue
        slot_lists.append(
            "\n".join(
                characters[(set_zero_index * max_girls) + slot_zero_index]
                for set_zero_index in range(set_count)
            )
        )
    return "\n".join(actions), slot_lists
