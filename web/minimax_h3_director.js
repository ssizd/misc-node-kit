import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const DEFAULT_BUILDER_STATE = mode => {
  if (mode === "REF2VA") {
    return { version: 2, mode: "REF2VA", duration: 5, ref: { subject_definitions: "", summary: "", retention_analysis: "", detailed_description: "", soundscape: "", music: "N/A" } };
  }
  return { version: 1, mode: mode || "FL2VA", imd: "", soundscape: "", music: "N/A", duration: 5, ref: { subject_defs: [], summary_types: ["reference generation"], summary_text: "", retention: [], style_line: "", detail: "", soundscape: "", music: "N/A" } };
};
const TASK_TYPES_JS = ["keyframe completion","reference generation","video editing","video continuation","audio reuse","audio reference"];
const VISUAL_MARKERS_JS = ["fully_preserved","partially_preserved","attribute_transfer","weak_reference"];
const AUDIO_MARKERS_JS = ["fully_copy","partially_copy","reference","weak_reference"];
const ALL_MARKERS_JS = [...new Set([...VISUAL_MARKERS_JS,...AUDIO_MARKERS_JS])];
const DEFAULT_STATE = { version: 1, items: [], prompt_blocks: [], builder_state: null, image_source_mode: "auto", use_end_frame: true };
const MAX = { image: 9, video: 3, audio: 3, total: 12 };
const REPOSITORY_URL = "https://github.com/darksidewalker/ComfyUI-DaSiWa-Nodes/blob/main/docs/minimax_h3_director.md";
const IMAGE_EXTENSIONS = new Set(["avif", "bmp", "gif", "heic", "heif", "jpeg", "jpg", "jxl", "png", "tif", "tiff", "webp"]);
const VIDEO_EXTENSIONS = new Set(["3gp", "avi", "flv", "m2ts", "m4v", "mkv", "mov", "mp4", "mpeg", "mpg", "mts", "ts", "webm", "wmv"]);
const AUDIO_EXTENSIONS = new Set(["aac", "aif", "aiff", "alac", "amr", "ape", "caf", "flac", "m4a", "mka", "mp3", "oga", "ogg", "opus", "wav", "weba", "wma"]);
let cssInstalled = false;

function installStyles() {
  if (cssInstalled) return;
  cssInstalled = true;
  const style = document.createElement("style");
  style.textContent = `
    .ds-h3{box-sizing:border-box;width:100%;min-width:0;min-height:850px;align-self:stretch;background:transparent;border:0;border-radius:0;padding:0;font:12px system-ui,sans-serif;display:flex;flex-direction:column;gap:6px;overflow:visible}
    .ds-h3 button{background:#202b35;color:#dbe7f0;border:1px solid #40515e;border-radius:4px;padding:4px 7px;cursor:pointer}.ds-h3 button:hover{background:#2c3c49}.ds-h3-lane-add{position:absolute;right:6px;z-index:3;width:22px;height:22px;padding:0!important;border-radius:50%!important;font-size:17px;line-height:18px;background:rgba(70,150,105,.3)!important;border-color:rgba(126,210,157,.75)!important;color:#bff3d0!important}
    .ds-h3-toolbar,.ds-h3-row,.ds-h3-actions{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.ds-h3-toolbar{justify-content:space-between;padding:2px 0 4px}.ds-h3-title{font-weight:600;color:#fff}.ds-h3-modebar{display:flex;gap:4px;padding:4px;background:#0d1217;border:1px solid #344452;border-radius:6px}.ds-h3-modebar button{padding:4px 9px!important;border-radius:999px!important;background:transparent!important;color:#9fb3c2!important}.ds-h3-modebar button.active{color:#fff!important;border-color:rgba(177,128,255,.8)!important;box-shadow:0 0 10px rgba(151,91,255,.6);font-weight:700}.ds-h3-clear-btn,.ds-h3-remove-btn{padding:3px 7px!important;font-size:11px;border-radius:999px!important}.ds-h3-clear-btn{background:rgba(255,100,100,.08)!important;color:#ffb0b0!important;border:1px solid rgba(255,100,100,.35)!important}.ds-h3-clear-btn:hover{box-shadow:0 0 8px rgba(255,100,100,.35)}.ds-h3-remove-btn{background:rgba(255,150,60,.08)!important;color:#ffcfab!important;border:1px solid rgba(255,150,60,.3)!important}.ds-h3-remove-btn:hover{box-shadow:0 0 8px rgba(255,150,60,.3)}.ds-h3-drop{border:1px dashed #587084;border-radius:5px;padding:12px;text-align:center;color:#9fb3c2}.ds-h3-drop.over{background:#263845;border-color:#8dd7ff}.ds-h3-list{display:flex;flex-direction:column;gap:4px}.ds-h3-item{display:grid;grid-template-columns:50px minmax(0,1fr) auto;gap:6px;align-items:center;border:1px solid #344452;border-radius:4px;padding:4px}.ds-h3-item.selected{border-color:#73c7ef;background:#1b2933}.ds-h3-item img,.ds-h3-item video{width:50px;height:38px;object-fit:cover;background:#090d11}.ds-h3-item audio{width:50px}.ds-h3-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ds-h3-muted{color:#8fa3b2}.ds-h3-prompt{width:100%;min-height:88px;box-sizing:border-box;background:#0d1217;color:#e5eef4;border:1px solid #40515e;border-radius:4px;padding:7px;resize:vertical}.ds-h3-prompt-panel{width:100%;box-sizing:border-box;border:0;border-radius:0;padding:0;display:flex;flex-direction:column;gap:6px;background:transparent}.ds-h3-block{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:5px;align-items:start}.ds-h3-status{min-height:16px;color:#f3c67a}.ds-h3-info-field{box-sizing:border-box;min-height:28px;border:1px solid #40515e;border-radius:4px;padding:6px 7px;background:#0d1217}.ds-h3-status.error{color:#ff6f6f;font-weight:700}.ds-h3-danger{color:#ff9e9e}.ds-h3-small{font-size:11px;color:#9fb3c2}.ds-h3-ruler{position:relative;height:19px;color:#8fa3b2;font-size:10px;white-space:nowrap;overflow:hidden}.ds-h3-ruler span{position:absolute;top:1px;border-left:1px solid #587084;padding-left:2px;height:16px}.ds-h3-track{position:relative;min-height:280px;max-width:100%;overflow-x:auto;overflow-y:hidden;background:#0b1015;border:1px solid #344452;border-radius:5px;padding:7px 6px 6px}.ds-h3-track::before{content:none}.ds-h3-track-inner{position:relative;min-width:100%;height:204px;overflow:visible;background:repeating-linear-gradient(90deg,#111a21 0,#111a21 49px,#1b2933 50px)}.ds-h3-track-inner::after{content:'';position:absolute;left:var(--insert-x,-8px);top:0;height:204px;border-left:2px solid #f3c67a;pointer-events:none}.ds-h3-track-inner.over{outline:2px solid #8dd7ff;outline-offset:-2px}.ds-h3-timeline-lane{position:absolute;left:0;right:0;height:120px;box-sizing:border-box;border-bottom:1px solid #344452;cursor:pointer}.ds-h3-empty-slot{position:absolute;top:21px;height:88px;box-sizing:border-box;border:1px dashed #587084;border-radius:4px;display:flex;align-items:center;justify-content:center;color:#7890a0;font-size:10px;pointer-events:none}.ds-h3-timeline-lane.disabled .ds-h3-empty-slot{display:none}.ds-h3-timeline-lane.visual{top:0;background:rgba(17,30,39,.72)}.ds-h3-timeline-lane.audio{top:120px;background:rgba(22,49,36,.55)}.ds-h3-timeline-lane.selected{box-shadow:inset 0 0 0 2px #8dd7ff}.ds-h3-timeline-lane.disabled{background:rgba(51,55,60,.72);filter:grayscale(1);cursor:not-allowed}.ds-h3-timeline-lane.disabled::after{content:"Not supported by the selected mode";position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#a1a8ad;font-size:11px;font-weight:600;background:rgba(0,0,0,.35);pointer-events:none}.ds-h3-lane-label{position:absolute;left:5px;top:2px;color:#8fa3b2;font-size:10px;text-transform:uppercase;pointer-events:none;z-index:1}.ds-h3-grip{position:absolute;top:0;width:11px;height:100%;cursor:ew-resize;background:rgba(255,255,255,.22);z-index:4}.ds-h3-grip.left{left:0;border-right:1px solid rgba(255,255,255,.65)}.ds-h3-grip.right{right:0;border-left:1px solid rgba(255,255,255,.65)}.ds-h3-clip{position:absolute;top:18px;height:48px;min-width:64px;box-sizing:border-box;border:1px solid #73c7ef;border-radius:4px;background:#1b4558;color:#e5eef4;padding:6px 14px 19px;cursor:grab;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ds-h3-clip.image,.ds-h3-clip.video{min-width:112px!important;width:112px!important;height:112px;top:7px}.ds-h3-clip.audio{border-color:#7ecf9d;background:#254b38;top:7px;height:112px}.ds-h3-waveform{position:absolute;inset:22px 12px 55px;width:calc(100% - 24px);height:calc(100% - 77px);pointer-events:none;opacity:.9}.ds-h3-crop-marker,.ds-h3-audio-crop-marker{position:absolute;top:20px;bottom:18px;width:4px;background:#fff;box-shadow:0 0 4px #000;cursor:ew-resize;z-index:6}.ds-h3-crop-marker.start,.ds-h3-audio-crop-marker.start{background:#f3c67a}.ds-h3-crop-marker.end,.ds-h3-audio-crop-marker.end{background:#8dd7ff;transform:translateX(-4px)}.ds-h3-crop-readout{position:absolute;left:14px;right:14px;bottom:3px;font-size:10px;line-height:12px;color:#d9f5e2;background:rgba(0,0,0,.36);pointer-events:none;text-align:center;overflow:hidden;white-space:nowrap}.ds-h3-clip-close{position:absolute!important;right:2px;top:2px;width:18px;height:18px;padding:0!important;line-height:15px!important;font-size:16px;color:#fff!important;background:rgba(105,28,28,.9)!important;border-color:#f08080!important;z-index:5}.ds-h3-clip.video{border-color:#b887d8;background:#432e52}.ds-h3-clip.text{border-color:#83c98a;background:#27442d}
  `;
  style.textContent += `.ds-h3-preview-overlay{position:fixed;inset:0;z-index:10001;display:flex;align-items:center;justify-content:center;background:rgba(8,10,14,.6)}.ds-h3-preview-panel{width:min(600px,90vw);max-height:85vh;display:flex;flex-direction:column;background:#111820;border:1px solid #40515e;border-radius:10px;overflow:hidden;box-shadow:0 8px 32px #000}.ds-h3-preview-header,.ds-h3-preview-meta{padding:8px 12px;background:#0d1217;color:#dbe7f0}.ds-h3-preview-header{display:flex;justify-content:space-between;border-bottom:1px solid #344452}.ds-h3-preview-body{padding:12px;background:#090d11;display:flex;justify-content:center}.ds-h3-preview-media{max-width:100%;max-height:40vh;object-fit:contain}.ds-h3-preview-controls{padding:8px 12px;background:#0d1217;display:flex;flex-direction:column;gap:6px}.ds-h3-preview-row{display:flex;align-items:center;gap:6px;flex-wrap:wrap;font-size:11px;color:#9fb3c2}.ds-h3-preview-row input[type="number"]{width:60px;padding:2px 4px;background:#111a21;color:#dbe7f0;border:1px solid #40515e;border-radius:3px}.ds-h3-preview-row input[type="text"],.ds-h3-preview-row textarea{flex:1;min-width:150px;padding:3px 5px;background:#111a21;color:#dbe7f0;border:1px solid #40515e;border-radius:3px;font-size:11px}.ds-h3-preview-row textarea{resize:vertical;min-height:30px}.ds-h3-preview-meta{font-size:11px;color:#9fb3c2;border-top:1px solid #344452}`;
  style.textContent += `
    .ds-h3-docs{font-weight:700;min-width:26px;padding:4px 8px!important}.ds-h3-ruler{display:none}.ds-h3-clip.video{width:var(--clip-width)!important;min-width:180px!important}.ds-h3-clip-identity{position:absolute;left:5px;top:4px;z-index:5;padding:1px 4px;border-radius:3px;background:rgba(0,0,0,.65);color:#fff;font-size:10px;font-weight:700;pointer-events:none}.ds-h3-video-scale{position:absolute;left:12px;right:12px;top:27px;height:44px;pointer-events:none;opacity:.8;background:repeating-linear-gradient(90deg,rgba(216,174,245,.82) 0,rgba(216,174,245,.82) 1px,transparent 1px,transparent 12px),linear-gradient(transparent 48%,rgba(216,174,245,.7) 49%,rgba(216,174,245,.7) 52%,transparent 53%)}.ds-h3-prompt-panel{min-height:120px;overflow:visible}.ds-h3-prompt-field{position:relative;flex:none;min-height:90px}.ds-h3-prompt-panel .ds-h3-prompt-field>.ds-h3-prompt{height:100%;min-height:0;padding-bottom:16px;resize:none}.ds-h3-prompt-field-resizer{position:absolute;bottom:0;left:0;width:100%;height:12px;cursor:ns-resize;display:flex;justify-content:center;align-items:flex-end;padding-bottom:4px;box-sizing:border-box;z-index:2;touch-action:none}.ds-h3-prompt-field-resizer::after{content:"";width:40px;height:4px;background:rgba(255,255,255,.16);border-radius:2px}.ds-h3-prompt-field-resizer:hover::after,.ds-h3-prompt-field-resizer.active::after{background:rgba(141,215,255,.8)}
    .ds-h3-video-stream-controls{position:absolute;right:5px;top:4px;z-index:7;display:flex;gap:3px}.ds-h3-clip.selected .ds-h3-video-stream-controls{right:24px}.ds-h3-video-stream-controls button{min-width:24px;padding:3px 6px!important;font-size:11px;line-height:14px;background:rgba(10,17,23,.85)!important}.ds-h3-video-stream-controls button.active{background:rgba(125,82,188,.9)!important;border-color:#d4b3ff;color:#fff}.ds-h3-lock-icon{position:absolute;right:4px;top:4px;z-index:8;font-size:13px;color:#f3c67a;text-shadow:0 0 4px rgba(0,0,0,.9);pointer-events:none}.ds-h3-edit-btn{position:absolute;right:5px;bottom:5px;z-index:7;font-size:14px;padding:3px 6px!important;border-radius:3px!important;background:rgba(20,35,45,.8)!important;border-color:rgba(100,150,180,.5)!important}.ds-h3-empty-slot{display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:700;color:#7eeba7;border:1.5px dashed #7eeba7;border-radius:6px;cursor:pointer;box-sizing:border-box;background:rgba(126,235,167,.06);transition:all .15s ease;pointer-events:auto}.ds-h3-empty-slot:hover{background:rgba(126,235,167,.18);border-color:#bff3d0;color:#d4ffe1;box-shadow:0 0 14px rgba(126,235,167,.45);transform:scale(1.02)}.ds-h3-timeline-lane.disabled .ds-h3-empty-slot{opacity:.15;cursor:not-allowed;pointer-events:none}.ds-h3-timeline-lane.audio .ds-h3-empty-slot{color:#5b8dd9;border-color:#5b8dd9;background:rgba(91,141,217,.06)}.ds-h3-timeline-lane.audio .ds-h3-empty-slot:hover{background:rgba(91,141,217,.18);border-color:#8bb4f0;color:#b3d4fc;box-shadow:0 0 14px rgba(91,141,217,.45)}
  `;
  document.head.appendChild(style);
}

