import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";


let extension;
const app = {
    registerExtension(value) {
        extension = value;
    },
};

const sourcePath = new URL("../web/video_loop_planner_outputs.js", import.meta.url);
const sourceCode = fs.readFileSync(sourcePath, "utf8")
    .replace(/^import .*?;\s*/s, "");
vm.runInNewContext(sourceCode, { app }, { filename: sourcePath.pathname });

assert.ok(extension, "Video Loop Planner output extension was not registered");

const originalNames = [
    "iteration", "repeat_count", "is_first", "is_last", "part_filename",
    "previous_video_path", "current_video_path", "output_folder", "final_filename",
    "loop_config", "source_index", "source_image", "source_filename", "source_path",
    "is_repeat_first", "is_extension_mode",
];

class PlannerNode {
    constructor() {
        this.outputs = originalNames.map(name => ({ name, type: "original" }));
    }

    addOutput(name, type) {
        this.outputs.push({ name, type });
    }

    onConfigure() {
        // LiteGraph restores the output array serialized by an older workflow.
        this.outputs = originalNames.map(name => ({ name, type: "original" }));
    }
}

await extension.beforeRegisterNodeDef(PlannerNode, { name: "VideoLoopPlanner" });

const node = new PlannerNode();
node.onNodeCreated();
assert.deepEqual(node.outputs.slice(0, 16).map(output => output.name), originalNames);
assert.deepEqual(node.outputs.slice(16), [
    { name: "source_video", type: "IMAGE" },
    { name: "source_audio", type: "AUDIO" },
]);

node.onConfigure();
assert.deepEqual(node.outputs.slice(0, 16).map(output => output.name), originalNames);
assert.deepEqual(node.outputs.slice(16), [
    { name: "source_video", type: "IMAGE" },
    { name: "source_audio", type: "AUDIO" },
]);

console.log("Video Loop Planner frontend output position tests passed.");
