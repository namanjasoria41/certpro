/*************************************************
 * SIMPLE MOBILE BUILDER — COMPLETE VERSION
 * Click to place text or image frames
 * Works on mobile + desktop
 *************************************************/

let canvas = new fabric.Canvas("builderCanvas", {
    selection: true,
    preserveObjectStacking: true
});

let activeObj = null;

// Modes
let addTextMode = false;
let addImageMode = false;
let addCircleImageMode = false;

/*************************************************
 * LOAD BACKGROUND TEMPLATE + AUTO SCALE
 *************************************************/
fabric.Image.fromURL(TEMPLATE_URL, function (img) {

    canvas.setWidth(img.width);
    canvas.setHeight(img.height);

    img.set({
        selectable: false,
        evented: false
    });

    canvas.setBackgroundImage(img, canvas.renderAll.bind(canvas));

    autoScaleCanvas();
    loadExistingFields();
});

/*************************************************
 * AUTO SCALE TO FIT MOBILE SCREEN
 *************************************************/
function autoScaleCanvas() {
    const area = document.querySelector(".builder-canvas-area");

    const maxW = area.clientWidth - 20;
    const maxH = area.clientHeight - 20;

    let scale = Math.min(maxW / canvas.width, maxH / canvas.height);

    canvas.setZoom(scale);

    canvas.setViewportTransform([
        scale, 0,
        0, scale,
        (maxW - canvas.width * scale) / 2,
        (maxH - canvas.height * scale) / 2
    ]);
}

/*************************************************
 * LOAD EXISTING FIELDS (from DB)
 *************************************************/
function loadExistingFields() {
    EXISTING_FIELDS.forEach(f => {
        let o = null;

        // TEXT
        if (f.field_type === "text") {
            o = new fabric.Textbox(f.field_name, {
                left: f.x,
                top: f.y,
                fontSize: f.font_size || 28,
                fill: f.color || "#ffffff",
                width: f.width || 200
            });
        }

        // IMAGE - RECT FRAME
        else if (f.field_type === "image" && f.shape === "rect") {
            o = new fabric.Rect({
                left: f.x,
                top: f.y,
                width: f.width || 150,
                height: f.height || 150,
                fill: "rgba(255,255,255,0.12)",
                stroke: "#00aaff",
                strokeWidth: 2
            });
        }

        // IMAGE - CIRCLE FRAME
        else if (f.field_type === "image" && f.shape === "circle") {
            o = new fabric.Circle({
                left: f.x,
                top: f.y,
                radius: (f.width || 150) / 2,
                fill: "rgba(255,255,255,0.12)",
                stroke: "#00aaff",
                strokeWidth: 2
            });
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
 * TOGGLE MODES
 *************************************************/
function enableAddTextMode() {
    addTextMode = true;
    addImageMode = false;
    addCircleImageMode = false;
    alert("Tap anywhere on the template to place text.");
}

function enableAddImageMode() {
    addImageMode = true;
    addTextMode = false;
    addCircleImageMode = false;
    alert("Tap anywhere on the template to place an image frame.");
}

function enableAddCircleImageMode() {
    addCircleImageMode = true;
    addTextMode = false;
    addImageMode = false;
    alert("Tap anywhere on the template to place a circle image frame.");
}

/*************************************************
 * CLICK HANDLER → PLACE OBJECT
 *************************************************/
canvas.on("mouse:down", function (e) {
    const pointer = canvas.getPointer(e.e);

    /************ ADD TEXT *************/
    if (addTextMode) {
        let t = new fabric.Textbox("New Text", {
            left: pointer.x,
            top: pointer.y,
            fontSize: 32,
            fill: "#ffffff",
            width: 250
        });

        t.customId = "text_" + Date.now();
        t.field_type = "text";

        canvas.add(t);
        setActive(t);

        addTextMode = false;
        return;
    }

    /************ ADD RECT IMAGE FRAME *************/
    if (addImageMode) {
        let r = new fabric.Rect({
            left: pointer.x,
            top: pointer.y,
            width: 160,
            height: 160,
            fill: "rgba(255,255,255,0.12)",
            stroke: "#00aaff",
            strokeWidth: 2,
        });

        r.customId = "image_" + Date.now();
        r.field_type = "image";
        r.shape = "rect";

        canvas.add(r);
        setActive(r);

        addImageMode = false;
        return;
    }

    /************ ADD CIRCLE IMAGE FRAME *************/
    if (addCircleImageMode) {
        let c = new fabric.Circle({
            left: pointer.x,
            top: pointer.y,
            radius: 80,
            fill: "rgba(255,255,255,0.12)",
            stroke: "#00aaff",
            strokeWidth: 2,
        });

        c.customId = "circle_" + Date.now();
        c.field_type = "image";
        c.shape = "circle";

        canvas.add(c);
        setActive(c);

        addCircleImageMode = false;
        return;
    }
});

/*************************************************
 * CANCEL MODES ON SELECTION
 *************************************************/
canvas.on("selection:created", function () {
    addTextMode = false;
    addImageMode = false;
    addCircleImageMode = false;
});
canvas.on("selection:updated", function () {
    addTextMode = false;
    addImageMode = false;
    addCircleImageMode = false;
});

/*************************************************
 * PROPERTIES PANEL SYNC
 *************************************************/
function updatePropertiesPanel(o) {
    if (!o) return;

    document.getElementById("propName").value = o.customId || "";
    document.getElementById("propFontSize").value = o.fontSize || "";
    document.getElementById("propColor").value = o.fill || "#ffffff";
}

canvas.on("selection:created", () => updatePropertiesPanel(canvas.getActiveObject()));
canvas.on("selection:updated", () => updatePropertiesPanel(canvas.getActiveObject()));

/*************************************************
 * PROPERTY UPDATES
 *************************************************/
function updateName() {
    if (canvas.getActiveObject()) {
        canvas.getActiveObject().customId =
            document.getElementById("propName").value;

        refreshLayers();
    }
}

function updateFontSize() {
    const obj = canvas.getActiveObject();
    if (obj && obj.type === "textbox") {
        obj.set("fontSize", parseInt(document.getElementById("propFontSize").value));
        canvas.renderAll();
    }
}

function updateColor() {
    const obj = canvas.getActiveObject();
    if (obj) {
        obj.set("fill", document.getElementById("propColor").value);
        canvas.renderAll();
    }
}

/*************************************************
 * LAYERS PANEL
 *************************************************/
function refreshLayers() {
    const list = document.getElementById("layerList");
    list.innerHTML = "";

    canvas.getObjects().forEach(o => {
        const li = document.createElement("li");
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
 * SAVE TEMPLATE FIELDS TO BACKEND
 *************************************************/
function saveTemplate() {
    const objects = canvas.getObjects().map(o => ({
        field_name: o.customId,
        field_type: o.field_type,
        shape: o.shape,
        x: Math.round(o.left),
        y: Math.round(o.top),
        width: Math.round(o.getScaledWidth ? o.getScaledWidth() : o.width),
        height: Math.round(o.getScaledHeight ? o.getScaledHeight() : o.height),
        font_size: o.fontSize || null,
        color: o.fill || null
    }));

    fetch(`/admin/template/${TEMPLATE_ID}/builder`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields: objects })
    })
    .then(r => r.json())
    .then(res => {
        if (res.status === "ok") {
            alert("Template Saved!");
        } else {
            alert("Failed to save template.");
        }
    });
}


