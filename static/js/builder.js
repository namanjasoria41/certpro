/***********************************************
 * FABRIC.JS CANVA-STYLE TEMPLATE BUILDER
 ***********************************************/

let canvas = new fabric.Canvas("builderCanvas", {
    preserveObjectStacking: true,
    selection: true
});

let zoomLevel = 1;
let undoStack = [];
let redoStack = [];

let verticalGuide = null;
let horizontalGuide = null;
const snapTolerance = 6;

/***************************************
 * LOAD BACKGROUND
 ***************************************/
fabric.Image.fromURL(TEMPLATE_URL, function(img) {
    canvas.setWidth(img.width);
    canvas.setHeight(img.height);
    img.set({ selectable: false, evented: false });

    canvas.setBackgroundImage(img, canvas.renderAll.bind(canvas));
    loadExistingFields();
});

/***************************************
 * LOAD EXISTING FIELDS
 ***************************************/
function loadExistingFields() {
    EXISTING_FIELDS.forEach(f => {
        let obj;

        if (f.field_type === "text") {
            obj = new fabric.Textbox(f.field_name || f.name, {
                left: f.x,
                top: f.y,
                fontSize: f.font_size,
                fill: f.color,
                fontFamily: f.font_family,
                textAlign: f.align || "left",
            });
        }
        else if (f.field_type === "image") {
            obj = new fabric.Rect({
                left: f.x,
                top: f.y,
                width: f.width,
                height: f.height,
                fill: "rgba(255,255,255,0.25)",
                stroke: "#aaa",
            });
        }
        else {
            return;
        }

        obj.customId = f.field_name || f.name;
        canvas.add(obj);
    });

    canvas.renderAll();
    refreshLayerList();
}

/***************************************
 * TOOLBAR FUNCTIONS
 ***************************************/
function addText() {
    let text = new fabric.Textbox("New Field", {
        left: 60,
        top: 60,
        fontSize: 32,
        fill: "#ffffff",
        fontFamily: "Arial"
    });
    text.customId = "field_" + Date.now();
    canvas.add(text);
    canvas.setActiveObject(text);
    saveState();
    updateProperties();
}

function addRectangle() {
    let rect = new fabric.Rect({
        left: 80,
        top: 80,
        width: 200,
        height: 80,
        fill: "rgba(255,255,255,0.18)",
        stroke: "#fff"
    });
    rect.customId = "field_" + Date.now();
    canvas.add(rect);
    canvas.setActiveObject(rect);
    saveState();
    updateProperties();
}

function addCircle() {
    let circle = new fabric.Circle({
        left: 120,
        top: 120,
        radius: 60,
        fill: "rgba(255,255,255,0.18)",
        stroke: "#fff"
    });
    circle.customId = "field_" + Date.now();
    canvas.add(circle);
    canvas.setActiveObject(circle);
    saveState();
    updateProperties();
}

function triggerImageUpload() {
    document.getElementById("imageUploadInput").click();
}

document.getElementById("imageUploadInput").onchange = function(e) {
    let file = e.target.files[0];
    let reader = new FileReader();

    reader.onload = function(ev) {
        fabric.Image.fromURL(ev.target.result, function(img) {
            img.scaleToWidth(220);

            // CIRCLE MASK
            let circle = new fabric.Circle({
                radius: img.getScaledWidth() / 2,
                originX: "center",
                originY: "center"
            });
            img.clipPath = circle;

            img.customId = "field_" + Date.now();
            canvas.add(img);
            canvas.setActiveObject(img);
            canvas.renderAll();
            saveState();
            updateProperties();
        });
    };

    reader.readAsDataURL(file);
};

function deleteSelected() {
    let obj = canvas.getActiveObject();
    if (obj) {
        canvas.remove(obj);
        canvas.renderAll();
        saveState();
        refreshLayerList();
    }
}

/***************************************
 * PROPERTY PANEL UPDATES
 ***************************************/
canvas.on("selection:created", updateProperties);
canvas.on("selection:updated", updateProperties);

function updateProperties() {
    let o = canvas.getActiveObject();
    if (!o) return;

    document.getElementById("propName").value = o.customId || "";
    document.getElementById("propFontSize").value = o.fontSize || "";
    document.getElementById("propColor").value = o.fill || "#ffffff";
    document.getElementById("propFontFamily").value = o.fontFamily || "Arial";
    document.getElementById("propAlign").value = o.textAlign || "left";
}

function updateName() {
    let o = canvas.getActiveObject();
    if (o) {
        o.customId = document.getElementById("propName").value;
        refreshLayerList();
    }
}

function updateFontSize() {
    let o = canvas.getActiveObject();
    if (o && o.type === "textbox") {
        o.fontSize = parseInt(document.getElementById("propFontSize").value);
        canvas.renderAll();
        saveState();
    }
}

function updateColor() {
    let o = canvas.getActiveObject();
    if (o) {
        o.set({ fill: document.getElementById("propColor").value });
        canvas.renderAll();
        saveState();
    }
}

function updateFontFamily() {
    let o = canvas.getActiveObject();
    if (o && o.type === "textbox") {
        o.set({ fontFamily: document.getElementById("propFontFamily").value });
        canvas.renderAll();
        saveState();
    }
}

function updateAlign() {
    let o = canvas.getActiveObject();
    if (o && o.type === "textbox") {
        o.set({ textAlign: document.getElementById("propAlign").value });
        canvas.renderAll();
        saveState();
    }
}

