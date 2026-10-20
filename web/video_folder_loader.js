import { app } from "../../scripts/app.js";

const MAX_SPLIT = 32;

function findOutputIdx(node, name) {
    return (node.outputs || []).findIndex(o => o?.name === name);
}

function growSize(node) {
    const computed = node.computeSize();
    node.size[0] = Math.max(node.size?.[0] || 0, computed[0]);
    node.size[1] = Math.max(node.size?.[1] || 0, computed[1]);
    app.graph?.setDirtyCanvas(true, true);
}

// 부족한 슬롯만 추가, 제거는 절대 안 함 (link 보존이 최우선)
function ensureSlots(node, upTo) {
    for (let i = 1; i <= upTo; i++) {
        if (findOutputIdx(node, `frames_${i}`) < 0) {
            node.addOutput(`frames_${i}`, "IMAGE");
        }
        if (findOutputIdx(node, `audio_${i}`) < 0) {
            node.addOutput(`audio_${i}`, "AUDIO");
        }
    }
    growSize(node);
}

app.registerExtension({
    name: "VideoFromFolderLoader",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name !== "VideoFromFolderLoader") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            const splitWidget = this.widgets?.find(w => w.name === "split_count");
            if (splitWidget) {
                const origCallback = splitWidget.callback;
                splitWidget.callback = (value) => {
                    origCallback?.call(splitWidget, value);
                    // 슬롯이 부족하면 추가만, 제거는 안 함
                    ensureSlots(this, value);
                };
                // 신규 노드: 현재 split_count 값까지 슬롯 추가
                if (!this._configureDone) {
                    setTimeout(() => {
                        if (!this._configureDone) {
                            ensureSlots(this, splitWidget.value || 0);
                        }
                    }, 0);
                }
            }
        };

        // 워크플로우 로드: ComfyUI가 저장된 슬롯/link 그대로 복원
        // 아무것도 안 함 → link 안 끊김
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            onConfigure?.apply(this, arguments);
            this._configureDone = true;
            // 추가 작업 없음 - 저장된 그대로 유지
        };
    }
});
