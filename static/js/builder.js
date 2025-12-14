/*************************************************
 * SIMPLE MOBILE BUILDER — Template Editor
 * Lightweight, Fast, Touch-Friendly
 *************************************************/

let canvas = new fabric.Canvas("builderCanvas", {
    selection: true,
    preserveObjectStacking: true
});

let activeObj = null;

/*************************************************
 * AUTO LOAD BACKGROUND
 *************************************************/
fabric.Image.fromURL(TEMPLATE_URL, function(img) {
    canvas.setWidth(img.width);
    canvas.setHeight(img.height);

    img.set({ selectable: false, evented: false });

    canvas.setBackgroundImage(img, canvas.renderAll.bind(canvas));

    autoScaleCanvas();
    loadExistingFields();
});

/*************************************************
 * AUTO SCALE FOR MOBILE VIEW
 *************************************************/
function autoScaleCanvas() {
    const wrapper = document.querySelector(".builder-canvas-area");

    const maxW = wrapper.clientWidth - 20;
    const maxH = wrapper.clientHeight - 20;

    const scale = Math.min(maxW / canvas.width, maxH / canvas.height);

    canvas.setZoom(scale);
    canvas.setViewportTransform([
        scale, 0,
        0, scale,
        (maxW - canvas.width * scale) / 2,
        (maxH - canvas.height * scale) / 2
    ]);
}

/*************************************************
 * LOAD EXISTING FIELDS
 *************************************************/
function loadExistingFields() {
    EXISTING_FIELDS.forEach(f => {
        let o = null;

        if (f.field_type === "text") {
            o = new fabric.Textbox(f.field_name, {
                left: f.x,
                top: f.y,
                fontSize: f.font_size || 32,
                fill: f.color || "#ffffff",
                fontFamily: f.font_family || "Arial",
                textAlign: f.align || "left"
            });
        }

        else if (f.field_type === "image") {
            if (f.shape === "circle") {
                o = new fabric.Circle({
                    left: f.x,
                    top: f.y,
                    radius: (f.width || 100) / 2,
                    fill: "rgba(255,255,255,0.15)",
                    stroke: "#00aaff",
                    strokeWidth: 2
                });
            } else {
                o = new fabric.Rect({
                    left: f.x,
                    top: f.y,
                    width: f.width || 100,
                    height: f.height || 100,
                    fill: "rgba(255,255,255,0.15)",
                    stroke: "#00aaff",
                    strokeWidth: 2
                });
            }
        }

        if (!o) return;

        o.customId = f.field_name;
        o.field_type = f.field_type;
        o.shape = f.shape;

        canvas.add(o);
    });

    refreshLayers();
    canvas.renderAll();
}

/*************************************************
 * BASIC OBJECT CREATION
 *************************************************/
function addText() {
    let t = new fabric.Textbox("New Text", {
        left: 60,
        top: 60,
        fontSize: 32,
        fill: "#ffffff"
    });

    t.customId = "field_" + Date.now();
    t.field_type = "text";

    canvas.add(t);
    setActive(t);
}

function addImagePlaceholder() {
    let r = new fabric.Rect({
        left: 80,
        top: 80,
        width: 140,
        height: 140,
        fill: "rgba(255,255,255,0.15)",
        stroke: "#00aaff",
        strokeWidth: 2
    });

    r.customId = "field_" + Date.now();
    r.field_type = "image";
    r.shape = "rect";

    canvas.add(r);
    setActive(r);
}

function addCirclePlaceholder() {
    let c = new fabric.Circle({
        left: 100,
        top: 100,
        radius: 60,
        fill: "rgba(255,255,255,0.15)",
        stroke: "#00aaff",
        strokeWidth: 2
    });

    c.customId = "field_" + Date.now();
    c.field_type = "image";
    c.shape = "circle";

    canvas.add(c);
    setActive(c);
}

/*************************************************
 * ACTIVE SELECTION HANDLER
 *************************************************/
canvas.on("selection:created", handleSelection);
canvas.on("selection:updated", handleSelection);

function handleSelection() {
    const o = canvas.getActiveObject();
    activeObj = o;
    updatePropertiesPanel(o);
}

/*************************************************
 * PROPERTY PANEL UPDATE
 *************************************************/
function updatePropertiesPanel(o) {
    if (!o) return;

    // For property drawer:
    document.getElementById("propName").value = o.customId || "";
    document.getElementById("propFontSize").value = o.fontSize || "";
    document.getElementById("propColor").value = o.fill || "#ffffff";
}

/*************************************************
 * PROPERTY CHANGES
 *************************************************/
function updateName() {
    if (activeObj) {
        activeObj.customId = document.getElementById("propName").value;
        refreshLayers();
    }
}

function updateFontSize() {
    if (activeObj && activeObj.type === "textbox") {
        activeObj.set("fontSize", parseInt(document.getElementById("propFontSize").value));
        canvas.renderAll();
    }
}

function updateColor() {
    if (activeObj) {
        activeObj.set("fill", document.getElementById("propColor").value);
        canvas.renderAll();
    }
}

/*************************************************
 * LAYER PANEL
 *************************************************/
function refreshLayers() {
    const list = document.getElementById("layerList");
    list.innerHTML = "";

    canvas.getObjects().forEach(o => {
        let li = document.createElement("li");
        li.innerText = o.customId;
        li.onclick = () => setActive(o);
        list.appendChild(li);
    });
}

function setActive(o) {
    canvas.setActiveObject(o);
    activeObj = o;
    updatePropertiesPanel(o);
    canvas.renderAll();
}

/*************************************************
 * SLIDE-UP DRAWER FUNCTIONS
 *************************************************/
function toggleProperties() {
    document.getElementById("propertiesPanel").classList.toggle("open");
}

function toggleLayers() {
    document.getElementById("layersPanel").classList.toggle("open");
}

/*************************************************
 * SAVE TEMPLATE
 *************************************************/
function saveTemplate() {
    const objects = canvas.getObjects().map(o => ({
        field_name: o.customId,
        field_type: o.field_type,
        shape: o.shape,
        x: Math.round(o.left),
        y: Math.round(o.top),
        width: o.getScaledWidth ? Math.round(o.getScaledWidth()) : null,
        height: o.getScaledHeight ? Math.round(o.getScaledHeight()) : null,
        font_size: o.fontSize || null,
        color: o.fill || null,
        font_family: o.fontFamily || null,
        align: o.textAlign || "left"
    }));

    fetch(`/admin/template/${TEMPLATE_ID}/builder`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ fields: objects })
    })
    .then(r => r.json())
    .then(res => {
        if (res.status === "ok") {
            alert("Template Saved Successfully!");
        } else {
            alert("Failed to save template");
        }
    });
}