function parseState(value) { try { const s = JSON.parse(value || "{}"); return { ...DEFAULT_STATE, ...s, items: Array.isArray(s.items) ? s.items : [], prompt_blocks: Array.isArray(s.prompt_blocks) ? s.prompt_blocks : [] }; } catch { return structuredClone(DEFAULT_STATE); } }
function viewUrl(path) { return api.apiURL(`/view?filename=${encodeURIComponent(path)}&type=input`); }
function count(state, type) { return state.items.filter(i => i.enabled !== false && i.type === type).length; }
function escapeText(text) { return String(text ?? ""); }
function idFor(type, n) { return `${type}-${Date.now()}-${n}`; }
function mediaTypeFor(file) {
  if (file.type.startsWith("image/")) return "image";
  if (file.type.startsWith("video/")) return "video";
  if (file.type.startsWith("audio/")) return "audio";
  const extension = String(file.name || "").split(".").pop().toLowerCase();
  if (IMAGE_EXTENSIONS.has(extension)) return "image";
  if (VIDEO_EXTENSIONS.has(extension)) return "video";
  return AUDIO_EXTENSIONS.has(extension) ? "audio" : null;
}
function mediaLabel(item) {
  const name = String(item.value || "media").split("/").pop();
  const prompt = String(item.prompt || "").trim().replace(/\s+/g, " ");
  const promptPreview = prompt ? ` · “${prompt.slice(0, 42)}${prompt.length > 42 ? "…" : ""}”` : "";
  if (item.type === "image") return `${name}${promptPreview}`;
  const duration = Number(item.duration);
  const durationText = Number.isFinite(duration) ? ` · ${duration.toFixed(2)}s` : "";
  const trim = (item.type === "video" || item.type === "audio") && (Number(item.trim_start) > 0 || item.trim_end != null)
    ? ` · crop L ${Number(item.trim_start || 0).toFixed(2)}s / R ${item.trim_end == null ? "end" : `${Number(item.trim_end).toFixed(2)}s`}` : "";
  return `${name}${durationText}${trim}${promptPreview}`;
}

const mediaReferenceName = type => type === "image" ? "Picture" : type === "video" ? "Video" : type === "audio" ? "Audio" : "Media";

function refImageSlots(node) {
  return (node.inputs || [])
    .map((input, index) => ({ input, index, match: /^ref_image_(\d+)$/.exec(input?.name || "") }))
    .filter(slot => slot.match)
    .map(slot => ({ ...slot, num: Number(slot.match[1]) }))
    .sort((a, b) => a.num - b.num);
}

function updateDynamicRefImageInputs(node) {
  if (!String(node.comfyClass || "").includes("FolderBatch")) return;
  let slots = refImageSlots(node);
  let highestConnected = 2;
  for (const slot of slots) {
    if (slot.input?.link != null) highestConnected = Math.max(highestConnected, slot.num);
  }
  const targetHighest = highestConnected + 1;
  let highestExisting = slots.length ? slots[slots.length - 1].num : 2;
  while (highestExisting < targetHighest) {
    highestExisting += 1;
    node.addInput(`ref_image_${highestExisting}`, "IMAGE");
    slots = refImageSlots(node);
  }
  for (let i = slots.length - 1; i >= 0; i -= 1) {
    const slot = slots[i];
    if (slot.num <= targetHighest || slot.input?.link != null) continue;
    const inputIndex = node.findInputSlot(slot.input.name);
    if (inputIndex >= 0) node.removeInput(inputIndex);
  }
  const computed = node.computeSize?.();
  if (computed) {
    node.size[0] = Math.max(node.size?.[0] || 0, computed[0]);
    node.size[1] = Math.max(node.size?.[1] || 0, computed[1]);
  }
  app.graph?.setDirtyCanvas(true, true);
}

async function uploadFile(file, status) {
  const form = new FormData();
  form.append("image", file, file.name);
  form.append("type", "input");
  form.append("overwrite", "false");
  status.textContent = `Uploading ${file.name}…`;
  const response = await api.fetchApi("/upload/image", { method: "POST", body: form });
  if (!response.ok) throw new Error(`upload failed (${response.status})`);
  const result = await response.json();
  return result.subfolder ? `${result.subfolder}/${result.name}` : result.name;
}

function insertAtCursor(textarea, text) {
  const start = textarea.selectionStart || 0;
  const end = textarea.selectionEnd || 0;
  textarea.value = textarea.value.slice(0, start) + text + textarea.value.slice(end);
  textarea.selectionStart = textarea.selectionEnd = start + text.length;
  textarea.focus();
  textarea.dispatchEvent(new Event("change"));
}

function createBuilderField(label, value, opts = {}) {
  const wrapper = document.createElement("div");
  wrapper.className = "ds-h3-prompt-field";
  wrapper.style.display = "flex"; wrapper.style.flexDirection = "column"; wrapper.style.gap = "2px"; wrapper.style.position = "relative";
  if (opts.dataAttr) wrapper.dataset.ref2vaTarget = opts.dataAttr;
  if (label) { const lbl = document.createElement("div"); lbl.className = "ds-h3-small"; lbl.textContent = label; wrapper.appendChild(lbl); }
  const area = document.createElement(opts.tag || "textarea");
  area.className = opts.class || "ds-h3-prompt";
  area.rows = opts.rows || 3;
  area.placeholder = opts.placeholder || "";
  area.value = value || "";
  if (opts.onChange) area.onchange = e => opts.onChange(e.target.value);
  wrapper.appendChild(area);
  const resizer = document.createElement("div");
  resizer.className = "ds-h3-prompt-field-resizer";
  let dragging = false, startY = 0, startH = 0;
  resizer.addEventListener("pointerdown", ev => { dragging = true; startY = ev.clientY; startH = area.clientHeight; area.setPointerCapture(ev.pointerId); });
  window.addEventListener("pointermove", ev => { if (!dragging) return; area.style.height = Math.max(60, startH + (ev.clientY - startY)) + "px"; });
  window.addEventListener("pointerup", () => { dragging = false; });
  wrapper.appendChild(resizer);
  return wrapper;
}

