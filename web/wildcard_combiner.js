import { app } from "../../scripts/app.js";

const MAX_CHARS = 8;

function countCharInputs(node) {
    return (node.inputs || []).filter(i => /^char_\d+$/.test(i?.name || "")).length;
}

function countCharOutputs(node) {
    return (node.outputs || []).filter(o => /^char_\d+$/.test(o?.name || "")).length;
}

function growSize(node) {
    const computed = node.computeSize();
    node.size[0] = Math.max(node.size?.[0] || 0, computed[0]);
    node.size[1] = Math.max(node.size?.[1] || 0, computed[1]);
    app.graph?.setDirtyCanvas(true, true);
}

function addCharSlot(node) {
    const count = countCharInputs(node);
    if (count >= MAX_CHARS) {
        alert(`최대 ${MAX_CHARS}개까지 추가 가능합니다.`);
        return;
    }
    const newIdx = count + 1;
    node.addInput(`char_${newIdx}`, "STRING");
    if (node.type === "ConditionalWildcardCombiner" || node.comfyClass === "ConditionalWildcardCombiner") {
        node.addInput(`char_present_${newIdx}`, "STRING");
        node.addInput(`char_missing_${newIdx}`, "STRING");
    }
    node.addOutput(`char_${newIdx}`, "STRING");
    growSize(node);
}

function removeLastCharSlot(node) {
    let lastInputIdx = -1;
    for (let i = node.inputs.length - 1; i >= 0; i--) {
        if (/^char_\d+$/.test(node.inputs[i]?.name || "")) {
            lastInputIdx = i;
            break;
        }
    }
    let lastOutputIdx = -1;
    for (let i = node.outputs.length - 1; i >= 0; i--) {
        if (/^char_\d+$/.test(node.outputs[i]?.name || "")) {
            lastOutputIdx = i;
            break;
        }
    }
    if (lastInputIdx < 0 && lastOutputIdx < 0) return;
    if (lastInputIdx >= 0) {
        const match = node.inputs[lastInputIdx]?.name?.match(/^char_(\d+)$/);
        const idx = match ? match[1] : null;
        if (idx && (node.type === "ConditionalWildcardCombiner" || node.comfyClass === "ConditionalWildcardCombiner")) {
            for (let i = node.inputs.length - 1; i >= 0; i--) {
                const name = node.inputs[i]?.name;
                if (name === `char_present_${idx}` || name === `char_missing_${idx}`) {
                    node.removeInput(i);
                }
            }
        }
        node.removeInput(lastInputIdx);
    }
    if (lastOutputIdx >= 0) node.removeOutput(lastOutputIdx);
    growSize(node);
}

function syncOutputsToInputs(node) {
    // char_ 인풋 개수에 맞춰 char_ 아웃풋 개수 동기화
    const inputCount = countCharInputs(node);
    let outputCount = countCharOutputs(node);

    while (outputCount < inputCount) {
        node.addOutput(`char_${outputCount + 1}`, "STRING");
        outputCount++;
    }

    while (outputCount > inputCount) {
        for (let i = node.outputs.length - 1; i >= 0; i--) {
            if (/^char_\d+$/.test(node.outputs[i]?.name || "")) {
                node.removeOutput(i);
                break;
            }
        }
        outputCount--;
    }
}

app.registerExtension({
    name: "WildcardCombiner",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (!["WildcardCombiner", "ConditionalWildcardCombiner"].includes(nodeData.name)) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            // 워크플로우 로드 중에는 기본 char_1 추가하지 않음
            // (configure에서 저장된 인풋이 복원됨)
            this._isConfiguring = this._isConfiguring || false;

            // 새 노드를 처음 만들 때만 기본 char_1 추가
            // configure 중에는 추가 안 함 (저장된 데이터로 복원됨)
            if (!this._isConfiguring && countCharInputs(this) === 0) {
                addCharSlot(this);
            }

            // + Add Char 버튼
            const addBtn = this.addWidget("button", "+ Add Char", null, () => {
                addCharSlot(this);
            });
            addBtn.serialize = false;

            // - Remove Char 버튼
            const removeBtn = this.addWidget("button", "- Remove Char", null, () => {
                removeLastCharSlot(this);
            });
            removeBtn.serialize = false;
        };

        // 워크플로우 로드 시 인풋/아웃풋 복원
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            this._isConfiguring = true;

            // ComfyUI가 info.inputs/outputs로 자동 복원하도록 super 먼저 호출
            onConfigure?.apply(this, arguments);

            // 복원 후, 인풋과 아웃풋이 정확히 일치하는지 확인
            syncOutputsToInputs(this);
            growSize(this);

            this._isConfiguring = false;
        };
    }
});
