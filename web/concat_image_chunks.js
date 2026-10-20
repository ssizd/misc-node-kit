import { app } from "../../scripts/app.js";

const MAX_CHUNKS = 16;

function countChunkInputs(node) {
    return (node.inputs || []).filter(i => i?.name?.startsWith("chunk_")).length;
}

function growSize(node) {
    const computed = node.computeSize();
    node.size[0] = Math.max(node.size?.[0] || 0, computed[0]);
    node.size[1] = Math.max(node.size?.[1] || 0, computed[1]);
    app.graph?.setDirtyCanvas(true, true);
}

function addChunkInput(node) {
    const count = countChunkInputs(node);
    if (count >= MAX_CHUNKS) {
        alert(`최대 ${MAX_CHUNKS}개까지 추가 가능합니다.`);
        return;
    }
    const newIdx = count + 1;
    node.addInput(`chunk_${newIdx}`, "IMAGE");
    growSize(node);
}

function removeLastChunkInput(node) {
    let lastInputIdx = -1;
    for (let i = node.inputs.length - 1; i >= 0; i--) {
        if (node.inputs[i]?.name?.startsWith("chunk_")) {
            lastInputIdx = i;
            break;
        }
    }
    if (lastInputIdx >= 0) {
        node.removeInput(lastInputIdx);
        growSize(node);
    }
}

app.registerExtension({
    name: "ConcatImageChunks",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name !== "ConcatImageChunks") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            // + Add Chunk 버튼
            const addBtn = this.addWidget("button", "+ Add Chunk", null, () => {
                addChunkInput(this);
            });
            addBtn.serialize = false;

            // - Remove Chunk 버튼
            const removeBtn = this.addWidget("button", "- Remove Chunk", null, () => {
                removeLastChunkInput(this);
            });
            removeBtn.serialize = false;

            // 신규 노드일 때만 기본 chunk_1, chunk_2 추가
            if (!this._isConfiguring && countChunkInputs(this) === 0) {
                addChunkInput(this);
                addChunkInput(this);
            }
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            this._isConfiguring = true;
            onConfigure?.apply(this, arguments);
            growSize(this);
            this._isConfiguring = false;
        };
    }
});
