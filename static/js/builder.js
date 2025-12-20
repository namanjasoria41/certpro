let canvas;
let bgImage = null;
let selectedObject = null;

/* ================= INIT ================= */
window.addEventListener("load", () => {
    const img = new Image();
    img.onload = () => initCanvas(img);
    img.src = TEMPLATE_URL;
});

/* ================= CANVAS ================= */
function initCanvas(img) {
    canvas = new fabric.Canvas("builderCanvas", {
        selection: true,
        preserveObjectStacking: true
    });

    canvas.setWidth(img.width);
    canvas.setHeight(img.height);

    bgImage = new fabric.Image(img, {
        selectable: false,
        evented: false
    });

    canvas.setBackgroundImage(bgImage, canvas.renderAll.bind(canvas));

    loadExistingFields();
    bindCanvasEvents();
}

/* ================= LOAD FIELDS ================= */
function loadExistingFields() {
    (EXISTING_FIELDS || []).forEach(f => {
        const obj = createObjectFromField(f);
        if (obj) canvas.add(obj);
    });
    refreshLayers();
}

/* ================= FIELD FACTORY ================= */
function createObjectFromField(f) {
    const type = f.field_type || f.type || "text";

    if (type === "image") {
        const rect = new fabric.Rect({
            left: f.x || 0,
            top: f.y || 0,
            width: f.width || 120,
            height: f.height || 120,
            fill: "rgba(255,255,255,0.15)",
            stroke: "#00ffd5",
            strokeDashArray: [6, 6],
        });

        rect.fieldMeta = normalizeMeta(f, "image");
        return rect;
    }

    const text = new fabric.Textbox("Text", {
        left: f.x || 0,
        top: f.y || 0,
        fontSize: f.font_size || 24,
        fill: f.color || "#ffffff",
        width: 300
    });

    text.fieldMeta = normalizeMeta(f, "text");
    return text;
}

/* ================= META NORMALIZER ================= */
function normalizeMeta(f, type) {
    return {
        field_name: f.field_name || f.name || "",
        field_type: type,
        font_size: f.font_size || f.size || 24,
        color: f.color || "#ffffff",
        width: f.width || null,
        height: f.height || null,
        shape: f.shape || "rect"
    };
}

/* ================= EVENTS ================= */
function bindCanvasEvents() {
    canvas.on("selection:created", e => select(e.selected[0]));
    canvas.on("selection:updated", e => select(e.selected[0]));
    canvas.on("selection:cleared", () => selectedObject = null);
}

function select(obj) {
    selectedObject = obj;
    document.getElementById("propName").value = obj.fieldMeta.field_name || "";
    document.getElementById("propFontSize").value = obj.fontSize || 24;
    document.getElementById("propColor").value = obj.fill || "#ffffff";
}

/* ================= ADD OBJECTS ================= */
function enableAddTextMode() {
    const t = new fabric.Textbox("Text", {
        left: 80, top: 80, fontSize: 24, fill: "#ffffff"
    });
    t.fieldMeta = normalizeMeta({}, "text");
    canvas.add(t).setActiveObject(t);
}

function enableAddImageMode(circle = false) {
    const r = new fabric.Rect({
        left: 100, top: 100, width: 120, height: 120,
        fill: "rgba(255,255,255,0.15)",
        stroke: "#00ffd5", strokeDashArray: [6,6]
    });
    r.fieldMeta = normalizeMeta({ shape: circle ? "circle" : "rect" }, "image");
    canvas.add(r).setActiveObject(r);
}

/* ================= SAVE ================= */
function saveTemplate() {
    const fields = canvas.getObjects().map(o => ({
        field_name: o.fieldMeta.field_name,
        field_type: o.fieldMeta.field_type,
        x: Math.round(o.left),
        y: Math.round(o.top),
        font_size: o.fontSize || o.fieldMeta.font_size,
        color: o.fill || o.fieldMeta.color,
        width: o.width,
        height: o.height,
        shape: o.fieldMeta.shape
    }));

    fetch("", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields })
    }).then(() => alert("Saved"));
}

/* ================= DELETE ================= */
function deleteSelectedField() {
    if (!selectedObject) return;
    canvas.remove(selectedObject);
    selectedObject = null;
}
