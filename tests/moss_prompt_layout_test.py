import ast
import importlib.util
import json
import math
import re
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("moss_layout_test_module", ROOT / "nodes_moss_prompt_layout.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_moss_contract():
    text = ('A quiet garden, @char[one, @pos(0.25,0.5), blue coat, (smile:1.2)], '
            '@char[two, @box(0.55,0.1,0.4,0.8), green coat], '
            '@object[bench, @box(0.1,0.8,0.8,0.15), wooden bench], resolution:1152x896')
    prompt, elements, scene, characters, width, height = module.compile_layout(text)
    assert (width, height) == (1152, 896)
    assert characters == "1, 2"
    assert scene == "A quiet garden"
    assert elements[1]["bbox"] == [100, 550, 900, 950]
    assert elements[0]["desc"] == "blue coat, (smile:1.2)"
    # Run the installed core node's real execute method without importing GPU code.
    source = ast.parse((ROOT.parents[1] / "comfy_extras" / "nodes_moss_image.py").read_text(encoding="utf-8"))
    cls = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "MOSSImageLayoutPrompt")
    execute = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "execute")
    execute.decorator_list = []
    namespace = {"math": math, "re": re, "json": json,
                 "io": types.SimpleNamespace(NodeOutput=lambda *args: args)}
    exec(compile(ast.Module(body=[execute], type_ignores=[]), "core_moss_execute", "exec"), namespace)
    expected = namespace["execute"](None, scene, elements, width, height, characters)[0]
    assert json.loads(prompt) == json.loads(expected)


def test_automatic_and_legacy_positions():
    result = module.compile_layout("Park, @char[one, blue coat], @char[two, green coat]")
    first, second = result[1]
    assert first["bbox"][1] < second["bbox"][1]
    assert first["bbox"][3] <= second["bbox"][1]
    result = module.compile_layout("@cha[one, @pos(0.9,0.2), @size(0.4,0.6), hat], @char[one, @pos(0.1,0.7), hat]")
    assert len(result[1]) == 2
    assert result[1][0]["bbox"] == [0, 600, 600, 1000]
    assert module.compile_layout("Plain scene")[0] == "Plain scene"


def test_validation_and_preview():
    for text in ("@char[one, @pos(2,0.5), coat]", "@char[one, coat",
                 "@char[one, @box(0,0,0,1), coat]", "@char[one, @pos(0,0)]",
                 "@char[one, @pos(0.2,0.5), @box(0,0,1,1), coat]",
                 "@char[one, @pos(no,0.2), coat]"):
        try:
            module.compile_layout(text)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid layout accepted: {text}")
    result = module.MOSSLayoutFromText().build("Scene, @char[one, @box(0,0,1,1), coat]", 512, 256)
    preview = result[6]
    assert tuple(preview.shape) == (1, 256, 512, 3)
    assert preview.max() > preview.min()
    assert module.MOSSLayoutFromText.RETURN_TYPES[1] == "ARRAY"


def test_character_set_iteration():
    text = "Scene, @char[2, walking], @char[1, sitting], @char[1, another panel], @char[boy, grey coat], @object[3, bench]"
    characters = "alice\nbeth\nclaire\ndora\neve\nfran"
    action, mapping, report = module.select_character_set(text, characters, 1)
    assert mapping == {"1": "claire", "2": "dora"}
    assert "Set 2/3" in report
    elements = module.compile_layout(action, character_map=mapping)[1]
    assert elements[0]["desc"] == "dora, walking"
    assert elements[1]["desc"] == "claire, sitting"
    assert elements[2]["desc"] == "claire, another panel"
    assert elements[3]["desc"] == "grey coat"
    assert elements[4]["desc"] == "bench"
    assert module.select_character_set(text, characters, 3)[1] == {"1": "alice", "2": "beth"}
    assert module.select_character_set(text, "", 1)[1] == {}
    assert module.select_character_set("@char[boy1, coat], @char[boy2, hat]", characters, 4)[1] == {}
    action, mapping, _ = module.select_character_set("@char[1]", characters)
    assert module.compile_layout(action, character_map=mapping)[1][0]["desc"] == "alice"


