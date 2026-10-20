import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

let stylesInstalled = false;
let legacyStorageCleared = false;
const STATE_PROPERTY = "prompt_preset_library_state";
const LEGACY_STORAGE_PREFIX = "WildcardImageIterator.PromptPresetLibrary.";

function clearLegacyStoredStates() {
    if (legacyStorageCleared) return;
    legacyStorageCleared = true;
    try {
        for (let index = localStorage.length - 1; index >= 0; index -= 1) {
            const key = localStorage.key(index);
            if (key?.startsWith(LEGACY_STORAGE_PREFIX)) localStorage.removeItem(key);
        }
    } catch {
        // Workflow serialization remains authoritative when storage is unavailable.
    }
}

function uid() {
    return `preset-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function defaultState() {
    return {
        version: 2,
        presets: [{ id: "preset-1", name: "Preset 1", prompt: "", pair_enabled: false, prompt_2: "" }],
        selected_id: "preset-1",
        updated_at: 0,
    };
}

function parseState(value) {
    let state;
    try {
        state = JSON.parse(value || "{}");
    } catch {
        return defaultState();
    }

    // Migrate the first version by flattening each profile/variant pair.
    if ((!Array.isArray(state.presets) || !state.presets.length) && Array.isArray(state.groups)) {
        state.presets = state.groups.flatMap(group => {
            const variants = Array.isArray(group?.variants) ? group.variants : [];
            return variants.map(variant => ({
                id: uid(),
                name: variants.length > 1
                    ? `${String(group?.name || "Preset")} - ${String(variant?.name || "Variant")}`
                    : String(group?.name || "Preset"),
                prompt: String(variant?.prompt || ""),
                pair_enabled: false,
                prompt_2: "",
            }));
        });
    }
    if (!Array.isArray(state.presets) || !state.presets.length) return defaultState();

    state.presets = state.presets.filter(item => item && typeof item === "object").map((item, index) => ({
        id: String(item.id || uid()),
        name: String(item.name || `Preset ${index + 1}`),
        prompt: String(item.prompt || ""),
        pair_enabled: item.pair_enabled === true,
        prompt_2: String(item.prompt_2 || ""),
        ...(Array.isArray(item.loras) ? { loras: item.loras.filter(lora => lora && typeof lora === "object").map(lora => ({ ...lora })) } : {}),
        ...(Object.hasOwn(item, "lora_enabled") || Object.hasOwn(item, "lora_name") ? {
            lora_enabled: item.lora_enabled === true,
            lora_name: String(item.lora_name || ""),
            lora_strength: Number.isFinite(Number(item.lora_strength)) ? Number(item.lora_strength) : 1,
            ...(Object.hasOwn(item, "lora_video") ? { lora_video: Number.isFinite(Number(item.lora_video)) ? Number(item.lora_video) : 1 } : {}),
            ...(Object.hasOwn(item, "lora_audio") ? { lora_audio: Number.isFinite(Number(item.lora_audio)) ? Number(item.lora_audio) : 1 } : {}),
        } : {}),
    }));
    if (!state.presets.length) return defaultState();
    if (!state.presets.some(item => item.id === state.selected_id)) {
        state.selected_id = state.presets[0].id;
    }
    state.version = 2;
    state.updated_at = Number.isFinite(Number(state.updated_at)) ? Number(state.updated_at) : 0;
    delete state.groups;
    delete state.output_a;
    delete state.output_b;
    delete state.editor;
    return state;
}

function workflowWidgetValue(node, index = 0) {
    if (Array.isArray(node?.widgets_values) && node.widgets_values[index] != null) {
        return node.widgets_values[index];
    }
    return undefined;
}

function workflowWidgetValues(source) {
    return Array.isArray(source?.widgets_values) ? source.widgets_values : [];
}

function stateScore(state) {
    if (!state || !Array.isArray(state.presets)) return -1;
    let score = state.presets.length;
    for (const preset of state.presets) {
        if (String(preset?.name || "").trim()) score += 1;
        if (String(preset?.prompt || "").trim()) score += 20;
        if (preset?.pair_enabled === true) score += 2;
        if (String(preset?.prompt_2 || "").trim()) score += 20;
    }
    return score;
}

function bestState(...values) {
    let best = null;
    let bestScore = -1;
    let bestUpdatedAt = -1;
    for (const value of values) {
        if (value == null || String(value).trim() === "") continue;
        const state = parseState(value);
        const updatedAt = Number(state.updated_at || 0);
        const score = stateScore(state);
        if (updatedAt > bestUpdatedAt || (updatedAt === bestUpdatedAt && score > bestScore)) {
            best = state;
            bestScore = score;
            bestUpdatedAt = updatedAt;
        }
    }
    return best || defaultState();
}

function hasSavedPresetState(value) {
    if (value == null || String(value).trim() === "") return false;
    try {
        const state = parseState(value);
        if (Number(state.updated_at || 0) > 0) return true;
        if (!Array.isArray(state.presets) || state.presets.length !== 1) return state.presets.length > 1;
        const only = state.presets[0] || {};
        return String(only.name || "") !== "Preset 1"
            || String(only.prompt || "").trim() !== ""
            || String(only.prompt_2 || "").trim() !== ""
            || only.pair_enabled === true
            || only.lora_enabled === true
            || Boolean(only.lora_name);
    } catch {
        return false;
    }
}

function installStyles() {
    if (stylesInstalled) return;
    stylesInstalled = true;
    const style = document.createElement("style");
    style.textContent = `
        .ppl-root{box-sizing:border-box;width:100%;height:100%;padding:8px;display:flex;flex-direction:column;gap:7px;color:#ddd;font:12px system-ui,sans-serif;overflow:hidden}
        .ppl-toolbar{display:grid;grid-template-columns:auto auto auto;gap:5px}
        .ppl-root input,.ppl-root select,.ppl-root textarea,.ppl-root button{box-sizing:border-box;background:#202020;color:#ddd;border:1px solid #555;border-radius:4px;font:12px system-ui,sans-serif}
        .ppl-root input{width:100%;height:28px;padding:4px 7px}
        .ppl-root input[type=checkbox]{width:16px;height:16px;margin:0}
        .ppl-root button{height:28px;padding:3px 9px;cursor:pointer}
        .ppl-root button:hover{background:#303030;border-color:#777}
        .ppl-list{width:100%;padding:3px;flex:none;display:flex;flex-direction:column;gap:2px;overflow:hidden;border:1px solid #555;border-radius:4px;background:#202020}
        .ppl-profile-row{box-sizing:border-box;width:100%;height:23px;display:grid;grid-template-columns:24px minmax(0,1fr);align-items:center;padding:0 6px;border:1px solid transparent;border-radius:3px;cursor:grab;user-select:none}
        .ppl-profile-row:hover{background:#303030}
        .ppl-profile-row.selected{background:#31577a;border-color:#5f8fb7;color:#fff}
        .ppl-profile-row.drag-over{border-color:#d0b46a}
        .ppl-drag-handle{color:#999;font-family:monospace}
        .ppl-prompt{width:100%;min-height:220px;flex:1;padding:8px;resize:none;line-height:1.4}
        .ppl-pair-row{display:flex;align-items:center;gap:7px;height:24px}
        .ppl-lora-controls{display:flex;flex-direction:column;gap:5px;flex:none;min-width:0}
        .ppl-lora-controls select{width:100%;min-width:0;height:80px}
        .ppl-lora-weights{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}
        .ppl-lora-stepper{display:grid;grid-template-columns:25px minmax(0,1fr) 25px;align-items:center}
        .ppl-lora-stepper input{text-align:center;padding:2px;appearance:textfield}
        .ppl-lora-stepper input::-webkit-inner-spin-button{appearance:none}
        .ppl-lora-stepper button{padding:0;height:28px}
        .ppl-label{color:#aaa;font-weight:600}
        .ppl-status{height:16px;color:#9bbf9b;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
        .ppl-status.error{color:#e6a0a0}
    `;
    document.head.appendChild(style);
}

function install(node) {
    if (node.__promptPresetLibraryInstalled) return;
    node.__promptPresetLibraryInstalled = true;
    clearLegacyStoredStates();
    installStyles();

    const stateWidget = node.widgets?.find(widget => widget.name === "library_json");
    if (!stateWidget) return;
    node.serialize_widgets = true;
    stateWidget.hidden = true;
    stateWidget.serialize = true;
    stateWidget.options = { ...(stateWidget.options || {}), hidden: true, serialize: true };
    stateWidget.draw = () => {};
    stateWidget.computeSize = () => [0, -4];

    node.properties = node.properties || {};
    let state = bestState(
        node.properties[STATE_PROPERTY],
        ...workflowWidgetValues(node),
        stateWidget.value,
    );
    const persistState = () => {
        const value = JSON.stringify(state);
        stateWidget.value = value;
        // library_json is the single persisted source of truth. Older versions
        // duplicated this large value in properties and localStorage, which
        // exhausted browser storage and produced cross-workflow ID collisions.
        delete node.properties[STATE_PROPERTY];
        node.widgets_values = Array.isArray(node.widgets_values) ? node.widgets_values : [];
        node.widgets_values[0] = value;
        return value;
    };
    stateWidget.serializeValue = () => persistState();
    const touch = () => {
        state.updated_at = Date.now();
    };
    const root = document.createElement("div");
    root.className = "ppl-root";
    const stop = element => {
        ["pointerdown", "mousedown", "keydown", "keypress", "keyup", "copy", "cut", "paste"]
            .forEach(type => element.addEventListener(type, event => event.stopPropagation()));
        return element;
    };
    const status = document.createElement("div");
    status.className = "ppl-status";
    const setStatus = (message, error = false) => {
        status.textContent = message;
        status.classList.toggle("error", error);
    };
    const selected = () => state.presets.find(item => item.id === state.selected_id) || state.presets[0];
    let loraNames = [];
    let loraRequest;
    const loadLoras = () => {
        if (loraRequest) return;
        loraRequest = api.fetchApi("/object_info/LoraLoaderModelOnly")
            .then(response => {
                if (!response.ok) throw new Error("Could not load LoRA list");
                return response.json();
            })
            .then(info => {
                loraNames = info.LoraLoaderModelOnly?.input?.required?.lora_name?.[0] || [];
                if (selected().lora_enabled) render();
            })
            .catch(error => { loraRequest = null; setStatus(error.message, true); });
    };
    const sync = () => {
        touch();
        persistState();
        stateWidget.callback?.(stateWidget.value);
        node.graph?.setDirtyCanvas(true, true);
    };
    const button = (label, title, handler) => {
        const element = document.createElement("button");
        element.textContent = label;
        element.title = title;
        element.onclick = event => {
            event.stopPropagation();
            handler();
        };
        return element;
    };

    const render = () => {
        root.replaceChildren();
        const current = selected();

        const listLabel = document.createElement("div");
        listLabel.className = "ppl-label";
        listLabel.textContent = `Profiles ${state.presets.indexOf(current) + 1}/${state.presets.length}`;
        const list = stop(document.createElement("div"));
        list.className = "ppl-list";
        list.style.height = `${Math.max(34, state.presets.length * 25 + 8)}px`;
        state.presets.forEach(item => {
            const row = document.createElement("div");
            row.className = "ppl-profile-row";
            row.classList.toggle("selected", item.id === current.id);
            row.draggable = true;
            row.dataset.id = item.id;
            row.title = "Drag to reorder";
            const handle = document.createElement("span");
            handle.className = "ppl-drag-handle";
            handle.textContent = "[=]";
            const label = document.createElement("span");
            label.textContent = item.name;
            row.append(handle, label);
            row.onclick = event => {
                event.stopPropagation();
                state.selected_id = item.id;
                sync();
                render();
            };
            row.ondragstart = event => {
                event.stopPropagation();
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", item.id);
            };
            row.ondragover = event => {
                event.preventDefault();
                event.stopPropagation();
                event.dataTransfer.dropEffect = "move";
                row.classList.add("drag-over");
            };
            row.ondragleave = () => row.classList.remove("drag-over");
            row.ondrop = event => {
                event.preventDefault();
                event.stopPropagation();
                row.classList.remove("drag-over");
                const sourceId = event.dataTransfer.getData("text/plain");
                const from = state.presets.findIndex(preset => preset.id === sourceId);
                const to = state.presets.findIndex(preset => preset.id === item.id);
                if (from < 0 || to < 0 || from === to) return;
                const [moved] = state.presets.splice(from, 1);
                state.presets.splice(to, 0, moved);
                sync();
                render();
                setStatus("Profile order updated.");
            };
            list.append(row);
        });
        root.append(listLabel, list);

        const toolbar = document.createElement("div");
        toolbar.className = "ppl-toolbar";
        toolbar.append(
            button("+ Add", "Add an empty profile", () => {
                const item = {
                    id: uid(),
                    name: `Preset ${state.presets.length + 1}`,
                    prompt: "",
                    pair_enabled: false,
                    prompt_2: "",
                };
                state.presets.push(item);
                state.selected_id = item.id;
                sync(); render(); setStatus("Profile added.");
            }),
            button("Duplicate", "Duplicate the selected profile", () => {
                const item = { ...structuredClone(current), id: uid(), name: `${current.name} Copy` };
                state.presets.push(item);
                state.selected_id = item.id;
                sync(); render(); setStatus("Profile duplicated.");
            }),
            button("Delete", "Delete the selected profile", () => {
                if (state.presets.length <= 1) return setStatus("At least one profile is required.", true);
                const index = state.presets.indexOf(current);
                state.presets.splice(index, 1);
                state.selected_id = state.presets[Math.min(index, state.presets.length - 1)].id;
                sync(); render(); setStatus("Profile deleted.");
            }),
        );
        root.append(toolbar);

        const nameLabel = document.createElement("div");
        nameLabel.className = "ppl-label";
        nameLabel.textContent = "Profile name";
        const name = stop(document.createElement("input"));
        name.value = current.name;
        name.placeholder = "Profile name";
        name.oninput = () => {
            current.name = name.value;
            sync();
        };
        name.onchange = render;

        const pairRow = document.createElement("label");
        pairRow.className = "ppl-pair-row";
        const pairEnabled = stop(document.createElement("input"));
        pairEnabled.type = "checkbox";
        pairEnabled.checked = current.pair_enabled;
        const pairText = document.createElement("span");
        pairText.textContent = "Pair (use two prompts)";
        pairEnabled.onchange = () => {
            current.pair_enabled = pairEnabled.checked;
            sync();
            render();
        };
        pairRow.append(pairEnabled, pairText);

        const promptLabel = document.createElement("div");
        promptLabel.className = "ppl-label";
        promptLabel.textContent = current.pair_enabled ? "Prompt 1" : "Prompt";
        const prompt = stop(document.createElement("textarea"));
        prompt.className = "ppl-prompt";
        prompt.placeholder = "Prompt text";
        prompt.value = current.prompt;
        prompt.oninput = () => {
            current.prompt = prompt.value;
            sync();
        };
        root.append(nameLabel, name, pairRow, promptLabel, prompt);

        if (current.pair_enabled) {
            const prompt2Label = document.createElement("div");
            prompt2Label.className = "ppl-label";
            prompt2Label.textContent = "Prompt 2";
            const prompt2 = stop(document.createElement("textarea"));
            prompt2.className = "ppl-prompt";
            prompt2.placeholder = "Second prompt text";
            prompt2.value = current.prompt_2;
            prompt2.oninput = () => {
                current.prompt_2 = prompt2.value;
                sync();
            };
            root.append(prompt2Label, prompt2);
        }
        const loraRow = document.createElement("label");
        loraRow.className = "ppl-pair-row";
        const loraEnabled = stop(document.createElement("input"));
        loraEnabled.type = "checkbox";
        loraEnabled.checked = current.lora_enabled === true;
        const loraLabel = document.createElement("span");
        loraLabel.textContent = "LoRA";
        loraEnabled.onchange = () => {
            current.lora_enabled = loraEnabled.checked;
            current.lora_name ??= "";
            current.lora_strength ??= 1;
            sync(); render();
        };
        loraRow.append(loraEnabled, loraLabel);
        root.append(loraRow);
        if (current.lora_enabled) {
            if (!Array.isArray(current.loras)) {
                current.loras = current.lora_name ? [{ enabled: true, lora_name: current.lora_name, lora_strength: current.lora_strength ?? 1, lora_video: current.lora_video ?? 1, lora_audio: current.lora_audio ?? 1 }] : [];
                persistState();
            }
            for (const lora of current.loras) {
            const controls = document.createElement("div");
            controls.className = "ppl-lora-controls";
            const rowHeader = document.createElement("div");
            rowHeader.className = "ppl-pair-row";
            const enabled = stop(document.createElement("input"));
            enabled.type = "checkbox";
            enabled.checked = lora.enabled !== false;
            enabled.title = "Enable LoRA";
            enabled.onchange = () => { lora.enabled = enabled.checked; sync(); };
            rowHeader.append(enabled, button("\u00d7", "Remove LoRA", () => {
                current.loras.splice(current.loras.indexOf(lora), 1); sync(); render();
            }));
            const chooser = stop(document.createElement("select"));
            chooser.title = "LoRA file";
            chooser.size = 4;
            const search = stop(document.createElement("input"));
            search.placeholder = "Search LoRA";
            search.title = "Search LoRA by filename or folder";
            const fillChoices = () => {
                chooser.replaceChildren();
                const query = search.value.trim().toLowerCase();
                chooser.style.display = query ? "block" : "none";
                for (const value of [...new Set([lora.lora_name || "", ...loraNames])]) {
                    if (!value || !value.toLowerCase().includes(query)) continue;
                    const option = document.createElement("option");
                    option.value = value;
                    option.textContent = value;
                    chooser.append(option);
                }
                chooser.value = lora.lora_name || "";
            };
            search.oninput = fillChoices;
            fillChoices();
            const weights = document.createElement("div");
            weights.className = "ppl-lora-weights";
            for (const [key, label, min, max] of [["lora_strength", "Strength", -10, 10], ["lora_video", "Video", 0, 2], ["lora_audio", "Audio", 0, 2]]) {
                const column = document.createElement("div");
                const title = document.createElement("div");
                title.className = "ppl-label";
                title.textContent = label;
                const stepper = document.createElement("div");
                stepper.className = "ppl-lora-stepper";
                const input = stop(document.createElement("input"));
                input.type = "number";
                input.step = "0.05";
                input.min = min;
                input.max = max;
                input.title = label;
                input.value = Number(lora[key] ?? 1).toFixed(2);
                const update = value => {
                    if (!Number.isFinite(value)) return;
                    lora[key] = Math.round(Math.max(min, Math.min(max, value)) * 100) / 100;
                    sync();
                };
                input.oninput = () => { if (input.value.trim()) update(Number(input.value)); };
                input.onchange = () => { input.value = Number(lora[key] ?? 1).toFixed(2); };
                const step = delta => { update(Number(lora[key] ?? 1) + delta); input.value = Number(lora[key]).toFixed(2); };
                stepper.append(button("\u25c0", `Decrease ${label}`, () => step(-0.05)), input, button("\u25b6", `Increase ${label}`, () => step(0.05)));
                column.append(title, stepper);
                weights.append(column);
            }
            const selectedFile = document.createElement("div");
            selectedFile.className = "ppl-label";
            selectedFile.style.overflowWrap = "anywhere";
            selectedFile.textContent = lora.lora_name || "Select LoRA";
            chooser.onchange = () => {
                lora.lora_name = chooser.value; selectedFile.textContent = chooser.value;
                search.value = ""; fillChoices(); sync();
            };
            controls.append(rowHeader, search, chooser, selectedFile, weights);
            root.append(controls);
            }
            root.append(button("+ Add LoRA", "Add a LoRA", () => {
                current.loras.push({ enabled: true, lora_name: "", lora_strength: 1, lora_video: 1, lora_audio: 0 });
                sync(); render();
            }));
            loadLoras();
        }
        root.append(status);
        requestAnimationFrame(fit);
    };

    let domWidget;
    const listHeight = () => Math.max(34, state.presets.length * 25 + 8);
    const widgetHeight = () => 486 + listHeight() + (selected().pair_enabled ? 245 : 0) + (selected().lora_enabled ? 35 + (selected().loras?.length || 0) * 230 : 0);
    if (node.addDOMWidget) {
        domWidget = node.addDOMWidget("prompt_preset_library_ui", "custom", root, {
            serialize: false,
            hideOnZoom: false,
            getHeight: widgetHeight,
        });
        domWidget.computeSize = () => [540, widgetHeight()];
    }
    let fitting = false;
    const fit = () => {
        if (fitting) return;
        const width = Math.max(540, node.size?.[0] || 540);
        const height = widgetHeight() + 40;
        if (node.size?.[0] !== width || node.size?.[1] !== height) {
            fitting = true;
            node.setSize?.([width, height]);
            fitting = false;
        }
        root.style.width = `${Math.max(1, width - 20)}px`;
        root.style.height = `${widgetHeight()}px`;
    };
    const restore = info => {
        const configuredValues = [
            info?.properties?.[STATE_PROPERTY],
            ...workflowWidgetValues(info),
        ].filter(hasSavedPresetState);

        // ComfyUI copies nodes through source.clone().serialize(). During clone(),
        // configure(info) is the authoritative copy payload and must not lose to
        // a newer localStorage entry belonging to the temporary clone id.
        state = configuredValues.length
            ? bestState(...configuredValues)
            : bestState(
                ...workflowWidgetValues(node),
                node.properties?.[STATE_PROPERTY],
                stateWidget.value,
            );
        persistState();
        render();
        fit();
    };
    const oldConfigure = node.onConfigure;
    node.onConfigure = function (info, ...args) {
        const result = oldConfigure?.apply(this, [info, ...args]);
        // This must be synchronous. ComfyUI serializes a temporary clone
        // immediately after configure() returns when copying a node.
        restore(info);
        return result;
    };
    const oldSerialize = node.onSerialize;
    node.onSerialize = function (data, ...args) {
        const value = persistState();
        const result = oldSerialize?.apply(this, [data, ...args]);
        if (data) {
            data.properties = data.properties || {};
            delete data.properties[STATE_PROPERTY];
            data.widgets_values = Array.isArray(data.widgets_values) ? data.widgets_values : [];
            data.widgets_values[0] = value;
        }
        return result;
    };
    const oldNodeSerialize = node.serialize;
    node.serialize = function (...args) {
        const value = persistState();
        const data = oldNodeSerialize?.apply(this, args);
        if (data && typeof data === "object") {
            data.properties = data.properties || {};
            delete data.properties[STATE_PROPERTY];
            data.widgets_values = Array.isArray(data.widgets_values) ? data.widgets_values : [];
            data.widgets_values[0] = value;
        }
        return data;
    };
    const oldResize = node.onResize;
    node.onResize = function (...args) {
        oldResize?.apply(this, args);
        fit();
    };
    node.__promptPresetLibraryRestore = info => restore(info);
    if (
        hasSavedPresetState(node.properties?.[STATE_PROPERTY])
        || workflowWidgetValues(node).some(hasSavedPresetState)
        || hasSavedPresetState(stateWidget.value)
    ) {
        restore();
    } else {
        render();
        requestAnimationFrame(fit);
    }
}

app.registerExtension({
    name: "WildcardImageIterator.PromptPresetLibrary",
    nodeCreated(node) {
        if (node.comfyClass === "PromptPresetLibrary") install(node);
    },
    loadedGraphNode(node) {
        if (node.comfyClass === "PromptPresetLibrary") {
            install(node);
            node.__promptPresetLibraryRestore?.(node);
        }
    },
});
