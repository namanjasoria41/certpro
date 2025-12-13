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
 * LOAD EXISTING FIELDS FROM DATABASE
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
                textAlign: f.align || "left"
            });
        }

        else if (f.field_type === "image") {
            if (f.shape === "circle") {
                obj = new fabric.Circle({
                    left: f.x,
                    top: f.y,
                    radius: f.width / 2,
                    fill: "rgba(255,255,255,0.15)",
                    stroke: "#00aaff",
                    strokeWidth: 2
                });
            } else {
                obj = new fabric.Rect({
                    left: f.x,
                    top: f.y,
                    width: f.width,
                    height: f.height,
                    fill: "rgba(255,255,255,0.15)",
                    stroke: "#00aaff",
                    strokeWidth: 2
                });
            }
        }

        obj.customId = f.field_name || f.name;
        obj.field_type = f.field_type;
        obj.shape = f.shape;

        canvas.add(obj);
    });

    canvas.renderAll();
    refreshLayerList();
}

/***************************************
 * TOOLBAR ACTIONS
 ***************************************/
function addText() {
    let t = new fabric.Textbox("New Field", {
        left: 60,
        top: 60,
        fontSize: 32,
        fill: "#ffffff"
    });

    t.customId = "field_" + Date.now();
    t.field_type = "text";

    canvas.add(t);
    canvas.setActiveObject(t);
    saveState();
    updateProperties();
}

function addRectangle() {
    let r = new fabric.Rect({
        left: 80,
        top: 80,
        width: 200,
        height: 80,
        fill: "rgba(255,255,255,0.15)",
        stroke: "#00aaff",
        strokeWidth: 2
    });

    r.customId = "field_" + Date.now();
    r.field_type = "shape";
    r.shape = "rect";

    canvas.add(r);
    canvas.setActiveObject(r);
    saveState();
}

function addCircle() {
    let c = new fabric.Circle({
        left: 120,
        top: 120,
        radius: 60,
        fill: "rgba(255,255,255,0.15)",
        stroke: "#00aaff",
        strokeWidth: 2
    });

    c.customId = "field_" + Date.now();
    c.field_type = "shape";
    c.shape = "circle";

    canvas.add(c);
    canvas.setActiveObject(c);
    saveState();
}

/*** IMAGE PLACEHOLDER (RECT) ***/
function addImagePlaceholder() {
    let frame = new fabric.Rect({
        left: 100,
        top: 100,
        width: 200,
        height: 200,
        fill: "rgba(255,255,255,0.15)",
        stroke: "#00aaff",
        strokeWidth: 2
    });

    frame.field_type = "image";
    frame.shape = "rect";
    frame.customId = "field_" + Date.now();

    canvas.add(frame);
    canvas.setActiveObject(frame);
    saveState();
}

/*** IMAGE PLACEHOLDER (CIRCLE) ***/
function addCirclePlaceholder() {
    let c = new fabric.Circle({
        left: 100,
        top: 100,
        radius: 80,
        fill: "rgba(255,255,255,0.15)",
        stroke: "#00aaff",
        strokeWidth: 2
    });

    c.field_type = "image";
    c.shape = "circle";
    c.customId = "field_" + Date.now();

    canvas.add(c);
    canvas.setActiveObject(c);
    saveState();
}

/***************************************
 * PROPERTY PANEL
 ***************************************/
canvas.on("selection:created", updateProperties);
canvas.on("selection:updated", updateProperties);

function updateProperties() {
    let o = canvas.getActiveObject();
    if (!o) return;

    document.getElementById("propName").value = o.customId || "";
    document.getElementById("propFontSize").value = o.fontSize || "";
    document.getElementById("propColor").value = o.fill || "#ffffff";
}

function updateName() {
    let o = canvas.getActiveObject();
    if (o) o.customId = document.getElementById("propName").value;
    refreshLayerList();
}

/***************************************
 * SMART GUIDES (CANVA-STYLE)
 ***************************************/
canvas.on("object:moving", function(e) {
    let o = e.target;
    let cx = o.left + o.getScaledWidth() / 2;
    let cy = o.top + o.getScaledHeight() / 2;

    let centerX = canvas.getWidth() / 2;
    let centerY = canvas.getHeight() / 2;

    if (Math.abs(cx - centerX) < snapTolerance) {
        o.left = centerX - o.getScaledWidth() / 2;
        drawVerticalGuide(centerX);
    } else clearVerticalGuide();

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
 * LAYER PANEL
 ***************************************/
function refreshLayerList() {
    let list = document.getElementById("layerList");
    list.innerHTML = "";

    canvas.getObjects().forEach(o => {
        let li = document.createElement("li");
        li.innerText = o.customId;

        li.onclick = () => {
            canvas.setActiveObject(o);
            updateProperties();
            canvas.renderAll();
        };

        list.appendChild(li);
    });
}

/***************************************
 * UNDO / REDO
 ***************************************/
function saveState() {
    undoStack.push(canvas.toJSON(["customId", "field_type", "shape"]));
}

function undo() {
    if (!undoStack.length) return;

    let state = undoStack.pop();
    redoStack.push(canvas.toJSON(["customId", "field_type", "shape"]));

    canvas.loadFromJSON(state, () => {
        canvas.renderAll();
        refreshLayerList();
    });
}

function redo() {
    if (!redoStack.length) return;

    let state = redoStack.pop();
    undoStack.push(canvas.toJSON(["customId", "field_type", "shape"]));

    canvas.loadFromJSON(state, () => {
        canvas.renderAll();
        refreshLayerList();
    });
}

/***************************************
 * SAVE TEMPLATE TO BACKEND
 ***************************************/
function saveTemplate() {
    let objs = canvas.getObjects().map((o, i) => ({
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
        align: o.textAlign || null
    }));

    fetch(`/admin/template/${TEMPLATE_ID}/builder`, {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({fields: objs})
    })
    .then(r => r.json())
    .then(res => {
        if (res.status === "ok") alert("Template saved!");
        else alert("Error saving template");
    });
}