/***************************************
 * SMART GUIDES (CANVA)
 ***************************************/
canvas.on("object:moving", function(e) {
    let o = e.target;

    let cx = o.left + o.getScaledWidth() / 2;
    let cy = o.top + o.getScaledHeight() / 2;

    let centerX = canvas.getWidth() / 2;
    let centerY = canvas.getHeight() / 2;

    // Snap vertical center
    if (Math.abs(cx - centerX) < snapTolerance) {
        o.left = centerX - o.getScaledWidth() / 2;
        drawVerticalGuide(centerX);
    } else clearVerticalGuide();

    // Snap horizontal center
    if (Math.abs(cy - centerY) < snapTolerance) {
        o.top = centerY - o.getScaledHeight() / 2;
        drawHorizontalGuide(centerY);
    } else clearHorizontalGuide();
});

function drawVerticalGuide(x) {
    if (!verticalGuide) {
        verticalGuide = new fabric.Line([x, 0, x, canvas.getHeight()], {
            stroke: "rgba(0,150,255,0.7)",
            strokeWidth: 1.5,
            selectable: false,
            evented: false
        });
        canvas.add(verticalGuide);
    }
}

function drawHorizontalGuide(y) {
    if (!horizontalGuide) {
        horizontalGuide = new fabric.Line([0, y, canvas.getWidth(), y], {
            stroke: "rgba(0,150,255,0.7)",
            strokeWidth: 1.5,
            selectable: false,
            evented: false
        });
        canvas.add(horizontalGuide);
    }
}

function clearVerticalGuide() {
    if (verticalGuide) {
        canvas.remove(verticalGuide);
        verticalGuide = null;
    }
}

function clearHorizontalGuide() {
    if (horizontalGuide) {
        canvas.remove(horizontalGuide);
        horizontalGuide = null;
    }
}


/***************************************
 * ZOOM CONTROLS
 ***************************************/
function zoomIn() {
    zoomLevel += 0.1;
    canvas.setZoom(zoomLevel);
    document.getElementById("zoomValue").innerText = Math.round(zoomLevel * 100) + "%";
}

function zoomOut() {
    zoomLevel = Math.max(0.2, zoomLevel - 0.1);
    canvas.setZoom(zoomLevel);
    document.getElementById("zoomValue").innerText = Math.round(zoomLevel * 100) + "%";
}


/***************************************
 * LAYER PANEL
 ***************************************/
function refreshLayerList() {
    let list = document.getElementById("layerList");
    list.innerHTML = "";

    canvas.getObjects().forEach(obj => {
        let li = document.createElement("li");
        li.innerText = obj.customId || "Unnamed";

        li.onclick = () => {
            canvas.setActiveObject(obj);
            canvas.renderAll();
            updateProperties();
        };

        list.appendChild(li);
    });
}

/***************************************
 * UNDO / REDO
 ***************************************/
function saveState() {
    undoStack.push(canvas.toJSON(["customId"]));
}

function undo() {
    if (!undoStack.length) return;
    let state = undoStack.pop();
    redoStack.push(canvas.toJSON(["customId"]));

    canvas.loadFromJSON(state, () => {
        canvas.renderAll();
        refreshLayerList();
    });
}

function redo() {
    if (!redoStack.length) return;
    let state = redoStack.pop();
    undoStack.push(canvas.toJSON(["customId"]));

    canvas.loadFromJSON(state, () => {
        canvas.renderAll();
        refreshLayerList();
    });
}

/***************************************
 * LOCK / UNLOCK / HIDE / SHOW
 ***************************************/
function lockSelected() {
    let obj = canvas.getActiveObject();
    if (!obj) return;

    obj.lockMovementX = true;
    obj.lockMovementY = true;
    obj.lockRotation = true;
    obj.lockScalingX = true;
    obj.lockScalingY = true;
}

function unlockSelected() {
    let obj = canvas.getActiveObject();
    if (!obj) return;

    obj.lockMovementX = false;
    obj.lockMovementY = false;
    obj.lockRotation = false;
    obj.lockScalingX = false;
    obj.lockScalingY = false;
}

function hideSelected() {
    let obj = canvas.getActiveObject();
    if (obj) {
        obj.visible = false;
        canvas.renderAll();
    }
}

function showAll() {
    canvas.getObjects().forEach(o => o.visible = true);
    canvas.renderAll();
}

/***************************************
 * SAVE TEMPLATE TO BACKEND
 ***************************************/
function saveTemplate() {
    let objs = canvas.getObjects().map((o, i) => ({
        field_name: o.customId || `field_${i+1}`,
        field_type:
            o.type === "textbox" ? "text" :
            o.type === "image"   ? "image" :
            "shape",

        x: Math.round(o.left),
        y: Math.round(o.top),

        width: o.getScaledWidth ? Math.round(o.getScaledWidth()) : null,
        height: o.getScaledHeight ? Math.round(o.getScaledHeight()) : null,

        font_size: o.fontSize || null,
        color: o.fill || null,
        font_family: o.fontFamily || null,
        align: o.textAlign || null,

        shape: o.type === "circle" ? "circle" :
               o.type === "rect"   ? "rect" : null
    }));

    fetch(`/admin/template/${TEMPLATE_ID}/builder`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields: objs })
    })
    .then(r => r.json())
    .then(res => {
        if (res.status === "ok") {
            alert("Template Saved!");
        } else {
            alert(res.message || "Failed to save");
        }
    });
}

