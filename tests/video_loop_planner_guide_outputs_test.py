import ast
import os
import pathlib
import re
import tempfile


NODE_ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE_PATH = NODE_ROOT / "wildcard_image_iterator.py"


def load_planner_class():
    source = SOURCE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SOURCE_PATH))
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "VideoLoopPlanner"
    )
    module = ast.Module(body=[class_node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "os": os,
        "re": re,
        "any_type": object(),
    }
    exec(compile(module, str(SOURCE_PATH), "exec"), namespace)
    return namespace["VideoLoopPlanner"]


planner = load_planner_class()()


class FakeTensor:
    def __init__(self, shape, sliced_with=None):
        self.shape = shape
        self.sliced_with = sliced_with

    def __getitem__(self, key):
        return FakeTensor(self.shape, key)

    def clone(self):
        return self


class FakeVideoLoader:
    def load_video(self, **kwargs):
        return (
            FakeTensor((145, 64, 64, 3)),
            {"waveform": FakeTensor((1, 2, 288000)), "sample_rate": 48000},
        )


planner._load_extension_guide_media.__func__.__globals__["VideoFromFolderLoaderSimple"] = FakeVideoLoader
tail_frames, tail_audio = planner._load_extension_guide_media("previous.mp4")
assert tail_frames.sliced_with == slice(-22, None, None)
assert tail_audio["waveform"].sliced_with == (Ellipsis, slice(-44000, None, None))

with tempfile.TemporaryDirectory() as output_dir:
    planner._resolve_output_folder = lambda value: output_dir
    planner.get_source_video_from_folder = lambda *args, **kwargs: (
        "source.mp4",
        os.path.abspath("source.mp4"),
        False,
    )
    planner._load_video_last_frame_tensor = lambda path: "last-frame-only"
    planner._load_extension_guide_media = lambda path: (
        "video-frame-batch",
        "source-audio",
    )

    without_guide = planner.plan(
        extension_enabled=True,
        extension_video_folder="videos",
        output_folder=output_dir,
        load_guide_media=False,
    )
    assert len(without_guide) == 18
    assert without_guide[11] == "last-frame-only"
    assert without_guide[15] is True
    assert without_guide[16:] == (None, None)

    with_guide = planner.plan(
        extension_enabled=True,
        extension_video_folder="videos",
        output_folder=output_dir,
        load_guide_media=True,
    )
    assert len(with_guide) == 18
    assert with_guide[11] == "last-frame-only"
    assert with_guide[15] is True
    assert with_guide[16:] == ("video-frame-batch", "source-audio")

expected_prefix = (
    "iteration", "repeat_count", "is_first", "is_last", "part_filename",
    "previous_video_path", "current_video_path", "output_folder", "final_filename",
    "loop_config", "source_index", "source_image", "source_filename", "source_path",
    "is_repeat_first", "is_extension_mode",
)
assert planner.RETURN_NAMES[:16] == expected_prefix
assert planner.RETURN_NAMES[16:] == ("source_video", "source_audio")

print("Video Loop Planner guide output compatibility tests passed.")
