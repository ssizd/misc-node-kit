import { app } from "../../scripts/app.js";

const MAX_FILES = 8;

// 캐시 (페이지 로드 1회만 유효, ComfyUI "Refresh Definitions" 누르면 초기화)
let cachedWildcardFiles = null;
let cacheTimestamp = 0;
const CACHE_TTL_MS = 5 * 1000;  // 5초 TTL: 짧은 시간 안에 여러 노드가 호출해도 1번만 fetch

async function getWildcardFiles(forceRefresh = false) {
    const now = Date.now();
    if (!forceRefresh && cachedWildcardFiles !== null && (now - cacheTimestamp) < CACHE_TTL_MS) {
        return cachedWildcardFiles;
    }
    try {
        // 캐시 무효화 쿼리 추가
        const resp = await fetch(`/object_info/WildcardFileLoader?t=${now}`);
        if (resp.ok) {
            const data = await resp.json();
            const info = data.WildcardFileLoader;
            if (info?.input?.required?.wildcard_file) {
                const fileList = info.input.required.wildcard_file[0];
                cachedWildcardFiles = ["None", ...fileList];
                cacheTimestamp = now;
                return cachedWildcardFiles;
            }
        }
    } catch (e) {
        console.error("[MultiFileLoader] wildcard files fetch fail:", e);
    }
    cachedWildcardFiles = ["None"];
    cacheTimestamp = now;
    return cachedWildcardFiles;
}

// 노드의 모든 file_* 위젯의 dropdown 값 목록 갱신
async function refreshAllFileDropdowns(node, forceRefresh = true) {
    const fileList = await getWildcardFiles(forceRefresh);
    let updated = 0;
    (node.widgets || []).forEach(w => {
        if (w?.name?.startsWith("file_") && w.type === "combo") {
            const oldValue = w.value;
            // options 객체에 직접 할당 (LiteGraph combo 위젯 표준)
            if (w.options) {
                w.options.values = fileList;
            } else {
                w.options = { values: fileList };
            }
            // 현재 값이 새 목록에 있으면 유지, 없으면 "None"으로
            if (!fileList.includes(oldValue)) {
                w.value = "None";
            }
            updated += 1;
        }
    });
    if (updated > 0) {
        app.graph?.setDirtyCanvas(true, true);
    }
    return updated;
}

function countFileWidgets(node) {
    return (node.widgets || []).filter(w => w?.name?.startsWith("file_")).length;
}

function growSize(node) {
    const computed = node.computeSize();
    node.size[0] = Math.max(node.size?.[0] || 0, computed[0]);
    node.size[1] = Math.max(node.size?.[1] || 0, computed[1]);
    app.graph?.setDirtyCanvas(true, true);
}

async function addFilePair(node, defaultFileValue, defaultEnabled) {
    const count = countFileWidgets(node);
    if (count >= MAX_FILES) {
        alert(`최대 ${MAX_FILES}개까지 추가 가능합니다.`);
        return;
    }
    const newIdx = count + 1;
    const fileList = await getWildcardFiles();

    const fileWidget = node.addWidget("combo", `file_${newIdx}`, defaultFileValue || "None", () => {}, { values: fileList });
    const enableWidget = node.addWidget("toggle", `enable_${newIdx}`, defaultEnabled !== false, () => {}, {
        on: "✅ on",
        off: "❌ off"
    });

    // 방금 추가된 두 위젯을 + Add File 버튼 앞으로 이동
    const widgets = node.widgets;
    const addBtnIdx = widgets.findIndex(w => w.name === "+ Add File");
    if (addBtnIdx >= 0 && addBtnIdx < widgets.length - 2) {
        const enable = widgets.pop();
        const file = widgets.pop();
        widgets.splice(addBtnIdx, 0, file, enable);
    }

    growSize(node);
    return [fileWidget, enableWidget];
}

function removeLastFilePair(node) {
    const widgets = node.widgets;
    for (let i = widgets.length - 1; i >= 0; i--) {
        if (widgets[i]?.name?.startsWith("enable_")) {
            widgets.splice(i, 1);
            break;
        }
    }
    for (let i = widgets.length - 1; i >= 0; i--) {
        if (widgets[i]?.name?.startsWith("file_")) {
            widgets.splice(i, 1);
            break;
        }
    }
    growSize(node);
}

app.registerExtension({
    name: "WildcardMultiFileLoader",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name !== "WildcardMultiFileLoader") return;

        // 워크플로우 로드인지 감지하기 위해 onConfigure에서 플래그 설정
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            this._wasConfigured = true;

            // widgets_values 뒤에서부터 (string, boolean) 쌍 추출
            const wv = Array.isArray(info?.widgets_values) ? [...info.widgets_values] : null;
            const filePairs = [];
            if (wv) {
                let i = wv.length;
                while (i >= 2) {
                    const enableCand = wv[i - 1];
                    const fileCand = wv[i - 2];
                    if (typeof enableCand === "boolean" && typeof fileCand === "string") {
                        filePairs.unshift([fileCand, enableCand]);
                        i -= 2;
                    } else {
                        break;
                    }
                }
            }

            // 슬롯을 미리 만들어둠 (super가 호출되기 전!)
            // 이렇게 하면 super가 widgets_values를 위젯 순서대로 매핑할 때 정확히 들어맞음
            (async () => {
                for (const [fileVal, enableVal] of filePairs) {
                    await addFilePair(this, fileVal, enableVal);
                }
                growSize(this);
            })();

            onConfigure?.apply(this, arguments);
        };

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = async function () {
            onNodeCreated?.apply(this, arguments);

            const addBtn = this.addWidget("button", "+ Add File", null, () => {
                addFilePair(this);
            });
            addBtn.serialize = false;

            const removeBtn = this.addWidget("button", "- Remove File", null, () => {
                removeLastFilePair(this);
            });
            removeBtn.serialize = false;

            const refreshBtn = this.addWidget("button", "🔄 Refresh File List", null, async () => {
                const updated = await refreshAllFileDropdowns(this, true);
                console.log(`[MultiFileLoader] file dropdown 갱신 완료 (${updated}개 슬롯)`);
            });
            refreshBtn.serialize = false;

            // 신규 노드일 때만 (configure가 호출되지 않은 경우) 기본 file_1 추가
            // setTimeout으로 onConfigure가 먼저 호출될 기회를 줌
            setTimeout(async () => {
                if (!this._wasConfigured && countFileWidgets(this) === 0) {
                    await addFilePair(this);
                }
            }, 0);
        };
    }
});