def test_layout_set_stride():
    nine = ", ".join(f"@char[{i}, walking]" for i in range(1, 10))
    two = "@char[1, sitting], @char[2, standing]"
    text = two + "\n---\n" + nine
    characters = "\n".join(f"person {i}" for i in range(1, 20))
    assert module.select_character_set(text, characters, 0)[1] == {"1": "person 1", "2": "person 2"}
    assert module.select_character_set(text, characters, 1)[1]["9"] == "person 9"
    assert module.select_character_set(text, characters, 2)[1] == {"1": "person 10", "2": "person 11"}
    assert module.select_character_set(text, characters, 3)[1]["9"] == "person 18"
    assert module.select_character_set(text, characters, 4)[1]["1"] == "person 1"
    assert "unused trailing lines: 1" in module.select_character_set(text, characters, 0)[2]
    try:
        module.select_character_set(nine, "alice\nbeth")
    except ValueError as error:
        assert "9 characters" in str(error)
    else:
        raise AssertionError("Too few characters accepted")
    node = module.MOSSLayoutFromText()
    result = node.build(two, 128, 128, seed=1, character_list="alice\nbeth\nclaire\ndora")
    assert result[1][0]["desc"] == "claire, sitting"
    assert result[1][1]["desc"] == "dora, standing"
    assert tuple(result[6].shape) == (1, 128, 128, 3)
    assert "[Character 1 | Box 1]" in result[8]
    assert "claire, sitting" in result[8]
    assert "dora, standing" in result[8]
    assert "alice" not in result[8]


def test_readable_prompt():
    text = "Garden, @char[1, coat], @char[1, hat], @char[boy, grey coat], @object[bench, wood]"
    action, mapping, _ = module.select_character_set(text, "blue hair")
    result = module.compile_layout(action, character_map=mapping)
    readable = module.readable_layout(action, result)
    assert "[Scene]\nGarden" in readable
    assert "[Character 1 | Box 1]" in readable
    assert "[Character 1 | Box 2]" in readable
    assert "[Character boy | Box 3]" in readable
    assert "[Object bench | Box 4]" in readable
    assert "blue hair, coat" in readable and "blue hair, hat" in readable
    assert "Position (center):" in readable and "Size:" in readable
    assert module.readable_layout("Garden", module.compile_layout("Garden")).endswith("[Scene]\nGarden")


def test_wildcard_action_lines():
    first = "Garden, @char[1, sitting], @char[2, standing]"
    second = "Street, @char[1, walking], @char[2, running]"
    text = first + "\n" + second
    chars = "alice\nbeth\nclaire\ndora"
    assert module.split_layouts(text) == [first, second]
    assert module.select_character_set(text, chars, 1)[0] == second
    assert module.select_character_set(text, chars, 1)[1] == {"1": "alice", "2": "beth"}
    assert module.select_character_set(text, chars, 2)[0] == first
    assert module.select_character_set(text, chars, 2)[1] == {"1": "claire", "2": "dora"}
    assert "total combinations: 4" in module.select_character_set(text, chars, 0)[2]
    multiline = "Garden\n@char[1, sitting]\n@char[2, standing]"
    assert module.split_layouts(multiline) == [multiline]
    wrapped = "Garden, @char[1,\nsitting], @char[2, standing]"
    assert module.split_layouts(wrapped) == [wrapped]
    bare = "@char[1, sitting]\n@char[1, walking]"
    assert len(module.split_layouts(bare, "lines")) == 2
    assert module.split_layouts(text, "---") == [text]


