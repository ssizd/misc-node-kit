import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const EXTENSION_NAME = "wildcard_image_iterator.VideoSaverPreview";
const PREVIEW_WIDGET_NAME = "video_saver_preview";

function buildVideoUrl(info) {
    const params = new URLSearchParams();
    params.set("filename", info.filename || "");
    params.set("type", info.type || "output");
    params.set("subfolder", info.subfolder || "");
    params.set("t", Date.now().toString());
    return `/view?${params.toString()}`;
}

function getWidget(node, name) {
    return node.widgets?.find((widget) => widget.name === name);
}

function setNodeSizeForPreview(node) {
    if (!node?.setSize || !node.size) return;
    const width = Math.max(node.size[0] || 360, 420);
    const preview = node.__videoSaverPreview;
    const height = Math.max(node.size[1] || 0, previewHeight(node, preview) + 330);
    node.setSize([width, height]);
}

function previewWidth(node) {
    return Math.max(320, (node?.size?.[0] || 420) - 20);
}

function previewHeight(node, preview) {
    const aspect = preview?.aspect || 16 / 9;
    return Math.max(120, Math.round(previewWidth(node) / aspect));
}

function syncPreviewLayout(node) {
    const preview = node.__videoSaverPreview;
    if (!preview) return;
    const width = previewWidth(node);
    const height = previewHeight(node, preview);
    preview.root.style.width = `${width}px`;
    preview.video.style.width = `${width}px`;
    preview.video.style.height = `${height}px`;
    preview.widget && (preview.widget.computeSize = () => [width, height + 34]);
    node.graph?.setDirtyCanvas(true, true);
}

function makeButton(label, title) {
    const button = document.createElement("button");
    button.textContent = label;
    button.title = title || label;
    button.style.cssText = [
        "background:#2b2b2b",
        "border:1px solid #555",
        "border-radius:3px",
        "color:#ddd",
        "cursor:pointer",
        "font-size:10px",
        "font-weight:600",
        "padding:3px 7px",
    ].join(";");
    return button;
}

function ensurePreview(node) {
    if (node.__videoSaverPreview) return node.__videoSaverPreview;

    const root = document.createElement("div");
    root.style.cssText = [
        "box-sizing:border-box",
        "display:flex",
        "flex-direction:column",
        "gap:6px",
        "padding:6px 0 0",
        "width:100%",
    ].join(";");

    const video = document.createElement("video");
    video.controls = true;
    video.loop = true;
    video.preload = "metadata";
    video.playsInline = true;
    video.style.cssText = [
        "background:transparent",
        "display:block",
        "height:236px",
        "object-fit:fill",
        "width:100%",
    ].join(";");

    const row = document.createElement("div");
    row.style.cssText = [
        "align-items:center",
        "display:flex",
        "gap:6px",
        "justify-content:flex-end",
        "min-height:22px",
    ].join(";");

    const spacer = document.createElement("span");
    spacer.style.flex = "1";

    const autoplayLabel = document.createElement("label");
    autoplayLabel.style.cssText = [
        "align-items:center",
        "color:#ddd",
        "display:flex",
        "font-size:10px",
        "gap:4px",
        "user-select:none",
    ].join(";");
    const autoplay = document.createElement("input");
    autoplay.type = "checkbox";
    autoplay.style.margin = "0";
    autoplayLabel.append(autoplay, document.createTextNode("Autoplay"));

    const download = makeButton("Download", "Download saved video");
    download.disabled = true;

    row.append(spacer, autoplayLabel, download);
    root.append(video, row);

    const preview = { root, video, autoplay, download, url: "", aspect: 16 / 9, widget: null };
    node.__videoSaverPreview = preview;

    if (typeof node.addDOMWidget === "function") {
        const widget = node.addDOMWidget(PREVIEW_WIDGET_NAME, "custom", root, {
            hideOnZoom: false,
            serialize: false,
        });
        preview.widget = widget;
        widget.computeSize = () => [previewWidth(node), previewHeight(node, preview) + 34];
    }

    video.addEventListener("loadedmetadata", () => {
        if (video.videoWidth > 0 && video.videoHeight > 0) {
            preview.aspect = video.videoWidth / video.videoHeight;
        }
        syncPreviewLayout(node);
        setNodeSizeForPreview(node);
    });

    autoplay.addEventListener("change", () => {
        const widget = getWidget(node, "preview_autoplay");
        if (widget) {
            widget.value = autoplay.checked;
            widget.callback?.(widget.value);
        }
        if (autoplay.checked && video.src) {
            video.muted = true;
            video.play().catch(() => {});
        } else {
            video.pause();
        }
    });

    download.addEventListener("click", () => {
        if (!preview.url) return;
        const anchor = document.createElement("a");
        anchor.href = preview.url;
        anchor.download = "";
        document.body.append(anchor);
        anchor.click();
        anchor.remove();
    });

    const oldResize = node.onResize;
    node.onResize = function (...args) {
        oldResize?.apply(this, args);
        syncPreviewLayout(this);
    };

    syncPreviewLayout(node);
    setNodeSizeForPreview(node);
    return preview;
}

function showPreview(node, info) {
    if (!node || node.comfyClass !== "VideoSaver" || !info) return;
    const preview = ensurePreview(node);
    const widget = getWidget(node, "preview_autoplay");
    const autoplayEnabled = widget ? Boolean(widget.value) : Boolean(info.autoplay);
    const url = buildVideoUrl(info);

    preview.url = url;
    preview.autoplay.checked = autoplayEnabled;
    preview.video.src = url;
    preview.video.muted = autoplayEnabled;
    preview.video.load();
    preview.download.disabled = false;
    syncPreviewLayout(node);

    if (autoplayEnabled) {
        preview.video.play().catch(() => {});
    }
    setNodeSizeForPreview(node);
}

function removePreview(node) {
    const preview = node.__videoSaverPreview;
    if (!preview) return;
    preview.video.pause();
    preview.video.removeAttribute("src");
    preview.video.load();
    node.__videoSaverPreview = null;
}

function findNodeById(id) {
    const graph = app.graph;
    if (!graph) return null;
    if (typeof graph.getNodeById === "function") return graph.getNodeById(id);
    return graph._nodes_by_id?.[id] || null;
}

api.addEventListener("executed", (event) => {
    const detail = event.detail || {};
    const gifs = detail.output?.gifs;
    if (!gifs?.length) return;
    showPreview(findNodeById(detail.node), gifs[0]);
});

app.registerExtension({
    name: EXTENSION_NAME,
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "VideoSaver") return;

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            const gifs = message?.gifs;
            if (gifs?.length) showPreview(this, gifs[0]);
        };

        const onRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            removePreview(this);
            onRemoved?.apply(this, arguments);
        };
    },
});
