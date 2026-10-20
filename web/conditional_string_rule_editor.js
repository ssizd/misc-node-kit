import { app } from "../../scripts/app.js";
import { ComfyWidgets } from "../../scripts/widgets.js";

const RULE_MODES = ["after_match", "prepend", "append", "replace_match"];

function defaultRule(first = false) {
    return {
        enabled: true,
        if_has: first ? "1boy" : "",
        unless_has: first ? "pov" : "",
        add: first ? "name" : "",
        mode: "after_match",
    };
}

function parseRules(value) {
    if (typeof value !== "string") return null;
    try {
        const parsed = JSON.parse(value);
        if (!Array.isArray(parsed)) return null;
        return parsed.filter((rule) => rule && typeof rule === "object").map((rule) => ({
            enabled: rule.enabled !== false,
            if_has: String(rule.if_has ?? rule.include ?? ""),
            unless_has: String(rule.unless_has ?? rule.exclude ?? ""),
            add: String(rule.add ?? rule.insert ?? ""),
            mode: RULE_MODES.includes(rule.mode) ? rule.mode : "after_match",
        }));
    } catch {
        return null;
    }
}

function migrateLegacyRules(widgetValues) {
    if (!Array.isArray(widgetValues) || widgetValues.length < 9) return null;
    const candidates = [];
    const startOffset = typeof widgetValues[4] === "boolean" ? 4 : 5;
    for (let offset = startOffset; offset + 4 < widgetValues.length; offset += 5) {
        const enabled = widgetValues[offset];
        if (typeof enabled !== "boolean") break;
        candidates.push({
            enabled,
            if_has: String(widgetValues[offset + 1] ?? ""),
            unless_has: String(widgetValues[offset + 2] ?? ""),
            add: String(widgetValues[offset + 3] ?? ""),
            mode: RULE_MODES.includes(widgetValues[offset + 4]) ? widgetValues[offset + 4] : "after_match",
        });
    }
    while (candidates.length > 1) {
        const last = candidates[candidates.length - 1];
        if (last.enabled || last.if_has || last.unless_has || last.add) break;
        candidates.pop();
    }
    return candidates.length ? candidates : null;
}

function stateWidget(node) {
    return node.widgets?.find((widget) => widget.name === "rules_json");
}

function hideStateWidget(node) {
    const widget = stateWidget(node);
    if (!widget || widget._conditionalRuleStateHidden) return;
    widget._conditionalRuleStateHidden = true;
    widget.serialize = true;
    widget.options = widget.options || {};
    widget.options.serialize = true;
    widget.computeSize = () => [0, -4];
    widget.draw = () => {};
    widget.serializeValue = () => {
        syncState(node);
        return widget.value;
    };
}

function ruleFromEntry(entry) {
    return {
        enabled: entry.enabled.value !== false,
        if_has: String(entry.ifHas.value ?? ""),
        unless_has: String(entry.unlessHas.value ?? ""),
        add: String(entry.add.value ?? ""),
        mode: RULE_MODES.includes(entry.mode.value) ? entry.mode.value : "after_match",
    };
}

function syncState(node) {
    const widget = stateWidget(node);
    if (!widget) return;
    const rules = (node._conditionalRuleEntries || []).map(ruleFromEntry);
    widget.value = JSON.stringify(rules);
    node.properties = node.properties || {};
    node.properties.conditional_rule_count = rules.length;
}

function markDynamicWidget(widget, node) {
    widget.serialize = false;
    widget.options = widget.options || {};
    widget.options.serialize = false;
    const originalCallback = widget.callback;
    widget.callback = function () {
        const result = originalCallback?.apply(this, arguments);
        syncState(node);
        app.graph?.setDirtyCanvas(true, true);
        return result;
    };
    return widget;
}

function addStringWidget(node, name, value) {
    const config = ["STRING", { default: String(value ?? "") }];
    node.constructor.nodeData.input.optional = node.constructor.nodeData.input.optional || {};
    node.constructor.nodeData.input.optional[name] = config;
    const widget = ComfyWidgets.STRING(node, name, config, app).widget;
    widget.value = String(value ?? "");
    widget.inputData = config;
    return markDynamicWidget(widget, node);
}

function ensureWidgetInput(node, widget) {
    const config = widget.inputData || ["STRING", { default: "" }];
    let input = (node.inputs || []).find((candidate) => candidate.name === widget.name);
    if (!input) {
        const size = node.size ? [...node.size] : null;
        node.addInput(widget.name, config[0], {
            widget: { name: widget.name, config },
        });
        input = (node.inputs || []).find((candidate) => candidate.name === widget.name);
        if (size) node.setSize?.([Math.max(size[0], node.size?.[0] || size[0]), Math.max(size[1], node.size?.[1] || size[1])]);
    }
    if (!input) return;
    input.widget = input.widget || { name: widget.name, config };
}

