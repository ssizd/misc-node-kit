import ast
import pathlib
import re


NODE_ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE_PATH = NODE_ROOT / "wildcard_image_iterator.py"


def load_combiner_class():
    source = SOURCE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SOURCE_PATH))
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ConditionalWildcardCombiner"
    )
    module = ast.Module(body=[class_node], type_ignores=[])
    ast.fix_missing_locations(module)

    class PassthroughTuple(tuple):
        def __new__(cls, values):
            return super().__new__(cls, values)

    namespace = {
        "re": re,
        "FlexibleOptionalInputType": lambda **kwargs: {},
        "any_type": object(),
        "ByPassTypeTuple": PassthroughTuple,
        "CharNamesTypeTuple": PassthroughTuple,
    }
    exec(compile(module, str(SOURCE_PATH), "exec"), namespace)
    return namespace["ConditionalWildcardCombiner"]


def combine(action):
    combiner = load_combiner_class()()
    return combiner.combine(
        action=action,
        char_1="alice, black hair",
        char_2="beth, blonde hair",
    )


girl_1 = combine("girl1, standing")
assert girl_1[2] == "alice, black hair"
assert girl_1[8:] == ("alice, black hair", "")
assert "beth" not in girl_1[0]
assert girl_1[1] == "standing"
assert "girl1" not in girl_1[0]

girl_2 = combine("girl2, sitting")
assert girl_2[2] == "beth, blonde hair"
assert girl_2[8:] == ("", "beth, blonde hair")
assert "alice" not in girl_2[0]
assert girl_2[1] == "sitting"
assert "girl2" not in girl_2[0]

both = combine("girl1, girl2, walking")
assert both[2] == "alice, beth, black hair, blonde hair"
assert both[8:] == ("alice, black hair", "beth, blonde hair")
assert both[1] == "walking"
assert "girl1" not in both[0] and "girl2" not in both[0]

legacy = combine("standing")
assert legacy[2] == "alice, beth, black hair, blonde hair"
assert legacy[8:] == ("alice, black hair", "beth, blonde hair")

exact_number = combine("girl10, standing")
assert exact_number[2] == ""
assert exact_number[8:] == ("", "")

combiner = load_combiner_class()()
character_sets = {
    "max_girls": 2,
    "slot_lists": [
        "character 1\ncharacter 3",
        "character 2\ncharacter 4",
    ],
}
automatic_first = combiner.combine(
    action="girl1, standing\ngirl1, girl2, walking",
    seed=0,
    character_sets=character_sets,
)
assert automatic_first[2] == "character 1"

automatic_pair = combiner.combine(
    action="girl1, standing\ngirl1, girl2, walking",
    seed=1,
    character_sets=character_sets,
)
assert automatic_pair[2] == "character 1, character 2"

automatic_next_set = combiner.combine(
    action="girl1, standing\ngirl1, girl2, walking",
    seed=2,
    character_sets=character_sets,
)
assert automatic_next_set[2] == "character 3"

sets_override_slots = combiner.combine(
    action="girl1, standing",
    seed=0,
    character_source_mode="character_sets",
    character_sets=character_sets,
    char_1="wrong individual character",
)
assert sets_override_slots[2] == "character 1"

slots_override_sets = combiner.combine(
    action="girl1, standing",
    seed=0,
    character_source_mode="individual_slots",
    character_sets=character_sets,
    char_1="individual character",
)
assert slots_override_sets[2] == "individual character"

empty_character_sets = {
    "max_girls": 2,
    "slot_lists": ["", ""],
}
action_only = combiner.combine(
    action="girl1, girl2, walking together\ngirl1, sitting",
    seed=0,
    character_source_mode="character_sets",
    character_sets=empty_character_sets,
)
assert action_only[0] == "walking together"
assert action_only[1] == "walking together"
assert action_only[2] == ""
assert action_only[7] == 2

print("Conditional Wildcard Combiner girl slot selection tests passed.")