function install(node) {
  if (node.__dasiwaH3Installed) return;
  node.__dasiwaH3Installed = true;
  installStyles();
  const dataWidget = node.widgets?.find(w => w.name === "timeline_data");
  if (!dataWidget) return;
  const isFolderBatch = String(node.comfyClass || "").includes("FolderBatch");
  dataWidget.hidden = true; dataWidget.options = { ...(dataWidget.options || {}), hidden: true };
  dataWidget.draw = () => {}; dataWidget.computeSize = () => [0, -4];
  let state = parseState(dataWidget.value);
  const mode = () => node.widgets?.find(w => w.name === "mode")?.value || "FL2VA";
  const sourceMode = () => ["auto", "source_image", "node_upload_or_folder"].includes(state.image_source_mode) ? state.image_source_mode : "auto";
  const useEndFrame = () => state.use_end_frame !== false;
  let builderState = state.builder_state && typeof state.builder_state === "object" ? { ...DEFAULT_BUILDER_STATE(mode()), ...state.builder_state, ref: { ...DEFAULT_BUILDER_STATE(mode()).ref, ...(state.builder_state.ref || {}) } } : DEFAULT_BUILDER_STATE(mode());
  builderState.mode = mode();
  const builderWidget = node.widgets?.find(w => w.name === "builder_state");
  if (builderWidget) { builderWidget.hidden = true; builderWidget.draw = () => {}; builderWidget.computeSize = () => [0, -4]; }
  const modeWidget = node.widgets?.find(w => w.name === "mode");
  if (modeWidget) { modeWidget.hidden = true; modeWidget.draw = () => {}; modeWidget.computeSize = () => [0, -4]; }
  const prompt = () => node.widgets?.find(w => w.name === "prompt");
  const promptWidget = prompt(); if (promptWidget) { promptWidget.hidden = true; promptWidget.draw = () => {}; promptWidget.computeSize = () => [0, -4]; }
  const status = document.createElement("div"); status.className = "ds-h3-status ds-h3-info-field"; status.textContent = ""; status.style.display = "none";
  const timeline = document.createElement("div"); timeline.className = "ds-h3 ds-h3-root"; timeline.tabIndex = 0;
  const setStatus = (message, isError = false) => { status.textContent = message; status.classList.toggle("error", isError); };
  const emit = () => { builderState.mode = mode(); state.builder_state = builderState; dataWidget.value = JSON.stringify(state); dataWidget.callback?.(dataWidget.value); if (builderWidget) { builderWidget.value = JSON.stringify(builderState); builderWidget.callback?.(builderWidget.value); } node.graph?.setDirtyCanvas(true, true); };
  const allowNativeTextEditing = element => { ["pointerdown","mousedown","keydown","keypress","keyup","copy","cut","paste"].forEach(type => element.addEventListener(type, event => event.stopPropagation())); };

  function buildBaseForm(panel) {
    panel.replaceChildren();
    const label = document.createElement("div"); label.className = "ds-h3-small"; label.textContent = `${mode()} prompt builder`; panel.appendChild(label);
    const imdArea = createBuilderField("integrated_multimodal_description", builderState.imd, { rows: 6, placeholder: "[Shot 1] Start your scene description here...", onChange: val => { builderState.imd = val; emit(); } });
    allowNativeTextEditing(imdArea.querySelector("textarea"));
    const helpers = document.createElement("div"); helpers.className = "ds-h3-actions";
    const shotBtn = document.createElement("button"); shotBtn.textContent = "Insert [Shot N]"; shotBtn.onclick = () => { const n = window.prompt("Shot number:", "1"); if (n) insertAtCursor(imdArea.querySelector("textarea"), `[Shot ${n}] `); }; helpers.appendChild(shotBtn);
    panel.appendChild(helpers); panel.appendChild(imdArea);
    const soundscape = createBuilderField("overall_soundscape", builderState.soundscape, { rows: 3, placeholder: "Describe ambient sounds, dialogue, effects...", onChange: val => { builderState.soundscape = val; emit(); } }); allowNativeTextEditing(soundscape.querySelector("textarea")); panel.appendChild(soundscape);
    const music = createBuilderField("non_diegetic_music", builderState.music, { rows: 2, placeholder: 'N/A or describe background score...', onChange: val => { builderState.music = val; emit(); } }); allowNativeTextEditing(music.querySelector("textarea")); panel.appendChild(music);
  }

  function buildRefForm(panel) {
    panel.replaceChildren();
    const r = builderState.ref || {};
    const label = document.createElement("div"); label.className = "ds-h3-small"; label.textContent = "REF2VA prompt builder — write freely; headers are added automatically"; panel.appendChild(label);
    const helpers = document.createElement("div"); helpers.className = "ds-h3-actions";
    const shotBtn = document.createElement("button"); shotBtn.textContent = "Insert [Shot N]"; shotBtn.onclick = () => { const wrapper = panel.querySelector("[data-ref2va-target='detail']"); const ta = wrapper?.querySelector("textarea") ?? wrapper; const n = window.prompt("Shot number:", "1"); if (n && ta) insertAtCursor(ta, `[Shot ${n}] `); }; helpers.appendChild(shotBtn);
    const prefillBtn = document.createElement("button"); prefillBtn.textContent = "Prefill Labels & Summary"; prefillBtn.title = "Generate Subject/Picture/Video/Audio labels from inserted media and fill summary template"; prefillBtn.onclick = () => { generateRefLabelsAndSummary(panel); }; helpers.appendChild(prefillBtn);
    const previewBtn = document.createElement("button"); previewBtn.textContent = "Preview Prompt"; previewBtn.title = "Show the full prompt that will be sent upstream"; previewBtn.onclick = () => { showPromptPreview(); }; helpers.appendChild(previewBtn);
    panel.appendChild(helpers);
    const subjField = createBuilderField("subject_definitions:", r.subject_definitions, { rows: 4, placeholder: "<Subject 1> is the woman in <Picture 1>, with short dark hair and a red coat.\n<Picture 1> is the opening-frame anchor for [Shot 1].\n<Subject 2> is the walking motion taken from <Video 1>.\n<Video 1> provides the camera path and pacing structure.\n<Audio 1> is the voice-timbre reference for <Subject 1>.", onChange: val => { r.subject_definitions = val; emit(); } }); allowNativeTextEditing(subjField.querySelector("textarea")); panel.appendChild(subjField);
    const summaryField = createBuilderField("summary:", r.summary, { rows: 3, placeholder: "[reference generation + audio reference] Use <Subject 1> from <Picture 1>, the motion and pacing of <Video 1>, and the voice character of <Audio 1>.", onChange: val => { r.summary = val; emit(); } }); allowNativeTextEditing(summaryField.querySelector("textarea")); panel.appendChild(summaryField);
    const retField = createBuilderField("retention_analysis:", r.retention_analysis, { rows: 4, placeholder: "<Subject 1> (appears in [Shot 1], [Shot 2]): fully_preserved - identity and clothing remain consistent.\n<Picture 1> ([Shot 1] first frame): fully_preserved - opening composition anchor.\n<Subject 2> (motion transferred to <Subject 1>): attribute_transfer - walk rhythm is applied to <Subject 1>.\n<Video 1> (pacing structure): weak_reference - general timing and camera rhythm are retained.\n<Audio 1>: reference - timbre and delivery are followed without copying the signal.", onChange: val => { r.retention_analysis = val; emit(); } }); allowNativeTextEditing(retField.querySelector("textarea")); panel.appendChild(retField);
    const detailField = createBuilderField("detailed_description:", r.detailed_description, { rows: 5, placeholder: "[Shot 1] ... [Shot 2] At 00:04.500, ...", dataAttr: "detail", onChange: val => { r.detailed_description = val; emit(); } }); allowNativeTextEditing(detailField.querySelector("textarea")); panel.appendChild(detailField);
    const rsoundField = createBuilderField("overall_soundscape:", r.soundscape, { rows: 2, placeholder: "Audio environment description...", onChange: val => { r.soundscape = val; emit(); } }); allowNativeTextEditing(rsoundField.querySelector("textarea")); panel.appendChild(rsoundField);
    const rmusicField = createBuilderField("non_diegetic_music:", r.music, { rows: 2, placeholder: "N/A or background score...", onChange: val => { r.music = val; emit(); } }); allowNativeTextEditing(rmusicField.querySelector("textarea")); panel.appendChild(rmusicField);
  }

  function generateRefLabelsAndSummary(panel) {
    const items = activeItems().sort((a, b) => {
      const typeOrder = { image: 0, video: 1, audio: 2 };
      return (typeOrder[a.type] ?? 3) - (typeOrder[b.type] ?? 3) || a.slot - b.slot;
    });
    const pictures = []; const videos = []; const audios = [];
    items.forEach(item => {
      if (item.type === "image") pictures.push(item);
      else if (item.type === "video") videos.push(item);
      else if (item.type === "audio") audios.push(item);
    });
    const subjLines = [];
    let pictureIdx = 1; let videoIdx = 1; let audioIdx = 1;
    pictures.forEach(item => {
      subjLines.push(`<Picture ${pictureIdx}> is the opening-frame anchor.`);
      pictureIdx++;
    });
    videos.forEach(item => {
      subjLines.push(`<Video ${videoIdx}> provides the camera path and pacing structure.`);
      videoIdx++;
    });
    audios.forEach(item => {
      subjLines.push(`<Audio ${audioIdx}> is the voice-timbre and audio reference.`);
      audioIdx++;
    });
    const subjArea = panel.querySelector("[data-ref2va-target='subj']")?.querySelector("textarea") || panel.querySelectorAll(".ds-h3-prompt")[0]?.querySelector("textarea") || panel.querySelectorAll(".ds-h3-prompt")[0];
    if (subjArea && subjLines.length > 0) {
      subjArea.value = subjLines.join("\n");
      builderState.ref.subject_definitions = subjArea.value;
    }
    const summaryArea = panel.querySelectorAll(".ds-h3-prompt")[1]?.querySelector("textarea") || panel.querySelectorAll(".ds-h3-prompt")[1];
    if (summaryArea) {
      const refs = [];
      pictures.forEach((_, i) => refs.push(`<Picture ${i + 1}>`));
      videos.forEach((_, i) => refs.push(`<Video ${i + 1}>`));
      audios.forEach((_, i) => refs.push(`<Audio ${i + 1}>`));
      const taskPrefixes = [];
      if (pictures.length > 0) taskPrefixes.push("reference generation");
      if (videos.length > 0) taskPrefixes.push("video editing");
      if (audios.length > 0) taskPrefixes.push("audio reference");
      const prefix = taskPrefixes.length ? `[${taskPrefixes.join(" + ")}] ` : "";
      const summaryLine = prefix + "Use " + refs.map(r => r).join(", ") + ".";
      summaryArea.value = summaryLine;
      builderState.ref.summary = summaryArea.value;
    }
    emit();
  }

  function showPromptPreview() {
    const m = mode();
    let promptText = "";
    if (m === "REF2VA") {
      const areas = timeline.querySelectorAll(".ds-h3-prompt-panel .ds-h3-prompt");
      const vals = [];
      areas.forEach(a => vals.push(String(a.value || "").trim()));
      const subj = vals[0] || "";
      const summ = vals[1] || "";
      const ret = vals[2] || "";
      const detail = vals[3] || "";
      const sound = vals[4] || "";
      const music = vals[5] || "N/A";
      promptText =
`subject_definitions:
${subj}

summary:
${summ}

retention_analysis:
${ret}

detailed_description:
${detail}

overall_soundscape:
${sound}

non_diegetic_music:
${music}`;
    } else {
      const areas = timeline.querySelectorAll(".ds-h3-prompt-panel .ds-h3-prompt");
      const imd = String(areas[0]?.value || "").trim();
      const sound = String(areas[1]?.value || "").trim();
      const music = String(areas[2]?.value || "N/A").trim();
      let head = "";
      if (m === "I2VA") {
        head = "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.";
      } else if (m === "FL2VA") {
        head = "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 2) aligns with the end mark of the target video.";
      } else if (m === "L2VA") {
        head = "How the reference pictures align with the target video — <Picture 1> (from [Shot 1]) aligns with the end mark of the target video.";
      }
      const body = `integrated_multimodal_description: ${imd}

overall_soundscape: ${sound}

non_diegetic_music: ${music}`;
      promptText = head ? `${head}

${body}` : body;
    }
    let overlay = document.createElement("div"); overlay.style.cssText = "position:fixed;inset:0;z-index:10002;display:flex;align-items:center;justify-content:center;background:rgba(8,10,14,.7);";
    overlay.onclick = event => { if (event.target === overlay) overlay.remove(); };
    const panel = document.createElement("div"); panel.style.cssText = "width:min(720px,90vw);max-height:85vh;display:flex;flex-direction:column;background:#111820;border:1px solid #40515e;border-radius:10px;overflow:hidden;box-shadow:0 8px 32px #000;";
    const header = document.createElement("div"); header.style.cssText = "padding:8px 12px;background:#0d1217;color:#dbe7f0;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #344452;";
    header.innerHTML = `<span>Prompt Preview (${m})</span><button title="Copy">📋</button>`;
    const copyBtn = header.querySelector("button");
    copyBtn.onclick = () => { navigator.clipboard.writeText(promptText).then(() => { copyBtn.textContent = "✓"; setTimeout(() => copyBtn.textContent = "📋", 1200); }).catch(() => { copyBtn.textContent = "×"; }); };
    const closeBtn = document.createElement("button"); closeBtn.textContent = "×"; closeBtn.style.cssText = "background:none;border:none;color:#fff;font-size:18px;cursor:pointer;padding:0 4px;"; closeBtn.onclick = () => overlay.remove(); header.appendChild(closeBtn);
    const body = document.createElement("div"); body.style.cssText = "padding:10px 12px;overflow:auto;";
    const textarea = document.createElement("textarea"); textarea.readOnly = true; textarea.value = promptText; textarea.style.cssText = "width:100%;min-height:300px;max-height:60vh;resize:vertical;background:#090d11;color:#e5eef4;border:1px solid #40515e;border-radius:4px;padding:7px;font-family:monospace;font-size:11px;line-height:1.4;box-sizing:border-box;"; body.appendChild(textarea);
    const footer = document.createElement("div"); footer.style.cssText = "padding:8px 12px;background:#0d1217;display:flex;justify-content:flex-end;gap:6px;border-top:1px solid #344452;";
    const doneBtn = document.createElement("button"); doneBtn.textContent = "Done"; doneBtn.onclick = () => overlay.remove(); footer.appendChild(doneBtn);
    panel.append(header, body, footer); overlay.appendChild(panel); document.body.appendChild(overlay);
    window.addEventListener("keydown", event => { if (event.key === "Escape") overlay.remove(); }, { once: true });
  }

  let previewOverlay = null;
  let previewCloseFn = null;
  let previewItemRef = null;
  function closePreview(discard = false) {
    if (!discard && previewOverlay && previewItemRef) {
      applyPreviewChanges(previewOverlay, previewItemRef);
    }
    previewOverlay?.remove();
    previewOverlay = null;
    previewItemRef = null;
    if (previewCloseFn) window.removeEventListener("keydown", previewCloseFn);
    previewCloseFn = null;
  }
  function applyPreviewChanges(overlay, item) {
    const tsInput = overlay.querySelector(".ds-h3-ts-input");
    const teInput = overlay.querySelector(".ds-h3-te-input");
    const sourceDuration = Number(item.source_duration) || Number(item.duration) || 0;
    if ((item.type === "video" || item.type === "audio") && sourceDuration > 0) {
      const ts = parseFloat(tsInput?.value) ?? 0;
      const te = parseFloat(teInput?.value) ?? sourceDuration;
      mutate(s => {
        const x = s.items.find(i => i.id === item.id);
        if (x) {
          x.trim_start = Math.min(sourceDuration, Math.max(0, ts));
          x.trim_end = Math.min(sourceDuration, Math.max(x.trim_start + 2, te));
          x.duration = x.trim_end - x.trim_start;
        }
      });
    }
  }
  function openPreview(item) {
    closePreview();
    previewItemRef = item;
    const sourceDuration = Number(item.source_duration) || Number(item.duration) || 0;
    const trimStart = Number(item.trim_start || 0);
    const trimEnd = Number(item.trim_end ?? sourceDuration);
    previewOverlay = document.createElement("div"); previewOverlay.className = "ds-h3-preview-overlay";
    previewOverlay.onclick = event => { if (event.target === previewOverlay) closePreview(); };
    const panel = document.createElement("div"); panel.className = "ds-h3-preview-panel";
    const header = document.createElement("div"); header.className = "ds-h3-preview-header";
    const title = document.createElement("span"); title.textContent = `${item.type}: ${String(item.value || "").split("/").pop()}`;
    const close = document.createElement("button"); close.textContent = "×"; close.title = "Close and save (Escape or click outside)"; close.onclick = () => closePreview(false); header.append(title, close);
    const body = document.createElement("div"); body.className = "ds-h3-preview-body";
    const media = document.createElement(item.type === "image" ? "img" : item.type === "audio" ? "audio" : "video"); media.className = "ds-h3-preview-media"; media.src = viewUrl(item.value); if (item.type !== "image") media.controls = true; body.append(media);
    const controls = document.createElement("div"); controls.className = "ds-h3-preview-controls";
    if ((item.type === "video" || item.type === "audio") && sourceDuration > 0) {
      const row1 = document.createElement("div"); row1.className = "ds-h3-preview-row";
      const lblTs = document.createElement("span"); lblTs.textContent = "Start:"; row1.appendChild(lblTs);
      const tsInput = document.createElement("input"); tsInput.type = "number"; tsInput.step = "0.25"; tsInput.min = "0"; tsInput.max = String(sourceDuration.toFixed(2)); tsInput.value = String(trimStart.toFixed(2)); tsInput.className = "ds-h3-ts-input"; row1.appendChild(tsInput);
      const lblTe = document.createElement("span"); lblTe.textContent = "End:"; row1.appendChild(lblTe);
      const teInput = document.createElement("input"); teInput.type = "number"; teInput.step = "0.25"; teInput.min = "0"; teInput.max = String(sourceDuration.toFixed(2)); teInput.value = String(trimEnd.toFixed(2)); teInput.className = "ds-h3-te-input"; row1.appendChild(teInput);
      const lblDur = document.createElement("span"); lblDur.textContent = `/ ${sourceDuration.toFixed(2)}s`; row1.appendChild(lblDur);
      controls.appendChild(row1);
      const rowSlider = document.createElement("div"); rowSlider.className = "ds-h3-preview-row"; rowSlider.style.flexDirection = "column"; rowSlider.style.alignItems = "stretch";
      const minRef = Math.min(2, sourceDuration);
      const updateFromInputs = () => {
        let ts = parseFloat(tsInput.value) ?? 0;
        let te = parseFloat(teInput.value) ?? sourceDuration;
        ts = Math.min(Math.max(0, ts), sourceDuration - minRef);
        te = Math.max(ts + minRef, Math.min(sourceDuration, te));
        tsInput.value = ts.toFixed(2);
        teInput.value = te.toFixed(2);
        const sPct = (ts / sourceDuration) * 100;
        const ePct = (te / sourceDuration) * 100;
        rangeTs.value = sPct; rangeTe.value = ePct;
        syncMarkers();
      };
      const trackBg = document.createElement("div"); trackBg.style.cssText = "position:relative;height:18px;background:#111a21;border-radius:3px;margin-top:4px;margin-bottom:4px;";
      const filledBar = document.createElement("div"); filledBar.style.cssText = "position:absolute;top:0;left:0;right:0;bottom:0;border-radius:3px;background:rgba(126,210,157,.25);pointer-events:none;";
      const markerS = document.createElement("div"); markerS.style.cssText = "position:absolute;top:-2px;width:8px;height:22px;background:#f3c67a;border-radius:2px;z-index:3;cursor:pointer;transform:translateX(-50%);";
      const markerE = document.createElement("div"); markerE.style.cssText = "position:absolute;top:-2px;width:8px;height:22px;background:#8dd7ff;border-radius:2px;z-index:3;cursor:pointer;transform:translateX(-50%);";
      const rangeTs = document.createElement("input"); rangeTs.type = "range"; rangeTs.min = "0"; rangeTs.max = "100"; rangeTs.step = "0.1"; rangeTs.value = ((trimStart / sourceDuration) * 100).toFixed(1); rangeTs.style.cssText = "position:absolute;top:0;left:0;width:100%;height:100%;opacity:0;pointer-events:none;z-index:0;";
      const rangeTe = document.createElement("input"); rangeTe.type = "range"; rangeTe.min = "0"; rangeTe.max = "100"; rangeTe.step = "0.1"; rangeTe.value = ((trimEnd / sourceDuration) * 100).toFixed(1); rangeTe.style.cssText = "position:absolute;top:0;left:0;width:100%;height:100%;opacity:0;pointer-events:none;z-index:0;";
      const MARKER_GRAB_RADIUS = 12;
      const pointerPct = pointerX => {
        const rect = trackBg.getBoundingClientRect();
        return ((pointerX - rect.left) / rect.width) * 100;
      };
      const syncMarkers = () => {
        const sPct = parseFloat(rangeTs.value);
        const ePct = parseFloat(rangeTe.value);
        markerS.style.left = sPct + "%";
        markerE.style.left = ePct + "%";
        filledBar.style.left = sPct + "%";
        filledBar.style.right = (100 - ePct) + "%";
      };
      const clampSliders = () => {
        let s = parseFloat(rangeTs.value);
        let e = parseFloat(rangeTe.value);
        const gap = (minRef / sourceDuration) * 100;
        if (e - s < gap) {
          if (dragging === "left") e = s + gap;
          else s = e - gap;
        }
        rangeTs.value = Math.max(0, Math.min(s, 100 - gap));
        rangeTe.value = Math.max(gap, Math.min(e, 100));
        syncMarkers();
        const tsSec = (parseFloat(rangeTs.value) / 100) * sourceDuration;
        const teSec = (parseFloat(rangeTe.value) / 100) * sourceDuration;
        tsInput.value = tsSec.toFixed(2);
        teInput.value = teSec.toFixed(2);
      };
      let dragging = null;
      const onStart = pointerX => {
        const pct = pointerPct(pointerX);
        const sPct = parseFloat(rangeTs.value);
        const ePct = parseFloat(rangeTe.value);
        if (Math.abs(pct - sPct) <= MARKER_GRAB_RADIUS && Math.abs(pct - sPct) <= Math.abs(pct - ePct)) {
          dragging = "left";
        } else if (Math.abs(pct - ePct) <= MARKER_GRAB_RADIUS) {
          dragging = "right";
        } else {
          dragging = null;
        }
      };
      const onMove = pointerX => {
        if (!dragging) return;
        const pct = pointerPct(pointerX);
        if (dragging === "left") {
          rangeTs.value = Math.max(0, Math.min(100, pct));
        } else {
          rangeTe.value = Math.max(0, Math.min(100, pct));
        }
        clampSliders();
      };
      const onEnd = () => { dragging = null; };
      trackBg.addEventListener("mousedown", event => { onStart(event.clientX); });
      window.addEventListener("mousemove", event => { onMove(event.clientX); });
      window.addEventListener("mouseup", () => { onEnd(); });
      trackBg.addEventListener("touchstart", event => { onStart(event.touches[0].clientX); }, { passive: false });
      trackBg.addEventListener("touchmove", event => { event.preventDefault(); onMove(event.touches[0].clientX); }, { passive: false });
      trackBg.addEventListener("touchend", () => { onEnd(); });
      tsInput.onchange = updateFromInputs;
      teInput.onchange = updateFromInputs;
      updateFromInputs();
      trackBg.append(filledBar, markerS, markerE, rangeTs, rangeTe);
      rowSlider.appendChild(trackBg);
      controls.appendChild(rowSlider);
    }
    const row2 = document.createElement("div"); row2.className = "ds-h3-preview-row";
    const saveBtn = document.createElement("button"); saveBtn.textContent = "Save"; saveBtn.className = "ds-h3-save-btn"; saveBtn.onclick = () => { applyPreviewChanges(previewOverlay, item); closePreview(false); }; row2.appendChild(saveBtn);
    const cancelBtn = document.createElement("button"); cancelBtn.textContent = "Cancel"; cancelBtn.onclick = () => { closePreview(true); }; cancelBtn.style.background = "#2c2c2c"; row2.appendChild(cancelBtn);
    controls.appendChild(row2);
    const meta = document.createElement("div"); meta.className = "ds-h3-preview-meta"; meta.textContent = sourceDuration && (item.type === "video" || item.type === "audio") ? `Source: ${sourceDuration.toFixed(2)}s · Current crop: ${trimStart.toFixed(2)}s – ${trimEnd.toFixed(2)}s` : "Full media preview";
    panel.append(header, body, controls, meta); previewOverlay.append(panel); document.body.append(previewOverlay);
    previewCloseFn = event => { if (event.key === "Escape") closePreview(); };
    window.addEventListener("keydown", previewCloseFn);
  }
  const syncAttachedPrompts = () => { const attached = state.items.filter(item => String(item.prompt || "").trim()).map((item, index) => ({ id: `attached-${item.id}`, text: String(item.prompt).trim(), enabled: item.enabled !== false, start: Number(item.start) || 0, duration: Number(item.duration) || 1, order: index })); if (attached.length || state.items.every(item => !item.prompt)) state.prompt_blocks = attached; };
  const mutate = fn => { fn(state); syncAttachedPrompts(); state.items.forEach((x, i) => { x.order = i; }); state.prompt_blocks.forEach((x, i) => { x.order = i; }); emit(); render(); };
  const activeItems = () => state.items.filter(x => x.enabled !== false);
  const isReferenceMode = () => mode() === "REF2VA";
  const allowsType = type => isReferenceMode() || ((mode() === "I2VA" || mode() === "FL2VA" || mode() === "L2VA") && type === "image");
  const frameSlots = () => mode() === "T2VA" ? [] : mode() === "I2VA" ? [0] : mode() === "FL2VA" ? [0, 1] : mode() === "L2VA" ? [0, 1] : [];
  const imageCapacity = () => frameSlots().length;
  const isLockedSlot = (item) => mode() === "L2VA" && laneForItem(item) === "visual" && item.slot === 0;
  const displayedItems = () => isReferenceMode() ? activeItems() : activeItems().filter(x => x.type === "image").sort((a, b) => a.slot - b.slot).slice(0, imageCapacity());
  const ensureLayout = () => { let cursor = 0; state.items.forEach(item => { if (!Number.isFinite(item.start)) item.start = cursor; if (!Number.isFinite(item.duration)) item.duration = item.type === "image" ? 1 : 2; cursor = Math.max(cursor, item.start + item.duration + 0.25); }); };
  let insertAt = 0;
  let selectedId = null;
  let selectedLane = "visual";
  let lastTimelineLength = null;
  let mediaPromptHeight = Math.max(90, Number(state.media_prompt_height) || 120);
  let globalPromptHeight = Math.max(90, Number(state.global_prompt_height) || 120);
  const hiddenLanes = new Set();
  let compactLanes = false;
  const laneForItem = item => item.type === "audio" ? "audio" : "visual";
  const availableSlots = lane => lane === "audio" ? [...Array(isReferenceMode() ? MAX.audio : 0).keys()] : isReferenceMode() ? [...Array(MAX.image + MAX.video).keys()] : frameSlots();
  const slotCapacity = lane => availableSlots(lane).length;
  const addItem = item => mutate(s => { const lane = laneForItem(item); const occupied = new Set(s.items.filter(x => laneForItem(x) === lane).map(x => x.slot).filter(Number.isInteger)); const slot = availableSlots(lane).find(index => !occupied.has(index)); if (slot == null) throw new Error(`No free ${lane} slot is available.`); s.items.push({ id: idFor(item.type, s.items.length), enabled: true, order: s.items.length, slot, start: slot, duration: item.type === "image" ? 1 : 2, ...item }); });
  const remove = id => mutate(s => { s.items = s.items.filter(x => x.id !== id); if (selectedId === id) selectedId = null; });
  const clearAll = () => { selectedId = null; if (promptWidget) { promptWidget.value = ""; promptWidget.callback?.(promptWidget.value); } mutate(s => { s.items = []; s.prompt_blocks = []; }); setStatus("All media and prompts cleared."); };
  timeline.addEventListener("keydown", event => { if (event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLInputElement) return; if ((event.key === "Delete" || event.key === "Backspace") && selectedId) { const sel = state.items.find(x => x.id === selectedId); if (sel && isLockedSlot(sel)) { setStatus(`${mediaReferenceName(sel.type)} ${sel.slot + 1} is locked in L2VA mode`, true); return; } event.preventDefault(); event.stopPropagation(); remove(selectedId); } });
  const move = (id, delta) => mutate(s => { const i = s.items.findIndex(x => x.id === id); const j = i + delta; if (i >= 0 && j >= 0 && j < s.items.length) [s.items[i], s.items[j]] = [s.items[j], s.items[i]]; });
  const replace = (id, value) => mutate(s => { const x = s.items.find(i => i.id === id); if (x) x.value = value; });

  const addPath = type => { if (!allowsType(type)) return; if (count(state, type) >= MAX[type] || activeItems().length >= MAX.total) { status.textContent = `Limit reached: ${MAX[type]} ${type}s / ${MAX.total} files.`; return; } fileInput.accept = type === "image" ? "image/*" : type === "video" ? "video/*" : "audio/*"; fileInput.click(); };
  const fileInput = document.createElement("input"); fileInput.type = "file"; fileInput.multiple = true; fileInput.accept = "image/*,video/*,audio/*"; fileInput.hidden = true;
  fileInput.onchange = async () => { for (const file of fileInput.files || []) await acceptFile(file); fileInput.value = ""; };
  timeline.addEventListener("paste", async event => {
    if (event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLInputElement) return;
    const files = [...(event.clipboardData?.files || [])];
    if (!files.length) files.push(...[...(event.clipboardData?.items || [])].filter(item => item.kind === "file").map(item => item.getAsFile()).filter(Boolean));
    if (!files.length) return;
    event.preventDefault(); event.stopPropagation();
    if (mode() === "FL2VA" && selectedLane === "audio") { setStatus("FL2VA supports image references only; select the Image/Video lane.", true); return; }
    setStatus(`Pasting ${files.length} file${files.length === 1 ? "" : "s"} into the ${selectedLane === "audio" ? "Audio" : "Image/Video"} lane.`);
    for (const file of files) await acceptFile(file, selectedLane);
  });
  async function probeDuration(value, type) {
    if (type === "image") return null;
    const media = document.createElement(type === "video" ? "video" : "audio");
    media.preload = "metadata";
    media.src = viewUrl(value);
    return await new Promise(resolve => {
      const done = result => { media.remove(); resolve(Number.isFinite(result) ? result : null); };
      media.onloadedmetadata = () => done(media.duration);
      media.onerror = () => done(null);
    });
  }
  async function captureFirstFrame(videoUrl) {
    return await new Promise(resolve => {
      const vid = document.createElement("video");
      vid.preload = "auto"; vid.muted = true; vid.crossOrigin = "";
      const fail = () => { vid.remove(); resolve(null); };
      const draw = () => {
        try {
          const c = document.createElement("canvas");
          c.width = vid.videoWidth || 160; c.height = vid.videoHeight || 96;
          const ctx = c.getContext("2d");
          ctx.drawImage(vid, 0, 0, c.width, c.height);
          vid.remove();
          resolve(c.toDataURL("image/jpeg", 0.7));
        } catch { fail(); }
      };
      vid.onloadeddata = () => { vid.currentTime = 0; };
      vid.onseeked = draw;
      vid.onerror = fail;
      vid.src = videoUrl;
    });
  }
  async function extractWaveform(value, id) {
    try {
      const audioContext = new (window.AudioContext || window.webkitAudioContext)();
      const response = await fetch(viewUrl(value));
      const buffer = await audioContext.decodeAudioData(await response.arrayBuffer());
      const channel = buffer.getChannelData(0); const peakCount = 240; const step = Math.max(1, Math.floor(channel.length / peakCount)); const peaks = [];
      for (let index = 0; index < peakCount; index += 1) { let peak = 0; for (let sample = index * step; sample < Math.min(channel.length, (index + 1) * step); sample += 1) peak = Math.max(peak, Math.abs(channel[sample])); peaks.push(peak); }
      audioContext.close?.();
      mutate(s => { const item = s.items.find(x => x.id === id); if (item) item.waveform_peaks = peaks; });
    } catch (error) { console.warn("[MiniMax H3 Director] Audio waveform decode failed", error); }
  }
  async function acceptFile(file, targetLane = null) { const type = mediaTypeFor(file); const validLane = targetLane === "visual" ? type === "image" || type === "video" : targetLane === "audio" ? type === "audio" : true; const modeSupportsType = !!type && allowsType(type); const lane = type === "audio" ? "audio" : "visual"; if (!type || !validLane || !modeSupportsType) { const requirement = mode() === "FL2VA" ? "FL2VA supports image references only; video and audio are unavailable." : targetLane ? `Drop ${targetLane === "audio" ? "audio" : "image or video"} files on this lane.` : "This media type is not available in the selected MiniMax mode."; setStatus(requirement, true); return; } if (count(state, type) >= MAX[type] || activeItems().length >= MAX.total) { setStatus(`Limit reached: ${MAX[type]} ${type}s / ${MAX.total} files.`, true); return; } const laneAvail = availableSlots(lane); const laneOccupied = new Set(activeItems().filter(x => laneForItem(x) === lane).map(x => x.slot).filter(Number.isInteger)); const laneFree = laneAvail.some(slot => !laneOccupied.has(slot)); if (!laneFree) { setStatus(`No free ${lane} slot is available.`, true); return; } try { const value = await uploadFile(file, status); const sourceDuration = await probeDuration(value, type); if (sourceDuration !== null && sourceDuration < 2) { setStatus(`${file.name}: MiniMax references must be at least 2 seconds.`, true); return; } const duration = sourceDuration === null ? null : Math.min(sourceDuration, 15); let thumbnail = null; if (type === "video") { thumbnail = await captureFirstFrame(viewUrl(value)); } const item = { type, value, thumbnail, ...(duration !== null ? { duration, source_duration: sourceDuration } : {}), ...((type === "video" || type === "audio") ? { trim_start: 0, trim_end: duration } : {}) }; addItem(item); const added = state.items[state.items.length - 1]; if (type === "audio") void extractWaveform(value, added.id); setStatus(sourceDuration > 15 ? `${file.name} added; cropped to the first 15 seconds.` : `${file.name} added.`); } catch (error) { setStatus(error.message, true); } }
  const render = () => {
    timeline.replaceChildren();
    const selected = state.items.find(item => item.id === selectedId);
    const modeGroup = document.createElement("div"); modeGroup.className = "ds-h3-mode-group"; modeGroup.style.display = "flex"; modeGroup.style.flexDirection = "column"; modeGroup.style.alignItems = "flex-start"; modeGroup.style.gap = "4px"; modeGroup.style.padding = "6px"; modeGroup.style.background = "#0d1217"; modeGroup.style.border = "1px solid #344452"; modeGroup.style.borderRadius = "6px";
    const topRow = document.createElement("div"); topRow.className = "ds-h3-modebar"; topRow.style.flexWrap = "nowrap"; topRow.style.justifyContent = "space-between"; topRow.style.gap = "6px"; topRow.style.padding = "0"; topRow.style.border = "0"; topRow.style.background = "transparent";
    const modesSide = document.createElement("span"); modesSide.className = "ds-h3-actions"; modesSide.style.gap = "4px"; ["T2VA", "I2VA", "FL2VA", "L2VA", "REF2VA"].forEach(value => { const button = document.createElement("button"); button.textContent = value; button.classList.toggle("active", mode() === value); button.onclick = () => { if (modeWidget) { modeWidget.value = value; modeWidget.callback?.(value); } if (selectedLane === "audio" && value !== "REF2VA") selectedLane = "visual"; render(); }; modesSide.append(button); });
    const rightSide = document.createElement("span"); rightSide.className = "ds-h3-actions"; rightSide.style.gap = "4px"; const hasContent = state.items.length || state.prompt_blocks?.length || String(promptWidget?.value || "").trim(); if (hasContent) { const clearButton = document.createElement("button"); clearButton.className = "ds-h3-clear-btn"; clearButton.textContent = "Clear"; clearButton.title = "Remove all media and prompts"; clearButton.onclick = clearAll; rightSide.append(clearButton); } if (selected) { if (!isLockedSlot(selected)) { const removeButton = document.createElement("button"); removeButton.className = "ds-h3-remove-btn"; removeButton.textContent = "Remove"; removeButton.title = `Remove selected ${selected.type}`; removeButton.onclick = () => remove(selected.id); rightSide.append(removeButton); } else { setStatus(`${mediaReferenceName(selected.type)} ${selected.slot + 1} is locked in L2VA mode`, true); } } const docsButton = document.createElement("button"); docsButton.className = "ds-h3-docs"; docsButton.textContent = "?"; docsButton.title = "Open MiniMax H3 Director documentation on GitHub"; docsButton.onclick = () => window.open(REPOSITORY_URL, "_blank", "noopener,noreferrer"); rightSide.append(docsButton);
    topRow.append(modesSide, rightSide); modeGroup.append(topRow);
    const modeHint = { T2VA: "T2VA · no input frame", I2VA: "I2VA · one opening-frame slot", FL2VA: "FL2VA · opening and closing-frame slots", L2VA: "L2VA · one closing-frame slot" }; const hint = document.createElement("div"); hint.className = "ds-h3-mode-hint"; hint.style.fontSize = "11px"; hint.style.color = "#9fb3c2"; hint.style.margin = "0"; hint.textContent = modeHint[mode()] || `REF2VA · up to ${MAX.image} image, ${MAX.video} video, and ${MAX.audio} audio slots · ${MAX.total} combined files maximum`; modeGroup.append(hint);
    if (isFolderBatch) {
      const sourceRow = document.createElement("div");
      sourceRow.className = "ds-h3-modebar";
      sourceRow.style.flexWrap = "wrap";
      sourceRow.style.gap = "4px";
      sourceRow.style.padding = "0";
      sourceRow.style.border = "0";
      sourceRow.style.background = "transparent";
      const sourceLabel = document.createElement("span");
      sourceLabel.className = "ds-h3-small";
      sourceLabel.textContent = "Image source:";
      sourceLabel.style.alignSelf = "center";
      sourceRow.append(sourceLabel);
      [["auto", "Auto"], ["source_image", "Socket"], ["node_upload_or_folder", "Upload/Folder"]].forEach(([value, label]) => {
        const button = document.createElement("button");
        button.textContent = label;
        button.classList.toggle("active", sourceMode() === value);
        button.title = value === "auto" ? "Use source_image socket first, then uploaded images, then folder" : value === "source_image" ? "Use only the source_image socket" : "Use node-uploaded images first, then folder";
        button.onclick = () => {
          state.image_source_mode = value;
          emit();
          setStatus(`Image source: ${label}`);
          render();
        };
        sourceRow.append(button);
      });
      const endButton = document.createElement("button");
      endButton.textContent = useEndFrame() ? "End On" : "End Off";
      endButton.classList.toggle("active", useEndFrame());
      endButton.title = "Use or ignore the connected/uploaded/folder end-frame image";
      endButton.onclick = () => {
        state.use_end_frame = !useEndFrame();
        emit();
        setStatus(`End image: ${state.use_end_frame ? "On" : "Off"}`);
        render();
      };
      sourceRow.append(endButton);
      modeGroup.append(sourceRow);
    }
    timeline.append(modeGroup);

    const lengthWidget = node.widgets?.find(w => w.name === "duration"); const timelineSeconds = Math.max(1, Number(lengthWidget?.value) || 5); lastTimelineLength = timelineSeconds;

    ensureLayout();
    const track = document.createElement("div"); track.className = "ds-h3-track"; track.addEventListener("pointerdown", () => timeline.focus());
    const trackInner = document.createElement("div"); trackInner.className = "ds-h3-track-inner";
    trackInner.onclick = event => { if (event.target !== trackInner) return; const rect = trackInner.getBoundingClientRect(); insertAt = Math.max(0, Math.round(((event.clientX - rect.left) / scale) * 4) / 4); status.textContent = `Insert cursor: ${insertAt.toFixed(2)}s · choose + image, + video, + audio, or + text.`; trackInner.style.setProperty("--insert-x", `${insertAt * scale}px`); };
    const laneTypes = ["Image/Video", "audio"]; const laneHeight = 120; const trackEntries = displayedItems(); const maxEnd = timelineSeconds; const scale = 48; const audioSlotWidth = sourceDuration => Math.round(Math.max(180, Math.min(420, 96 * Math.log2(Math.max(2, sourceDuration) + 1)))); const slotWidthFor = item => item && (item.type === "audio" || item.type === "video") ? audioSlotWidth(Number(item.source_duration) || item.duration) : 112; const laneNameFor = item => laneForItem(item) === "audio" ? "audio" : "Image/Video"; const slotItem = (lane, slot) => trackEntries.find(item => laneNameFor(item) === lane && item.slot === slot); const slotLeft = (lane, slot) => { let left = 6; for (let index = 0; index < slot; index += 1) left += slotWidthFor(slotItem(lane, index)) + 8; return left; }; const acceptLaneDrop = async (event, targetLane) => { event.preventDefault(); event.stopPropagation(); trackInner.classList.remove("over"); const rect = trackInner.getBoundingClientRect(); insertAt = Math.max(0, Math.round(((event.clientX - rect.left) / scale) * 4) / 4); trackInner.style.setProperty("--insert-x", `${insertAt * scale}px`); for (const file of event.dataTransfer.files || []) await acceptFile(file, targetLane); }; const visualSlotCount = () => mode() === "T2VA" ? 0 : mode() === "I2VA" ? 1 : mode() === "L2VA" ? 2 : mode() === "FL2VA" ? 2 : MAX.image + MAX.video; const slotExtent = lane => Array.from({ length: lane === "audio" ? MAX.audio : visualSlotCount() }, (_, index) => slotWidthFor(slotItem(lane === "audio" ? "audio" : "Image/Video", index)) + 8).reduce((sum, width) => sum + width, 6); trackInner.style.width = `${Math.max(240, slotExtent("Image/Video"), slotExtent("audio"))}px`; trackInner.style.height = `${laneTypes.length * laneHeight}px`; trackInner.style.background = `repeating-linear-gradient(0deg, transparent 0, transparent ${laneHeight - 1}px, #344452 ${laneHeight - 1}px, #344452 ${laneHeight}px), repeating-linear-gradient(90deg,#111a21 0,#111a21 49px,#1b2933 50px)`; const ruler = document.createElement("div"); ruler.className = "ds-h3-ruler"; for (let second = 0; second <= timelineSeconds; second++) { if (second % 2 !== 0) continue; const mark = document.createElement("div"); mark.style.position = "absolute"; mark.style.left = `${second * scale}px`; mark.style.bottom = "0"; mark.style.fontSize = "9px"; mark.style.color = "#8fa3b2"; mark.textContent = `${second}s`; ruler.appendChild(mark); } track.append(ruler);
    const lanes = new Map(); laneTypes.forEach((type, index) => { const lane = document.createElement("div"); const targetLane = type === "audio" ? "audio" : "visual"; const m = mode(); const audioDisabledByMode = m === "T2VA" || m === "I2VA" || m === "FL2VA" || m === "L2VA"; const supported = !(targetLane === "audio" && audioDisabledByMode); const slotCount = targetLane === "audio" ? MAX.audio : visualSlotCount(); lane.className = `ds-h3-timeline-lane ${targetLane}${selectedLane === targetLane ? " selected" : ""}${supported ? "" : " disabled"}`; lane.style.top = `${index * laneHeight}px`; lane.onclick = () => { if (!supported) { setStatus(m === "T2VA" ? "T2VA has no input lanes." : audioDisabledByMode ? "This mode does not support audio references." : "", true); return; } selectedLane = targetLane; setStatus(`${type === "audio" ? "Audio" : "Image/Video"} lane selected. Paste files here with Ctrl+V.`); render(); }; lane.ondragover = event => { if ([...event.dataTransfer.items].some(item => item.kind === "file")) { event.preventDefault(); if (supported) trackInner.classList.add("over"); } }; lane.ondragleave = () => trackInner.classList.remove("over"); lane.ondrop = event => { if (!supported) { event.preventDefault(); event.stopPropagation(); setStatus(audioDisabledByMode ? "This mode does not support audio references." : "", true); return; } selectedLane = targetLane; acceptLaneDrop(event, targetLane); }; const label = document.createElement("span"); label.className = "ds-h3-lane-label"; label.textContent = `${type}${selectedLane === targetLane ? " · selected" : ""}`; label.style.display = hiddenLanes.has(type) ? "none" : "block"; lane.append(label); for (let slotIndex = 0; slotIndex < slotCount; slotIndex += 1) { if (slotItem(type, slotIndex)) continue; const slot = document.createElement("span"); slot.className = "ds-h3-empty-slot"; slot.textContent = "+"; slot.style.left = `${slotLeft(type, slotIndex)}px`; slot.style.width = `${slotWidthFor(null)}px`; if (m === "L2VA" && targetLane === "visual" && slotIndex === 0) { const lockIcon = document.createElement("span"); lockIcon.className = "ds-h3-lock-icon"; lockIcon.textContent = "🔒"; lockIcon.style.position = "absolute"; lockIcon.style.right = "4px"; lockIcon.style.top = "4px"; lockIcon.style.fontSize = "12px"; slot.style.position = "relative"; slot.appendChild(lockIcon); } if (!m.includes("T2VA") && supported) { slot.onclick = event => { event.stopPropagation(); selectedLane = targetLane; const acceptTypes = targetLane === "audio" ? ["audio"] : ["image","video"]; const accepts = acceptTypes.map(t => t === "image" ? "image/*" : t === "video" ? "video/*" : "audio/*").join(","); fileInput.accept = accepts; fileInput.click(); }; } lane.append(slot); } lanes.set(type, lane); trackInner.append(lane); });
    trackEntries.forEach(item => { const clip = document.createElement("div"); clip.className = `ds-h3-clip ${item.type} ${selectedId === item.id ? "selected" : ""}${isLockedSlot(item) ? " locked" : ""}`; clip.textContent = mediaLabel(item); clip.title = item.type === "text" ? String(item.value || "") : String(item.value || ""); clip.style.display = "block"; const bgSrc = item.type === "image" ? viewUrl(item.value) : item.thumbnail || null; if (bgSrc) { clip.style.backgroundImage = `linear-gradient(90deg, rgba(20,35,45,.78), rgba(20,35,45,.5)), url("${bgSrc}")`; clip.style.backgroundSize = "cover"; clip.style.backgroundPosition = "center"; } item.slot = Number.isInteger(item.slot) ? item.slot : trackEntries.filter(x => laneNameFor(x) === laneNameFor(item)).indexOf(item); item.start = item.slot; item.duration = Number.isFinite(item.duration) ? item.duration : 1; const visualStart = item.start; const sourceDuration = Number(item.source_duration) || item.duration; const clipWidth = slotWidthFor(item); clip.style.left = `${slotLeft(laneNameFor(item), item.slot)}px`; clip.style.top = "7px"; clip.style.width = `${clipWidth}px`; clip.style.setProperty("--clip-width", `${clipWidth}px`); clip.dataset.slot = String(item.slot); const identity = document.createElement("span"); identity.className = "ds-h3-clip-identity"; const typePosition = trackEntries.filter(entry => entry.type === item.type).sort((a, b) => a.slot - b.slot).indexOf(item) + 1; identity.textContent = `${mediaReferenceName(item.type)} ${typePosition}`; clip.append(identity); if (isLockedSlot(item)) { const lockIcon = document.createElement("span"); lockIcon.className = "ds-h3-lock-icon"; lockIcon.textContent = "🔒"; clip.append(lockIcon); } if (item.type === "video") { const streamControls = document.createElement("span"); streamControls.className = "ds-h3-video-stream-controls"; const currentMediaMode = ["video", "audio", "video_audio"].includes(item.media_mode) ? item.media_mode : "video"; [["video", "V", "Video only"], ["audio", "A", "Audio only"], ["video_audio", "V+A", "Video + embedded audio"]].forEach(([value, label, title]) => { const button = document.createElement("button"); button.textContent = label; button.title = title; button.classList.toggle("active", value === currentMediaMode); button.onpointerdown = event => event.stopPropagation(); button.onclick = event => { event.stopPropagation(); mutate(s => { const target = s.items.find(x => x.id === item.id); if (target) target.media_mode = value; }); }; streamControls.append(button); }); clip.append(streamControls); const videoScale = document.createElement("span"); videoScale.className = "ds-h3-video-scale"; videoScale.title = "Full source-duration scale"; clip.append(videoScale); } if (selectedId === item.id) { const close = document.createElement("button"); close.className = "ds-h3-clip-close"; close.textContent = "×"; close.title = `Remove selected ${item.type}`; close.onclick = event => { event.stopPropagation(); remove(item.id); }; clip.append(close); }
      const cropReadout = document.createElement("span"); cropReadout.className = "ds-h3-crop-readout"; if (item.type === "video" || item.type === "audio") { cropReadout.textContent = `crop ${Number(item.trim_start || 0).toFixed(2)}s–${item.trim_end == null ? "end" : Number(item.trim_end).toFixed(2) + "s"}`; clip.append(cropReadout); } if (item.type === "video") { for (const edge of ["start", "end"]) { const marker = document.createElement("span"); marker.className = `ds-h3-crop-marker ${edge}`; marker.style.left = `${(Number(edge === "start" ? item.trim_start || 0 : item.trim_end ?? sourceDuration) / sourceDuration) * 100}%`; clip.append(marker); } } if (item.type === "audio") { const peaks = Array.isArray(item.waveform_peaks) ? item.waveform_peaks : []; const waveform = document.createElement("canvas"); waveform.className = "ds-h3-waveform"; waveform.width = 720; waveform.height = 160; waveform.title = peaks.length ? "Full audio waveform; crop markers show the selected reference window" : "Decoding audio waveform…"; const context = waveform.getContext("2d"); if (context && peaks.length) { const center = waveform.height / 2; context.fillStyle = "rgba(126, 225, 157, .8)"; for (let x = 0; x < waveform.width; x += 1) { const peakIndex = Math.min(peaks.length - 1, Math.floor((x / waveform.width) * peaks.length)); const amplitude = (Math.log1p(9 * peaks[peakIndex]) / Math.log(10)) * (waveform.height - 16) * .45; context.fillRect(x, center - amplitude, 1, amplitude * 2); } } const cropStartMarker = document.createElement("span"); cropStartMarker.className = "ds-h3-audio-crop-marker start"; const cropEndMarker = document.createElement("span"); cropEndMarker.className = "ds-h3-audio-crop-marker end"; const updateAudioCropMarkers = () => { const startPercent = Math.max(0, Math.min(100, (Number(item.trim_start || 0) / sourceDuration) * 100)); const endPercent = Math.max(startPercent, Math.min(100, (Number(item.trim_end ?? sourceDuration) / sourceDuration) * 100)); cropStartMarker.style.left = `${startPercent}%`; cropEndMarker.style.left = `${endPercent}%`; }; updateAudioCropMarkers(); clip.append(waveform, cropStartMarker, cropEndMarker); }
      const resize = (edge, event) => { event.stopPropagation(); clip.setPointerCapture?.(event.pointerId); const origin = event.clientX; const start = item.start; const duration = item.duration; const sourceDuration = Number(item.source_duration) || duration; const minimumReferenceDuration = Math.min(2, sourceDuration); const cropStartAtDrag = Number(item.trim_start) || 0; const cropEndAtDrag = Number(item.trim_end) || sourceDuration; const onMove = moveEvent => { const delta = (item.type === "audio" || item.type === "video") ? ((moveEvent.clientX - origin) / clipWidth) * sourceDuration : (moveEvent.clientX - origin) / scale; if (edge === "left") { if (item.type === "video" || item.type === "audio") { item.trim_start = Math.min(cropEndAtDrag - minimumReferenceDuration, Math.max(0, Math.round((cropStartAtDrag + delta) * 4) / 4)); item.duration = Math.min(15, Math.max(minimumReferenceDuration, Math.round((cropEndAtDrag - item.trim_start) * 4) / 4)); item.trim_end = cropEndAtDrag; } else { const nextStart = Math.max(0, Math.round((start + delta) * 4) / 4); const end = start + duration; item.start = Math.min(nextStart, end - 0.25); item.duration = Math.max(0.25, Math.round((end - item.start) * 4) / 4); item.trim_start = item.start; } } else if (item.type === "video" || item.type === "audio") { item.trim_end = Math.min(sourceDuration, Math.max(cropStartAtDrag + minimumReferenceDuration, Math.round((cropEndAtDrag + delta) * 4) / 4)); item.duration = Math.min(15, Math.max(minimumReferenceDuration, Math.round((item.trim_end - cropStartAtDrag) * 4) / 4)); item.trim_end = cropStartAtDrag + item.duration; } else { item.duration = Math.max(0.25, Math.round((duration + delta) * 4) / 4); item.trim_end = item.start + item.duration; } if (item.type === "video" || item.type === "audio") { cropReadout.textContent = `crop ${Number(item.trim_start || 0).toFixed(2)}s–${Number(item.trim_end).toFixed(2)}s / ${sourceDuration.toFixed(2)}s`; setStatus(`${edge === "left" ? "Crop start" : "Crop end"}: ${cropReadout.textContent}`); } if (item.type === "video" || item.type === "audio") { const startPercent = Math.max(0, Math.min(100, (Number(item.trim_start || 0) / sourceDuration) * 100)); const endPercent = Math.max(startPercent, Math.min(100, (Number(item.trim_end ?? sourceDuration) / sourceDuration) * 100)); const [cropStartMarker, cropEndMarker] = clip.querySelectorAll(".ds-h3-crop-marker, .ds-h3-audio-crop-marker"); if (cropStartMarker) cropStartMarker.style.left = `${startPercent}%`; if (cropEndMarker) cropEndMarker.style.left = `${endPercent}%`; } clip.style.left = `${slotLeft(laneNameFor(item), item.slot)}px`; clip.style.width = `${clipWidth}px`; }; const onUp = () => { clip.removeEventListener("pointermove", onMove); clip.removeEventListener("pointerup", onUp); if (item._block) { item._block.start = item.start; item._block.duration = item.duration; } mutate(() => {}); }; clip.addEventListener("pointermove", onMove); clip.addEventListener("pointerup", onUp); };
      const leftGrip = document.createElement("span"); leftGrip.className = "ds-h3-grip left"; leftGrip.onpointerdown = event => resize("left", event); const rightGrip = document.createElement("span"); rightGrip.className = "ds-h3-grip right"; rightGrip.onpointerdown = event => resize("right", event); clip.append(leftGrip, rightGrip); if (item.type === "video" || item.type === "audio") { leftGrip.style.display = "none"; rightGrip.style.display = "none"; clip.querySelectorAll(".ds-h3-crop-marker, .ds-h3-audio-crop-marker").forEach(marker => { marker.onpointerdown = event => resize(marker.classList.contains("start") ? "left" : "right", event); }); }
      const editBtn = document.createElement("button"); editBtn.textContent = "☰"; editBtn.className = "ds-h3-edit-btn"; editBtn.title = "Open preview and details"; editBtn.onclick = event => { event.stopPropagation(); openPreview(item); }; clip.append(editBtn);
      clip.onclick = event => { if (event.target !== clip) return; selectedId = item.id; render(); }; clip.onpointerdown = event => { selectedId = item.id; if (event.target !== clip) return; event.stopPropagation(); clip.setPointerCapture?.(event.pointerId); const origin = event.clientX; const originalLeft = slotLeft(laneNameFor(item), item.slot); const lane = laneNameFor(item); const slotCount = lane === "audio" ? MAX.audio : visualSlotCount(); let dragged = false; const onMove = moveEvent => { dragged ||= Math.abs(moveEvent.clientX - origin) >= 4; if (dragged) clip.style.left = `${originalLeft + moveEvent.clientX - origin}px`; }; const onUp = moveEvent => { clip.removeEventListener("pointermove", onMove); clip.removeEventListener("pointerup", onUp); if (!dragged) return; const rect = trackInner.getBoundingClientRect(); const x = moveEvent.clientX - rect.left; const targetSlot = Array.from({ length: slotCount }, (_, slot) => slot).reduce((nearest, slot) => Math.abs((slotLeft(lane, slot) + slotWidthFor(slotItem(lane, slot)) / 2) - x) < Math.abs((slotLeft(lane, nearest) + slotWidthFor(slotItem(lane, nearest)) / 2) - x) ? slot : nearest, 0); mutate(s => { const moved = s.items.find(x => x.id === item.id); if (!moved) return; const occupant = s.items.find(x => x.id !== moved.id && laneForItem(x) === laneForItem(moved) && x.slot === targetSlot); const previousSlot = moved.slot; moved.slot = targetSlot; moved.start = targetSlot; if (occupant) { occupant.slot = previousSlot; occupant.start = previousSlot; } }); }; clip.addEventListener("pointermove", onMove); clip.addEventListener("pointerup", onUp); }; lanes.get(item.type === "audio" ? "audio" : "Image/Video").append(clip); }); track.append(trackInner); timeline.append(track);
    // Unified prompt-builder form replacing legacy per-item/global prompts
    const promptPanel = document.createElement("div"); promptPanel.className = "ds-h3-prompt-panel";
    if (mode() === "REF2VA") {
      buildRefForm(promptPanel);
    } else {
      buildBaseForm(promptPanel);
    }
    timeline.append(promptPanel);
    const list = document.createElement("div"); list.className = "ds-h3-list"; list.style.display = "none";
    activeItems().forEach((item, index) => { const row = document.createElement("div"); row.className = "ds-h3-item"; row.draggable = true; row.dataset.id = item.id; row.ondragstart = e => e.dataTransfer.setData("text/plain", item.id); row.ondragover = e => e.preventDefault(); row.ondrop = e => { const from = state.items.findIndex(x => x.id === e.dataTransfer.getData("text/plain")); const to = state.items.findIndex(x => x.id === item.id); if (from >= 0 && to >= 0) mutate(s => { const [x] = s.items.splice(from, 1); s.items.splice(to, 0, x); }); };
      let preview = document.createElement("img"); if (item.type === "image") { preview.src = viewUrl(item.value); } else if (item.type === "video") { const src = viewUrl(item.value); const vid = document.createElement("video"); vid.preload = "auto"; vid.muted = true; vid.crossOrigin = ""; vid.onloadeddata = () => { vid.currentTime = 0; }; vid.onseeked = () => { try { const c = document.createElement("canvas"); c.width = vid.videoWidth || 160; c.height = vid.videoHeight || 96; const ctx = c.getContext("2d"); ctx.drawImage(vid, 0, 0, c.width, c.height); preview.src = c.toDataURL("image/jpeg", 0.7); preview.alt = "video thumbnail"; } catch(e) { preview.src = src; preview.alt = "video"; } }; vid.onerror = () => { preview.src = src; preview.alt = "video"; }; vid.src = src; } else if (item.type === "audio") { preview = document.createElement("audio"); preview.src = viewUrl(item.value); preview.controls = true; }
      const middle = document.createElement("div"); const name = document.createElement("div"); name.className = "ds-h3-name"; name.textContent = `${item.type} ${index + 1}: ${item.value}`; middle.append(name); const promptArea = document.createElement("textarea"); promptArea.className = "ds-h3-prompt ds-h3-media-prompt"; promptArea.placeholder = `Prompt for this ${item.type}`; promptArea.value = item.prompt || ""; promptArea.onchange = () => mutate(s => { const x = s.items.find(i => i.id === item.id); if (x) x.prompt = promptArea.value; }); middle.append(promptArea); if (item.type === "video") { const trim = document.createElement("input"); trim.className = "ds-h3-prompt"; trim.placeholder = "trim start,end seconds"; trim.value = `${item.trim_start ?? 0},${item.trim_end ?? ""}`; trim.onchange = () => { const [a,b] = trim.value.split(",").map(x => x.trim()); mutate(s => { const x = s.items.find(i => i.id === item.id); if (x && Number.isFinite(Number(a)) && (!b || Number(b) > Number(a))) { x.trim_start = Number(a); x.trim_end = b ? Number(b) : null; } }); }; middle.append(trim); } if (item.type === "video" && item.audio) { const paired = document.createElement("div"); paired.className = "ds-h3-small"; paired.textContent = `soundtrack: ${item.audio}`; middle.append(paired); }
      const actions = document.createElement("div"); actions.className = "ds-h3-actions"; [["↑", () => move(item.id,-1)], ["↓", () => move(item.id,1)], ["replace", () => { const v = window.prompt("Replacement input path:", item.value); if (v?.trim()) replace(item.id, v.trim()); }], ["clear", () => remove(item.id)]].forEach(([label, fn]) => { const b = document.createElement("button"); b.textContent = label; b.onclick = fn; actions.append(b); }); if (mode() === "REF2VA" && item.type === "video") { const b = document.createElement("button"); b.textContent = item.audio ? "remove soundtrack" : "attach soundtrack"; b.onclick = () => { if (item.audio) mutate(s => { const x=s.items.find(i=>i.id===item.id); if(x){ x.audio=null; delete x.audio_duration; } }); else { const v=window.prompt("Soundtrack path relative to ComfyUI input:", ""); if(v?.trim()) mutate(s => { const x=s.items.find(i=>i.id===item.id); if(x) x.audio=v.trim(); }); } }; actions.append(b); } row.append(preview, middle, actions); list.append(row); }); timeline.append(list);
    // Prompt text is edited on the corresponding media row and synchronized to prompt_blocks.
    timeline.append(status); if (domWidget) domWidget.computeSize = () => [Math.max(420, node.size?.[0] || 520), uiHeight()];
  };
  const appendPromptField = (panel, editor, stateKey, getHeight, setHeight) => {
    const field = document.createElement("div");
    field.className = "ds-h3-prompt-field";
    field.style.height = `${getHeight()}px`;
    const resizer = document.createElement("div");
    resizer.className = "ds-h3-prompt-field-resizer";
    resizer.title = "Drag to resize this prompt field";
    resizer.setAttribute("role", "separator");
    resizer.setAttribute("aria-label", "Resize prompt field");
    resizer.addEventListener("mousedown", event => {
      event.preventDefault();
      event.stopPropagation();
      const startY = event.clientY;
      const startHeight = getHeight();
      resizer.classList.add("active");
      const drag = moveEvent => {
        if (moveEvent.buttons === 0) return finish();
        const height = Math.max(90, Math.min(640, startHeight + moveEvent.clientY - startY));
        setHeight(height);
        field.style.height = `${height}px`;
        syncNodeBounds();
      };
      const finish = () => {
        window.removeEventListener("mousemove", drag, true);
        window.removeEventListener("mouseup", finish, true);
        document.body.style.cursor = "default";
        resizer.classList.remove("active");
        state[stateKey] = getHeight();
        emit();
        syncNodeBounds();
      };
      document.body.style.cursor = "ns-resize";
      window.addEventListener("mousemove", drag, true);
      window.addEventListener("mouseup", finish, true);
    });
    field.append(editor, resizer);
    panel.append(field);
  };
  let domWidget;
  const uiHeight = () => Math.max(850, 500 + mediaPromptHeight + globalPromptHeight);
  const minimumNodeSize = [440, 880];
  let syncingNodeBounds = false;
  const syncNodeBounds = () => {
    if (syncingNodeBounds) return;
    const [currentWidth = minimumNodeSize[0], currentHeight = minimumNodeSize[1]] = node.size || [];
    const [contentWidth = minimumNodeSize[0], contentHeight = minimumNodeSize[1]] = node.computeSize?.() || [];
    const width = Math.max(minimumNodeSize[0], contentWidth, currentWidth);
    const height = Math.max(minimumNodeSize[1], uiHeight(), contentHeight, currentHeight);
    if (width !== currentWidth || height !== currentHeight) {
      syncingNodeBounds = true;
      node.setSize?.([width, height]);
      syncingNodeBounds = false;
    }
    timeline.style.width = `${Math.max(1, (node.size?.[0] || width) - 20)}px`;
    timeline.style.height = `${uiHeight()}px`;
  };
  if (node.addDOMWidget) {
    domWidget = node.addDOMWidget("minimax_h3_director_ui", "custom", timeline, { serialize: false, hideOnZoom: false, getHeight: () => uiHeight() });
    domWidget.computeSize = () => [Math.max(420, node.size?.[0] || 520), uiHeight()];
  }
  const oldResize = node.onResize;
  node.onResize = function (...args) { oldResize?.apply(this, args); syncNodeBounds(); };
  const restorePersistedState = () => {
    state = parseState(dataWidget.value);
    mediaPromptHeight = Math.max(90, Number(state.media_prompt_height) || 120);
    globalPromptHeight = Math.max(90, Number(state.global_prompt_height) || 120);
    selectedId = null;
    const m = mode();
    const baseDefaults = DEFAULT_BUILDER_STATE(m);
    const rawBuilder = builderWidget?.value || state.builder_state;
    if (rawBuilder) {
      try {
        const parsed = typeof rawBuilder === "string" ? JSON.parse(rawBuilder) : rawBuilder;
        if (parsed && typeof parsed === "object") {
          builderState = { ...baseDefaults, ...parsed, ref: { ...baseDefaults.ref, ...(parsed.ref || {}) } };
          builderState.mode = m;
        }
      } catch { /* fall back to defaults */ }
    } else {
      builderState = baseDefaults;
      builderState.mode = m;
    }
    syncNodeBounds();
    render();
    void Promise.all(state.items.filter(item => item.type === "video" && !item.thumbnail).map(async item => {
      const thumb = await captureFirstFrame(viewUrl(item.value));
      if (thumb) mutate(s => { const x = s.items.find(i => i.id === item.id); if (x) x.thumbnail = thumb; });
    })).then(render);
  };
  const oldConfigure = node.onConfigure;
  node.onConfigure = function (...args) {
    oldConfigure?.apply(this, args);
    requestAnimationFrame(restorePersistedState);
  };
  node.__dasiwaH3RestorePersistedState = () => requestAnimationFrame(restorePersistedState);
  node.__dasiwaH3State = () => state; node.__dasiwaH3Render = render;
  if (modeWidget) { const old = modeWidget.callback; modeWidget.callback = value => { old?.(value); render(); }; }
  const lengthWidget = node.widgets?.find(w => w.name === "duration");
  if (lengthWidget) { const old = lengthWidget.callback; lengthWidget.callback = value => { old?.(value); render(); }; }
  const oldDrawForeground = node.onDrawForeground;
  node.onDrawForeground = function (...args) { oldDrawForeground?.apply(this, args); const seconds = Math.max(1, Number(lengthWidget?.value) || 5); if (seconds !== lastTimelineLength) render(); };
  node.__dasiwaH3LengthPoll = window.setInterval(() => { const seconds = Math.max(1, Number(lengthWidget?.value) || 5); if (seconds !== lastTimelineLength) render(); }, 200);
  syncNodeBounds();
  requestAnimationFrame(syncNodeBounds);
  render();
}