function moveButtonsToBottom(node) {
    const buttons = node._conditionalRuleButtons || [];
    if (!buttons.length) return;
    const buttonSet = new Set(buttons);
    node.widgets = (node.widgets || []).filter((widget) => !buttonSet.has(widget));
    node.widgets.push(...buttons);
}

function fitNode(node) {
    const computed = node.computeSize?.() || [500, 260];
    const size = [Math.max(500, computed[0]), Math.max(260, computed[1])];
    node.setSize?.(size);
    app.graph?.setDirtyCanvas(true, true);
}

function addRule(node, rule = defaultRule(false)) {
    const index = (node._conditionalRuleEntries?.length || 0) + 1;
    const enabled = markDynamicWidget(
        node.addWidget("toggle", `rule_${index} enabled`, rule.enabled !== false, () => {}),
        node,
    );
    const ifHas = addStringWidget(node, `rule_${index} if has`, rule.if_has);
    const unlessHas = addStringWidget(node, `rule_${index} unless has`, rule.unless_has);
    const add = addStringWidget(node, `rule_${index} add`, rule.add);
    const mode = markDynamicWidget(
        node.addWidget("combo", `rule_${index} mode`, rule.mode || "after_match", () => {}, { values: RULE_MODES }),
        node,
    );
    const entry = { enabled, ifHas, unlessHas, add, mode };
    node._conditionalRuleEntries = node._conditionalRuleEntries || [];
    node._conditionalRuleEntries.push(entry);
    ensureWidgetInput(node, add);
    moveButtonsToBottom(node);
    syncState(node);
    fitNode(node);
}

function removeLastRule(node) {
    const entries = node._conditionalRuleEntries || [];
    if (entries.length <= 1) return;
    const index = entries.length;
    const entry = entries.pop();
    const widgets = new Set(Object.values(entry));
    node.widgets = (node.widgets || []).filter((widget) => !widgets.has(widget));
    const inputIndex = (node.inputs || []).findIndex((input) => input.name === `rule_${index} add`);
    if (inputIndex >= 0) node.removeInput(inputIndex);
    syncState(node);
    fitNode(node);
}

function clearRuleWidgets(node) {
    const widgets = new Set(
        (node._conditionalRuleEntries || []).flatMap((entry) => Object.values(entry)),
    );
    node.widgets = (node.widgets || []).filter((widget) => !widgets.has(widget));
    const ruleAddInputs = new Set(
        (node._conditionalRuleEntries || []).map((_, index) => `rule_${index + 1} add`),
    );
    for (let index = (node.inputs || []).length - 1; index >= 0; index--) {
        if (ruleAddInputs.has(node.inputs[index].name)) node.removeInput(index);
    }
    node._conditionalRuleEntries = [];
}

function rebuildRules(node, rules) {
    clearRuleWidgets(node);
    const restored = rules?.length ? rules : [defaultRule(true)];
    for (const rule of restored) addRule(node, rule);
    moveButtonsToBottom(node);
    syncState(node);
    fitNode(node);
}

function addButtons(node) {
    if (node._conditionalRuleButtons?.length) return;
    const addButton = node.addWidget("button", "+ Add Rule", null, () => addRule(node));
    addButton.serialize = false;
    addButton.options = { ...(addButton.options || {}), serialize: false };
    const removeButton = node.addWidget("button", "- Remove Rule", null, () => removeLastRule(node));
    removeButton.serialize = false;
    removeButton.options = { ...(removeButton.options || {}), serialize: false };
    node._conditionalRuleButtons = [addButton, removeButton];
}

app.registerExtension({
    name: "ConditionalStringRuleEditor.DynamicRules",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "ConditionalStringRuleEditor") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            this._conditionalRuleEntries = [];
            this._conditionalRuleConfigured = false;
            hideStateWidget(this);
            addButtons(this);
            setTimeout(() => {
                if (!this._conditionalRuleConfigured && this._conditionalRuleEntries.length === 0) {
                    rebuildRules(this, [defaultRule(true)]);
                }
            }, 0);
            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            this._conditionalRuleConfigured = true;
            const result = onConfigure?.apply(this, arguments);
            hideStateWidget(this);
            addButtons(this);
            const parsed = parseRules(stateWidget(this)?.value);
            const migrated = parsed || migrateLegacyRules(info?.widgets_values);
            rebuildRules(this, migrated || [defaultRule(true)]);
            return result;
        };

        const onSerialize = nodeType.prototype.onSerialize;
        nodeType.prototype.onSerialize = function () {
            syncState(this);
            return onSerialize?.apply(this, arguments);
        };
    },
});