def test_multi_file_loader_to_layout():
    import os
    # Execute the actual loader class with file IO stubbed, retaining its real
    # newline serialization, enabled-file handling and sequential ordering.
    tree = ast.parse((ROOT / "wildcard_image_iterator.py").read_text(encoding="utf-8-sig"))
    loader_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "WildcardMultiFileLoader")
    namespace = {"os": os}
    exec(compile(ast.Module(body=[loader_class], type_ignores=[]), "multi_file_loader", "exec"), namespace)
    loader = namespace["WildcardMultiFileLoader"]()
    files = {"first.txt": ["Garden, @char[1, sitting]", "A quiet street"],
             "second.txt": ["Library, @char[1, reading]"]}
    loader._load_one_file = lambda name: files[name]
    output = loader.load_files(seed=0, file_1="first.txt", enable_1=True,
                               file_2="second.txt", enable_2=True)
    assert output[1] == 3
    assert len(module.split_layouts(output[0])) == 3
    node = module.MOSSLayoutFromText()
    expected_scenes = ["Garden", "A quiet street", "Library", "Garden", "A quiet street", "Library"]
    for seed, scene in enumerate(expected_scenes):
        result = node.build(output[0], 64, 64, seed=seed, character_list="blue coat\ngreen coat")
        assert result[2] == scene
        assert "layout " + str(seed % 3 + 1) + "/3" in result[7]
        if result[1]:
            assert result[1][0]["desc"].startswith("blue coat" if seed < 3 else "green coat")
        if scene != "A quiet street":
            assert "A quiet street" not in result[0]
    assert module.split_layouts("A quiet garden\nA quiet street") == ["A quiet garden", "A quiet street"]
    assert len(module.split_layouts("@char[1, sitting]\n@char[1, walking]", "lines")) == 2


def test_single_character_without_slots():
    node = module.MOSSLayoutFromText()
    for token in ("1girl", "1boy"):
        text = token + ", garden, smiling"
        result = node.build(text, 64, 64, seed=1, character_list="blue coat\ngreen coat")
        assert result[1][0]["desc"] == "green coat"
        assert result[2] == text
        assert "green coat" in result[0] and "green coat" in result[8]
        assert "Set 2/2" in result[7]
        assert len(result[1]) == 1
        assert node.build(text, 64, 64)[0] == text
    explicit = "1girl, @cha[1, sitting], @cha[1, standing], @cha[boy, coat]"
    result = node.build(explicit, 64, 64, character_list="blue coat")
    assert len(result[1]) == 3
    assert result[1][0]["desc"] == "blue coat, sitting"
    assert result[1][2]["desc"] == "coat"
    male = node.build("1boy, @char[boy, grey coat]", 64, 64, character_list="blue coat")
    assert len(male[1]) == 1 and male[1][0]["desc"] == "grey coat"
    plain = node.build("garden", 64, 64, character_list="blue coat")
    assert plain[1][0]["desc"] == "blue coat"
    assert module.select_character_set("11girl, 21boy, 1boyfriend", "blue coat")[1] == {"1": "blue coat"}
    repeated = node.build("1girl, 1girl, garden", 64, 64, character_list="blue coat")
    assert len(repeated[1]) == 1


def test_separate_male_list():
    node = module.MOSSLayoutFromText()
    text = "Garden, @char[1, walking], @char[boy, coat], @char[boy1, hat], @char[boy2, smiling]"
    kwargs = dict(character_list="alice\nbeth", male_character_list="adam\nben\nchris\ndan")
    result = node.build(text, 64, 64, seed=0, **kwargs)
    assert [element["desc"] for element in result[1]] == ["alice, walking", "adam, coat", "adam, hat", "ben, smiling"]
    result = node.build(text, 64, 64, seed=1, **kwargs)
    assert result[1][0]["desc"] == "beth, walking"
    assert result[1][1]["desc"] == "adam, coat"
    result = node.build(text, 64, 64, seed=2, **kwargs)
    assert result[1][0]["desc"] == "alice, walking"
    assert result[1][1]["desc"] == "chris, coat"
    assert result[1][3]["desc"] == "dan, smiling"
    assert "chris, coat" in result[8]
    male_only = node.build("1boy, garden", 64, 64, male_character_list="adam\nben", seed=1)
    assert len(male_only[1]) == 1
    assert male_only[1][0]["desc"] == "ben"
    assert "alice" not in male_only[0]
    assert "Character boy1" in male_only[8]
    mixed = node.build("1boy, 1girl, garden", 64, 64, character_list="alice", male_character_list="adam")
    assert [element["desc"] for element in mixed[1]] == ["alice"]
    girl_only = node.build("1girl, garden", 64, 64, character_list="alice", male_character_list="adam\nben")
    assert len(girl_only[1]) == 1 and girl_only[1][0]["desc"] == "alice"
    assert "total combinations: 1" in girl_only[7]
    layouts = text + "\nStreet, @char[1, standing], @char[boy, reading]"
    selected = module.select_character_set(layouts, "alice\nbeth", seed=1, male_character_list="adam\nben\nchris\ndan")
    assert selected[1] == {"1": "alice", "boy1": "adam"}
    selected = module.select_character_set(layouts, "alice\nbeth", seed=4, male_character_list="adam\nben\nchris\ndan")
    assert selected[1] == {"1": "alice", "boy1": "chris", "boy2": "dan"}
    try:
        node.build(text, 64, 64, male_character_list="adam")
    except ValueError as error:
        assert "2 male characters" in str(error)
    else:
        raise AssertionError("Too few male characters accepted")


