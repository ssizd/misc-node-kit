import { app } from "../../scripts/app.js";

const APPENDED_OUTPUTS = [
    ["source_video", "IMAGE"],
    ["source_audio", "AUDIO"],
];

function ensureGuideOutputs(node) {
    for (const [name, type] of APPENDED_OUTPUTS) {
        if (!(node.outputs || []).some(output => output?.name === name)) {
            node.addOutput(name, type);
        }
    }
}

app.registerExtension({
    name: "WildcardImageIterator.VideoLoopPlannerOutputs",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "VideoLoopPlanner") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            ensureGuideOutputs(this);
            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure?.apply(this, arguments);
            // Saved workflows created before these outputs have only the
            // original 16 slots. Append the new slots without reordering them.
            ensureGuideOutputs(this);
            return result;
        };
    },
});
