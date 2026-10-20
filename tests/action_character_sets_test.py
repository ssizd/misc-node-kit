import importlib.util
from pathlib import Path


HELPER_PATH = Path(__file__).resolve().parents[1] / "helper_action_character_sets.py"
SPEC = importlib.util.spec_from_file_location("action_character_sets_helper", HELPER_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def main():
    actions = "2girls, holding hands\n9girls, group photo"
    characters = "\n".join(f"character prompt {number}" for number in range(1, 19))
    entries = MODULE.build_action_character_sets(actions, characters)

    assert len(entries) == 4
    assert entries[0]["markers"] == "girl1, girl2"
    assert entries[1]["markers"].endswith("girl9")
    assert entries[2]["markers"] == "girl1, girl2"
    assert entries[2]["characters"] == ["character prompt 10", "character prompt 11"]
    assert entries[2]["set_index"] == 2
    assert entries[2]["action_index"] == 1
    assert entries[2]["max_girls"] == 9
    assert MODULE.girl_count("6+girls, outdoors") == 6
    assert MODULE.girl_count("multiple girls, outdoors") == 2

    implicit_single = MODULE.build_action_character_sets(
        "safe, indoors, sitting on bed",
        "character one\ncharacter two",
    )
    assert implicit_single[0]["max_girls"] == 1
    assert implicit_single[0]["markers"] == "girl1"
    assert implicit_single[0]["characters"] == ["character one"]
    assert implicit_single[1]["characters"] == ["character two"]

    empty_entries = MODULE.build_action_character_sets(actions, "")
    empty_marked_actions, empty_slots = MODULE.build_combiner_inputs(actions, "")
    assert len(empty_entries) == 2
    assert empty_entries[0]["characters"] == []
    assert empty_marked_actions.splitlines()[0].endswith("girl1, girl2")
    assert all(slot == "" for slot in empty_slots)

    marked_actions, slot_lists = MODULE.build_combiner_inputs(actions, characters)
    assert marked_actions.splitlines() == [
        "2girls, holding hands, girl1, girl2",
        "9girls, group photo, girl1, girl2, girl3, girl4, girl5, girl6, girl7, girl8, girl9",
    ]
    assert slot_lists[0].splitlines() == ["character prompt 1", "character prompt 10"]
    assert slot_lists[1].splitlines() == ["character prompt 2", "character prompt 11"]
    assert slot_lists[8].splitlines() == ["character prompt 9", "character prompt 18"]

    try:
        MODULE.build_action_character_sets("3girls", "one\ntwo")
    except ValueError as error:
        assert "at least 3 lines" in str(error)
    else:
        raise AssertionError("An incomplete character set must be rejected.")

    print("Action/character set helper regression tests passed.")


if __name__ == "__main__":
    main()