const DIRECTOR_CLASSES = new Set([
  "MiniMaxH3Director",
  "MiniMaxH3DirectorFolderBatch",
  "WildcardMiniMaxH3Director",
  "WildcardMiniMaxH3DirectorFolderBatch",
]);

app.registerExtension({
  name: "WildcardImageIterator.MiniMaxH3Director",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (!DIRECTOR_CLASSES.has(nodeData.name) || !String(nodeData.name || "").includes("FolderBatch")) return;
    const onConnectionsChange = nodeType.prototype.onConnectionsChange;
    nodeType.prototype.onConnectionsChange = function (...args) {
      onConnectionsChange?.apply(this, args);
      try {
        updateDynamicRefImageInputs(this);
      } catch (error) {
        console.error("[MiniMax H3 Director] dynamic ref image inputs:", error);
      }
    };
    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function (...args) {
      onNodeCreated?.apply(this, args);
      requestAnimationFrame(() => updateDynamicRefImageInputs(this));
    };
    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function (...args) {
      onConfigure?.apply(this, args);
      requestAnimationFrame(() => updateDynamicRefImageInputs(this));
    };
  },
  nodeCreated(node) {
    if (DIRECTOR_CLASSES.has(node.comfyClass)) install(node);
  },
  loadedGraphNode(node) {
    if (DIRECTOR_CLASSES.has(node.comfyClass)) {
      install(node);
      node.__dasiwaH3RestorePersistedState?.();
    }
  },
});
