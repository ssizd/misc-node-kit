// VideoCompareSplit - 동적 입력 + 인터랙티브 분할선 드래그 UI
import { app } from "/scripts/app.js";

app.registerExtension({
    name: "wildcard_image_iterator.VideoCompareSplit",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name !== "VideoCompareSplit") return;

        // ─── 동적 IMAGE 입력 관리 ───
        // image_N 슬롯이 모두 연결되면 image_(N+1) 추가
        // 마지막 슬롯이 연결 해제되면 빈 슬롯 제거 (최소 2개 유지)
        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function (type, slotIndex, isConnected, link, ioSlot) {
            if (onConnectionsChange) {
                onConnectionsChange.apply(this, arguments);
            }
            if (type !== 1) return; // 1 = input
            try {
                this._updateImageInputs();
                this._renderSplitPreview();
            } catch (e) {
                console.error("[VideoCompareSplit] onConnectionsChange:", e);
            }
        };

        nodeType.prototype._updateImageInputs = function () {
            // 모든 image_N 슬롯 찾기
            const imageSlots = [];
            this.inputs.forEach((inp, idx) => {
                if (inp.name && /^image_\d+$/.test(inp.name)) {
                    imageSlots.push({ inp, idx, num: parseInt(inp.name.split("_")[1]) });
                }
            });
            imageSlots.sort((a, b) => a.num - b.num);

            // 연결된 가장 큰 번호
            let lastConnectedNum = 0;
            imageSlots.forEach(s => {
                if (s.inp.link != null) lastConnectedNum = Math.max(lastConnectedNum, s.num);
            });

            // 목표 슬롯 수: 연결된 마지막 + 1 (빈 슬롯), 최소 2개
            const targetCount = Math.max(2, lastConnectedNum + 1);

            // 부족하면 추가
            let nextNum = imageSlots.length > 0 ? imageSlots[imageSlots.length - 1].num : 0;
            while (imageSlots.length < targetCount) {
                nextNum += 1;
                this.addInput(`image_${nextNum}`, "IMAGE");
                imageSlots.push({ num: nextNum });
            }

            // 남는 빈 슬롯 제거 (뒤에서부터, 최소 2개 유지, 연결 안 된 것만)
            for (let i = imageSlots.length - 1; i >= 0; i--) {
                if (imageSlots.length <= Math.max(2, lastConnectedNum + 1)) break;
                const s = imageSlots[i];
                if (s.inp && s.inp.link == null && s.num > lastConnectedNum) {
                    const slotIdx = this.findInputSlot(s.inp.name);
                    if (slotIdx !== -1) {
                        this.removeInput(slotIdx);
                        imageSlots.splice(i, 1);
                    }
                }
            }

            // 분할 위치 개수 자동 조정 (영상 개수 - 1)
            const numAreas = imageSlots.length;
            const positions = this._getSplitPositions();
            const expected = Math.max(1, numAreas - 1);
            if (positions.length !== expected) {
                const newPos = [];
                for (let i = 1; i < numAreas; i++) newPos.push(i / numAreas);
                this._setSplitPositions(newPos);
            }
        };

        // ─── widget 헬퍼 ───
        nodeType.prototype._getSplitPositions = function () {
            const w = this.widgets && this.widgets.find(w => w.name === "split_positions");
            if (!w || !w.value) return [0.5];
            return String(w.value).split(",").map(s => parseFloat(s.trim())).filter(n => !isNaN(n));
        };

        nodeType.prototype._setSplitPositions = function (positions) {
            const w = this.widgets && this.widgets.find(w => w.name === "split_positions");
            if (w) {
                w.value = positions.map(p => p.toFixed(3)).join(",");
                if (w.callback) {
                    try { w.callback(w.value); } catch (e) {}
                }
            }
        };

        nodeType.prototype._getSplitDirection = function () {
            const w = this.widgets && this.widgets.find(w => w.name === "split_direction");
            return w ? String(w.value) : "vertical";
        };

        // ─── 캔버스 미리보기 (분할선 드래그) ───
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);

            try {
                const canvas = document.createElement("canvas");
                canvas.width = 280;
                canvas.height = 160;
                canvas.style.cssText = "background:#1a1a1a;border-radius:6px;cursor:crosshair;display:block;width:100%;";

                const container = document.createElement("div");
                container.style.cssText = "padding:4px 0;";
                container.appendChild(canvas);

                const helpEl = document.createElement("div");
                helpEl.style.cssText = "font-size:10px;color:#888;text-align:center;margin-top:2px;";
                helpEl.textContent = "분할선 핸들 드래그로 위치 조절";
                container.appendChild(helpEl);

                // DOM widget으로 노드에 부착
                if (typeof this.addDOMWidget === "function") {
                    this.addDOMWidget("split_canvas_widget", "div", container, {
                        hideOnZoom: false,
                        serialize: false,
                    });
                }

                this._splitCanvas = canvas;
                this._splitHelpEl = helpEl;

                // 드래그 상태
                let dragging = null;
                let dragRectCache = null;

                const getNormalizedPos = (e) => {
                    const rect = dragRectCache || canvas.getBoundingClientRect();
                    const cx = (e.clientX - rect.left) / rect.width;
                    const cy = (e.clientY - rect.top) / rect.height;
                    return { cx: Math.max(0.001, Math.min(0.999, cx)),
                             cy: Math.max(0.001, Math.min(0.999, cy)) };
                };

                canvas.addEventListener("mousedown", (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    dragRectCache = canvas.getBoundingClientRect();
                    const positions = this._getSplitPositions();
                    const direction = this._getSplitDirection();
                    const { cx, cy } = getNormalizedPos(e);
                    const target = direction === "vertical" ? cx : cy;

                    let closestIdx = -1;
                    let closestDist = 0.08; // 8% 이내에서 핸들 잡힘
                    positions.forEach((p, i) => {
                        const d = Math.abs(p - target);
                        if (d < closestDist) {
                            closestDist = d;
                            closestIdx = i;
                        }
                    });
                    if (closestIdx >= 0) {
                        dragging = closestIdx;
                        canvas.style.cursor = (direction === "vertical") ? "ew-resize" : "ns-resize";
                    }
                });

                const onMouseMove = (e) => {
                    if (dragging === null) return;
                    const direction = this._getSplitDirection();
                    const { cx, cy } = getNormalizedPos(e);
                    const newPos = direction === "vertical" ? cx : cy;
                    let positions = this._getSplitPositions();
                    positions[dragging] = newPos;
                    // 정렬 후 dragging 인덱스도 따라가도록 추적
                    const draggedValue = newPos;
                    positions.sort((a, b) => a - b);
                    dragging = positions.indexOf(draggedValue);
                    this._setSplitPositions(positions);
                    this._renderSplitPreview();
                };

                const onMouseUp = () => {
                    dragging = null;
                    canvas.style.cursor = "crosshair";
                    dragRectCache = null;
                };

                // mousemove/mouseup은 document에 걸어야 핸들 밖으로 빠져나가도 추적됨
                document.addEventListener("mousemove", onMouseMove);
                document.addEventListener("mouseup", onMouseUp);

                // 노드 삭제 시 cleanup
                const onRemoved = this.onRemoved;
                this.onRemoved = function () {
                    document.removeEventListener("mousemove", onMouseMove);
                    document.removeEventListener("mouseup", onMouseUp);
                    if (onRemoved) onRemoved.apply(this, arguments);
                };

                // split_direction/positions 변경 시 즉시 리렌더
                const dirWidget = this.widgets && this.widgets.find(w => w.name === "split_direction");
                if (dirWidget) {
                    const origCb = dirWidget.callback;
                    dirWidget.callback = (val) => {
                        if (origCb) origCb.call(dirWidget, val);
                        this._renderSplitPreview();
                    };
                }
                const posWidget = this.widgets && this.widgets.find(w => w.name === "split_positions");
                if (posWidget) {
                    const origCb = posWidget.callback;
                    posWidget.callback = (val) => {
                        if (origCb) origCb.call(posWidget, val);
                        this._renderSplitPreview();
                    };
                }

                // 초기 렌더
                setTimeout(() => {
                    this._updateImageInputs();
                    this._renderSplitPreview();
                }, 50);
            } catch (e) {
                console.error("[VideoCompareSplit] onNodeCreated:", e);
            }
        };

        // ─── 캔버스 렌더링 ───
        nodeType.prototype._renderSplitPreview = function () {
            if (!this._splitCanvas) return;
            const canvas = this._splitCanvas;
            const ctx = canvas.getContext("2d");
            const W = canvas.width, H = canvas.height;

            // 영상 입력 슬롯 수
            const imageSlots = (this.inputs || []).filter(i => i.name && /^image_\d+$/.test(i.name));
            const numAreas = Math.max(2, imageSlots.length);
            const direction = this._getSplitDirection();
            let positions = this._getSplitPositions();

            // 분할 위치 개수 자동 조정
            const expected = numAreas - 1;
            if (positions.length !== expected) {
                positions = [];
                for (let i = 1; i < numAreas; i++) positions.push(i / numAreas);
            }
            positions = positions.map(p => Math.max(0.001, Math.min(0.999, p)));

            // 배경
            ctx.fillStyle = "#1a1a1a";
            ctx.fillRect(0, 0, W, H);

            // 체크무늬 백그라운드 (영상이 안 깔린 슬롯 표시 의도)
            const grid = 16;
            ctx.fillStyle = "#252525";
            for (let y = 0; y < H; y += grid) {
                for (let x = 0; x < W; x += grid) {
                    if (((x / grid) + (y / grid)) % 2 === 0) {
                        ctx.fillRect(x, y, grid, grid);
                    }
                }
            }

            // 영역 색
            const palette = ["#FF6B6B", "#4ECDC4", "#45B7D1", "#FFA07A",
                             "#98D8C8", "#F7DC6F", "#BB8FCE", "#85C1E9"];

            const connected = imageSlots.map(i => i.link != null);

            if (direction === "vertical") {
                const boundaries = [0, ...positions.map(p => p * W), W];
                for (let i = 0; i < numAreas; i++) {
                    const x0 = boundaries[i];
                    const x1 = boundaries[i + 1];
                    const w = x1 - x0;
                    if (w <= 0) continue;
                    ctx.fillStyle = palette[i % palette.length];
                    ctx.globalAlpha = connected[i] ? 0.55 : 0.18;
                    ctx.fillRect(x0, 0, w, H);
                    ctx.globalAlpha = 1.0;
                    // 라벨
                    ctx.fillStyle = "#fff";
                    ctx.font = "bold 11px sans-serif";
                    ctx.textAlign = "center";
                    ctx.textBaseline = "middle";
                    const label = `vid${i + 1}${connected[i] ? "" : " (빈)"}`;
                    if (w > 30) ctx.fillText(label, x0 + w / 2, H / 2);
                }
                // 분할선 + 핸들
                positions.forEach(p => {
                    const x = p * W;
                    ctx.strokeStyle = "#fff";
                    ctx.lineWidth = 1.5;
                    ctx.beginPath();
                    ctx.moveTo(x, 0); ctx.lineTo(x, H);
                    ctx.stroke();
                    // 핸들 (위/아래 양 끝에 작은 사각형)
                    ctx.fillStyle = "#fff";
                    ctx.fillRect(x - 5, H / 2 - 12, 10, 24);
                    ctx.fillStyle = "#222";
                    ctx.font = "bold 10px sans-serif";
                    ctx.textAlign = "center";
                    ctx.textBaseline = "middle";
                    ctx.fillText("⇔", x, H / 2);
                });
            } else {
                // horizontal
                const boundaries = [0, ...positions.map(p => p * H), H];
                for (let i = 0; i < numAreas; i++) {
                    const y0 = boundaries[i];
                    const y1 = boundaries[i + 1];
                    const h = y1 - y0;
                    if (h <= 0) continue;
                    ctx.fillStyle = palette[i % palette.length];
                    ctx.globalAlpha = connected[i] ? 0.55 : 0.18;
                    ctx.fillRect(0, y0, W, h);
                    ctx.globalAlpha = 1.0;
                    ctx.fillStyle = "#fff";
                    ctx.font = "bold 11px sans-serif";
                    ctx.textAlign = "center";
                    ctx.textBaseline = "middle";
                    const label = `vid${i + 1}${connected[i] ? "" : " (빈)"}`;
                    if (h > 20) ctx.fillText(label, W / 2, y0 + h / 2);
                }
                positions.forEach(p => {
                    const y = p * H;
                    ctx.strokeStyle = "#fff";
                    ctx.lineWidth = 1.5;
                    ctx.beginPath();
                    ctx.moveTo(0, y); ctx.lineTo(W, y);
                    ctx.stroke();
                    ctx.fillStyle = "#fff";
                    ctx.fillRect(W / 2 - 12, y - 5, 24, 10);
                    ctx.fillStyle = "#222";
                    ctx.font = "bold 10px sans-serif";
                    ctx.textAlign = "center";
                    ctx.textBaseline = "middle";
                    ctx.fillText("⇕", W / 2, y);
                });
            }

            // 도움말 텍스트
            if (this._splitHelpEl) {
                this._splitHelpEl.textContent =
                    `${numAreas}개 영역 (${direction === "vertical" ? "좌→우" : "위→아래"}) | ` +
                    `분할: ${positions.map(p => (p * 100).toFixed(1) + "%").join(", ")}`;
            }
        };
    },
});
