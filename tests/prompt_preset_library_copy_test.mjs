import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

class FakeClassList {
    add() {}
    remove() {}
    toggle() {}
}

class FakeElement {
    constructor() {
        this.children = [];
        this.style = {};
        this.dataset = {};
        this.classList = new FakeClassList();
        this.value = "";
        this.checked = false;
    }

    append(...children) {
        this.children.push(...children);
    }

    appendChild(child) {
        this.children.push(child);
        return child;
    }

    replaceChildren(...children) {
        this.children = children;
    }

    addEventListener() {}
}

const storage = new Map();
const localStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
};

let extension;
const animationFrameQueue = [];
const app = {
    registerExtension(value) {
        extension = value;
    },
};

const context = vm.createContext({
    app,
    api: { fetchApi: async () => ({ ok: true, json: async () => ({ LoraLoaderModelOnly: { input: { required: { lora_name: [["example.safetensors"]] } } } }) }) },
    console,
    Date,
    JSON,
    Math,
    localStorage,
    location: { pathname: "/" },
    document: {
        createElement: () => new FakeElement(),
        head: new FakeElement(),
    },
    requestAnimationFrame: callback => {
        animationFrameQueue.push(callback);
        return animationFrameQueue.length;
    },
    structuredClone,
});

const sourcePath = new URL("../web/prompt_preset_library.js", import.meta.url);
const sourceCode = fs.readFileSync(sourcePath, "utf8")
    .replace(/^import .*?;\s*/gm, "");
new vm.Script(sourceCode, { filename: sourcePath.pathname }).runInContext(context);

assert.ok(extension, "Prompt Preset Library extension was not registered");

const defaultLibrary = JSON.stringify({
    version: 2,
    presets: [{ id: "preset-1", name: "Preset 1", prompt: "", pair_enabled: false, prompt_2: "" }],
    selected_id: "preset-1",
    updated_at: 0,
});

function createNode(id = -1) {
    const stateWidget = {
        name: "library_json",
        value: defaultLibrary,
        options: {},
    };
    const node = {
        id,
        type: "PromptPresetLibrary",
        comfyClass: "PromptPresetLibrary",
        properties: {},
        widgets: [stateWidget],
        widgets_values: [defaultLibrary],
        size: [540, 540],
        addDOMWidget(name, type, element) {
            this.ui = element;
            const widget = {};
            this.widgets.push(widget);
            return widget;
        },
        setSize(size) {
            this.size = [...size];
        },
        configure(info) {
            this.properties = structuredClone(info.properties || {});
            this.widgets_values = structuredClone(info.widgets_values || []);
            if (this.widgets_values[0] != null) stateWidget.value = this.widgets_values[0];
            this.onConfigure?.(info);
        },
        serialize() {
            const data = {
                id: this.id,
                type: this.type,
                properties: structuredClone(this.properties || {}),
                widgets_values: this.widgets.map(widget => widget.serialize === false ? undefined : (widget.value ?? null)),
            };
            this.onSerialize?.(data);
            return data;
        },
        clone() {
            const clone = createNode(-1);
            clone.configure(structuredClone(this.serialize()));
            return clone;
        },
    };
    extension.nodeCreated(node);
    return node;
}

const expectedState = {
    version: 2,
    presets: [
        { id: "one", name: "Profile One", prompt: "alpha prompt", pair_enabled: false, prompt_2: "" },
        { id: "two", name: "Profile Two", prompt: "beta prompt", pair_enabled: true, prompt_2: "beta second", lora_enabled: true, lora_name: "example.safetensors", lora_strength: 0.65, lora_video: 0.75, lora_audio: 0 },
    ],
    selected_id: "two",
    updated_at: 100,
};

const original = createNode(3009);
expectedState.presets[1].loras = [{ enabled: true, lora_name: "example.safetensors", lora_strength: 0.65, lora_video: 0.75, lora_audio: 0 }];
const configuredJson = JSON.stringify(expectedState);
original.configure({
    properties: { prompt_preset_library_state: configuredJson },
    widgets_values: [configuredJson],
});

// Stale data from an older extension version must not affect copy/duplicate.
const staleState = {
    ...expectedState,
    presets: [{ id: "stale", name: "Wrong Local State", prompt: "wrong", pair_enabled: false, prompt_2: "" }],
    selected_id: "stale",
    updated_at: 999999,
};
localStorage.setItem(
    "WildcardImageIterator.PromptPresetLibrary./.-1",
    JSON.stringify(staleState),
);

// ComfyUI 1.48.x: selected item -> item.clone() -> cloned.serialize().
const copiedData = original.clone().serialize();
const copiedWidgetState = JSON.parse(copiedData.widgets_values[0]);

assert.equal(copiedData.properties.prompt_preset_library_state, undefined);
assert.deepEqual(copiedWidgetState.presets, expectedState.presets);
assert.equal(copiedWidgetState.selected_id, "two");

// Paste creates another fresh node and configures it from the clipboard data.
const pasted = createNode(3011);
pasted.configure(structuredClone(copiedData));
const pastedData = pasted.serialize();
const pastedState = JSON.parse(pastedData.widgets_values[0]);
assert.deepEqual(pastedState.presets, expectedState.presets);
assert.equal(pastedState.selected_id, "two");
assert.equal(pastedData.properties.prompt_preset_library_state, undefined);
const reloaded = createNode(3012);
reloaded.configure(structuredClone(pastedData));
assert.deepEqual(JSON.parse(reloaded.serialize().widgets_values[0]).presets, expectedState.presets);
assert.equal(storage.get("WildcardImageIterator.PromptPresetLibrary./.-1"), JSON.stringify(staleState));

console.log("Prompt Preset Library copy/duplicate state test passed.");
await Promise.resolve();
await Promise.resolve();
await Promise.resolve();
function elements(root) { return [root, ...root.children.flatMap(elements)]; }
const search = elements(reloaded.ui).find(element => element.placeholder === "Search LoRA");
assert.ok(search);
search.value = "no match";
search.oninput();
const chooser = elements(reloaded.ui).find(element => element.title === "LoRA file");
assert.equal(chooser.children.length, 0);
search.value = "EXAMPLE";
search.oninput();
assert.ok(chooser.children.some(option => option.value === "example.safetensors"));
const increase = elements(reloaded.ui).find(element => element.title === "Increase Video");
increase.onclick({ stopPropagation() {} });
assert.equal(JSON.parse(reloaded.serialize().widgets_values[0]).presets[1].loras[0].lora_video, 0.8);
assert.equal(JSON.parse(reloaded.clone().serialize().widgets_values[0]).presets[1].loras[0].lora_video, 0.8);
elements(reloaded.ui).find(element => element.title === "Add a LoRA").onclick({ stopPropagation() {} });
assert.equal(JSON.parse(reloaded.serialize().widgets_values[0]).presets[1].loras.length, 2);
elements(reloaded.ui).find(element => element.title === "Remove LoRA").onclick({ stopPropagation() {} });
assert.equal(JSON.parse(reloaded.serialize().widgets_values[0]).presets[1].loras.length, 1);
console.log("Prompt preset LoRA search and weight controls tests passed.");
