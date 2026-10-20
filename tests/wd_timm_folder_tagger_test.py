import importlib.util
from pathlib import Path

from PIL import Image
import torch


MODULE_PATH = Path(__file__).resolve().parents[1] / "nodes_wd_timm_folder_tagger.py"
SPEC = importlib.util.spec_from_file_location("wd_timm_folder_tagger_test_module", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeTagger:
    def tag(self, *_args, **_kwargs):
        return (["blue_hair, smile, "], [{}])


def test_folder_tagging_saves_sibling_text_and_prefix(tmp_path):
    Image.new("RGB", (32, 24), "red").save(tmp_path / "image2.png")
    Image.new("RGB", (32, 24), "blue").save(tmp_path / "image10.jpg")

    node = MODULE.WDTimmFolderTagger()
    node._tagger = FakeTagger()
    result = node.tag_folder(
        str(tmp_path), "unused", "auto", 0.35, 0.75, False, "",
        "artist tag", True, "overwrite", False,
    )

    tags, image_paths, text_paths, count, report = result
    assert count == 2
    assert [Path(path).name for path in image_paths] == ["image2.png", "image10.jpg"]
    assert tags == ["artist tag, blue_hair, smile", "artist tag, blue_hair, smile"]
    assert (tmp_path / "image2.txt").read_text(encoding="utf-8") == tags[0]
    assert (tmp_path / "image10.txt").read_text(encoding="utf-8") == tags[1]
    assert len(text_paths) == 2
    assert "saved 2" in report


def test_skip_existing_text_keeps_file(tmp_path):
    Image.new("RGB", (16, 16), "white").save(tmp_path / "sample.webp")
    text_path = tmp_path / "sample.txt"
    text_path.write_text("keep me", encoding="utf-8")

    node = MODULE.WDTimmFolderTagger()
    node._tagger = FakeTagger()
    result = node.tag_folder(
        str(tmp_path), "unused", "auto", 0.35, 0.75, False, "",
        "prefix", True, "skip", False,
    )

    assert text_path.read_text(encoding="utf-8") == "keep me"
    assert "skipped 1" in result[-1]


def test_connected_image_uses_single_mode_and_ignores_folder():
    node = MODULE.WDTimmFolderTagger()
    node._tagger = FakeTagger()
    image_batch = torch.zeros((3, 24, 32, 3), dtype=torch.float32)

    tags, image_paths, text_paths, count, report = node.tag_folder(
        "this folder does not exist", "unused", "auto", 0.35, 0.75, False, "",
        "connected", True, "overwrite", False, image=image_batch,
    )

    assert tags == ["connected, blue_hair, smile"]
    assert image_paths == []
    assert text_paths == []
    assert count == 1
    assert "save_text was ignored" in report


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        test_folder_tagging_saves_sibling_text_and_prefix(Path(directory))
    with tempfile.TemporaryDirectory() as directory:
        test_skip_existing_text_keeps_file(Path(directory))
    test_connected_image_uses_single_mode_and_ignores_folder()
    print("WD Timm folder tagger tests passed.")
