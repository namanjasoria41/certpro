// ---------------------------------------------
// FABRIC.JS CANVA BUILDER ENGINE
// ---------------------------------------------

let canvas = new fabric.Canvas("builderCanvas", {
    preserveObjectStacking: true,
    selection: true
});

let zoomLevel = 1;


// ---------------------------------------------
// LOAD BACKGROUND TEMPLATE
// ---------------------------------------------
fabric.Image.fromURL(TEMPLATE_URL, function(img) {
    canvas.setWidth(img.width);
    canvas.setHeight(img.height);

    img.set({ selectable: false });
    canvas.setBackgroundImage(img, canvas.renderAll.bind(canvas));

    loadExistingFields();
});


// ---------------------------------------------
// LOAD EXISTING FIELDS FROM DATABASE
// ---------------------------------------------
function loadExistingFields() {
    EXISTING_FIELDS.forEach(f => {
        if (f.field_type === "text") {
            let textObj = new fabric.Textbox(f.field_name || f.name, {
                left: f.x,
                top: f.y,
                fontSize: f.font_size,
                fill: f.color,
                fontFamily: f.font_family,
                textAlign: f.align || "left",
            });

            textObj.customId = f.field_name || f.name;

            canvas.add(textObj);
        }

        else if (f.field_type === "image") {
            let box = new fabric.Rect({
                left: f.x,
                top: f.y,
                width: f.width || 120,
                height: f.height || 120,
                fill: "rgba(255,255,255,0.2)",
                stroke: "#888",
            });

            box.customId = f.field_name || f.name;
            canvas.add(box);
        }
    });

    canvas.renderAll();
}


// ---------------------------------------------
// TOOLBAR ACTIONS
// ---------------------------------------------

function addText() {
    let text = new fabric.Textbox("New Field", {
        left: 50,
        top: 50,
        fontSize: 32,
        fill: "#ffffff",
        fontFamily: "Arial",
        textAlign: "left"
    });

    text.customId = "field_" + Date.now();

    canvas.add(text);
    canvas.setActiveObject(text);

    updateProperties();
}

function addRectangle() {
    let rect = new fabric.Rect({
        left: 80,
        top: 80,
        width: 200,
        height: 100,
        fill: "rgba(255,255,255,0.2)",
        stroke: "#fff"
    });

    rect.customId = "field_" + Date.now();

    canvas.add(rect);
    canvas.setActiveObject(rect);

    updateProperties();
}

function addCircle() {
    let circle = new fabric.Circle({
        left: 120,
        top: 120,
        radius: 70,
        fill: "rgba(255,255,255,0.2)",
        stroke: "#fff"
    });

    circle.customId = "field_" + Date.now();

    canvas.add(circle);
    canvas.setActiveObject(circle);

    updateProperties();
}

function triggerImageUpload() {
    document.getElementById("imageUploadInput").click();
}

document.getElementById("imageUploadInput").addEventListener("change", function(e) {
    let file = e.target.files[0];
    let reader = new FileReader();

    reader.onload = function(event) {
        fabric.Image.fromURL(event.target.result, function(img) {
            img.scaleToWidth(200);
            img.customId = "field_" + Date.now();

            canvas.add(img);
            canvas.setActiveObject(img);
            canvas.renderAll();
            updateProperties();
        });
    };

    reader.readAsDataURL(file);
});

function deleteSelected() {
    let obj = canvas.getActiveObject();
    if (obj) {
        canvas.remove(obj);
        canvas.renderAll();
    }
}


// ---------------------------------------------
// PROPERTY PANEL BINDINGS
// ---------------------------------------------

canvas.on("selection:created", updateProperties);
canvas.on("selection:updated", updateProperties);
canvas.on("selection:cleared", clearProperties);

function updateProperties() {
    let obj = canvas.getActiveObject();
    if (!obj) return;

    document.getElementById("propName").value = obj.customId || "";
    document.getElementById("propFontSize").value = obj.fontSize || "";
    document.getElementById("propColor").value = obj.fill || "#ffffff";
    document.getElementById("propFontFamily").value = obj.fontFamily || "Arial";
    document.getElementById("propAlign").value = obj.textAlign || "left";
}

function clearProperties() {
    document.getElementById("propName").value = "";
}

function updateName() {
    let obj = canvas.getActiveObject();
    if (!obj) return;

    obj.customId = document.getElementById("propName").value;
}

function updateFontSize() {
    let obj = canvas.getActiveObject();
    if (obj && obj.type === "textbox") {
        obj.fontSize = parseInt(document.getElementById("propFontSize").value);
        canvas.renderAll();
    }
}

function updateColor() {
    let obj = canvas.getActiveObject();
    if (obj) {
        obj.set({ fill: document.getElementById("propColor").value });
        canvas.renderAll();
    }
}

function updateFontFamily() {
    let obj = canvas.getActiveObject();
    if (obj && obj.type === "textbox") {
        obj.set({ fontFamily: document.getElementById("propFontFamily").value });
        canvas.renderAll();
    }
}

function updateAlign() {
    let obj = canvas.getActiveObject();
    if (obj && obj.type === "textbox") {
        obj.set({ textAlign: document.getElementById("propAlign").value });
        canvas.renderAll();
    }
}


// ---------------------------------------------
// ZOOM CONTROLS
// ---------------------------------------------
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


// ---------------------------------------------
// SAVE TEMPLATE (MATCHES YOUR BACKEND EXACTLY)
// ---------------------------------------------
function saveTemplate() {
    let objs = canvas.getObjects().map((o, index) => ({
        field_name: o.customId || `field_${index+1}`,
        field_type: o.type === "textbox"
            ? "text"
            : (o.type === "image" ? "image" : "shape"),

        x: Math.round(o.left),
        y: Math.round(o.top),

        width: o.getScaledWidth ? Math.round(o.getScaledWidth()) : null,
        height: o.getScaledHeight ? Math.round(o.getScaledHeight()) : null,

        font_size: o.fontSize || null,
        color: o.fill || null,
        font_family: o.fontFamily || null,
        align: o.textAlign || null,

        shape: (o.type === "circle" ? "circle" : (o.type === "rect" ? "rect" : null))
    }));

    fetch(`/admin/template/${TEMPLATE_ID}/builder`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ fields: objs })     // FIXED STRUCTURE
    })
    .then(r => r.json())
    .then(res => {
        if (res.status === "ok") {
            alert("Template Saved!");
        } else {
            alert(res.message || "Failed to save template");
        }
    });
}