def test_gender_neutral_solo_actions():
    node = module.MOSSLayoutFromText()
    action = "solo, full body, standing, arms crossed, serious expression, (from front:2.70), white background"
    characters = "1boy, short black hair, blue coat\n1girl, long white hair, green coat"
    for seed, expected in enumerate(characters.splitlines()):
        result = node.build(action, 64, 64, seed=seed, character_list=characters)
        assert len(result[1]) == 1
        assert result[1][0]["desc"] == expected
        assert result[2] == action
        parsed = json.loads(result[0])
        assert parsed["summary"]["caption"] == action
        assert parsed["items"][0]["caption"] == expected
        assert expected in result[8]
        assert "characters per set: 1" in result[7]
    assert node.build(action, 64, 64)[0] == action
    explicit = "solo, @char[1, sitting], @char[1, standing]"
    assert len(node.build(explicit, 64, 64, character_list=characters)[1]) == 2
    assert module.select_character_set("solomon, soloist", characters)[1] == {"1": characters.splitlines()[0]}
    second = "solo, sitting, reading"
    actions = action + "\n" + second
    result = node.build(actions, 64, 64, seed=2, character_list=characters, action_format="lines")
    assert result[2] == action
    assert result[1][0]["desc"].startswith("1girl")
    assert "total combinations: 4" in result[7]


def test_natural_language_single_character():
    action = (
        "A single character is shown in a full-body studio composition against a clean, seamless white background. "
        "The character is depicted standing, in a contrapposto stance, with one hand on the hip. "
        "The character is wearing a confident smile. "
        "The camera uses a straight-on frontal view with a noticeable Dutch tilt."
    )
    node = module.MOSSLayoutFromText()
    characters = "1boy, adult man, black hair, navy suit\n1boy, adult man, grey hair, black coat"
    for seed, caption in enumerate(characters.splitlines()):
        result = node.build(action, 64, 64, seed=seed, character_list=characters)
        parsed = json.loads(result[0])
        assert parsed["summary"]["caption"] == action
        assert len(parsed["items"]) == 1
        assert parsed["items"][0]["caption"] == caption
        assert "1girl" not in result[0]
        assert caption in result[8]
    for phrase in ("One person standing", "a single person standing", "single figure, studio", "one character, smiling"):
        assert len(node.build(phrase, 64, 64, character_list=characters)[1]) == 1
    assert node.build(action, 64, 64)[0] == action


test_natural_language_single_character()
test_gender_neutral_solo_actions()
test_separate_male_list()
test_single_character_without_slots()
test_wildcard_action_lines()
test_multi_file_loader_to_layout()
test_character_set_iteration()
test_readable_prompt()
test_layout_set_stride()
test_moss_contract()
test_automatic_and_legacy_positions()
test_validation_and_preview()
print("MOSS layout parsing, core compatibility and preview tests passed.")
