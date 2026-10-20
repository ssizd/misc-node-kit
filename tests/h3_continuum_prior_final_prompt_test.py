import ast
from pathlib import Path


SOURCE_PATH = Path(__file__).resolve().parents[1] / "wildcard_image_iterator.py"


def load_node_class():
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.ClassDef) and item.name == "H3ContinuumPriorFinalPrompt"
    )
    module = ast.Module(body=[node], type_ignores=[])
    namespace = {}
    exec(compile(module, str(SOURCE_PATH), "exec"), namespace)
    return namespace["H3ContinuumPriorFinalPrompt"]


def main():
    node = load_node_class()()

    assert node.build("continue", "finish", 1) == ("continue",)
    assert node.build("continue", "", 1) == ("continue",)
    assert node.build("continue", "finish", 2) == ("continue\n---\nfinish",)
    assert node.build("continue", "finish", 4) == (
        "continue\n---\ncontinue\n---\ncontinue\n---\nfinish",
    )
    assert node.build("  continue  ", "  finish  ", 2) == (
        "continue\n---\nfinish",
    )

    try:
        node.build("", "finish", 2)
    except ValueError:
        pass
    else:
        raise AssertionError("empty prior_prompt must fail")

    print("H3 Continuum prior/final prompt tests passed")


if __name__ == "__main__":
    main()
