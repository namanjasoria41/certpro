/* =========================================================
   GLOBALS
========================================================= */

let canvas;
let selectedObject = null;

/* =========================================================
   INIT
========================================================= */

window.onload = () => {
    initCanvas();
    loadTemplateImage();
    loadExistingFields();
    bindSelectionEvents();
};

/* =========================================================
   CANVAS SETUP
========================================================= */

function initCanvas() {
    canvas = new fabric.Canvas("builderCanvas", {
        preserveObjectStacking: true,
        selection: true
    });

    canvas.setWidth(900);
    canvas.setHeight(600);
}

function loadTemplateImage() {
    fabric.Image.fromURL(TEMPLATE_URL, img => {
        img.set({
            selectable: false,
            evented: false,
            originX: "left",
            originY: "top"
        });

        canvas.setWidth(img.width);
        canvas.setHeight(img.height);
        canvas.setBackgroundImage(img, canvas.renderAll.bind(canvas));
    });
}

/* =========================================================
   LOAD EXISTING FIELDS
========================================================= */

function loadExistingFields() {
    if (!EXISTING_FIELDS || !Array.isArray(EXISTING_FIELDS)) return;

    EXISTING_FIELDS.forEach(f => {
        if (f.field_type === "image") {
            addImageField(
                f.x,
                f.y,
                f.width || 120,
                f.height || 120,
                f.shape || "rect",
                f.field_name
            );
        } else {
            addTextField(
                f.x,
                f.y,
                f.field_name,
                f.font_size || 24,
                f.color || "#000000"
            );
        }
    });

    canvas.renderAll();
    refreshLayerPanel();
}

/* =========================================================
   ADD FIELDS
========================================================= */

function enableAddTextMode() {
    addTextField(100, 100, "text_field");
}

function enableAddImageMode() {
    addImageField(100, 100, 140, 140, "rect", "image_field");
}

function enableAddCircleImageMode() {
    addImageField(100, 100, 140, 140, "circle", "image_field");
}

function addTextField(x, y, name, size = 24, color = "#000000") {
    const text = new fabric.Textbox("Text", {
        left: x,
        top: y,
        fontSize: size,
        fill: color,
        fontFamily: "Arial",
        editable: false,
        objectCaching: false
    });

    attachMeta(text, {
        field_type: "text",
        field_name: name
    });

    canvas.add(text);
    canvas.setActiveObject(text);
}

function addImageField(x, y, w, h, shape, name) {
    let obj;

    if (shape === "circle") {
        obj = new fabric.Circle({
            radius: w / 2,
            fill: "rgba(0,0,0,0.15)"
        });
    } else {
        obj = new fabric.Rect({
            width: w,
            height: h,
            fill: "rgba(0,0,0,0.15)"
        });
    }

    const group = new fabric.Group([obj], {
        left: x,
        top: y,
        lockRotation: true
    });

    attachMeta(group, {
        field_type: "image",
        field_name: name,
        shape: shape,
        width: w,
        height: h
    });

    canvas.add(group);
    canvas.setActiveObject(group);
}

/* =========================================================
   META HELPERS
========================================================= */

function attachMeta(obj, meta) {
    obj.meta = {
        field_name: meta.field_name || "field",
        field_type: meta.field_type || "text",
        shape: meta.shape || null
    };
}

/* =========================================================
   SELECTION + PROPERTIES
========================================================= */

function bindSelectionEvents() {
    canvas.on("selection:created", onSelect);
    canvas.on("selection:updated", onSelect);
    canvas.on("selection:cleared", () => {
        selectedObject = null;
    });
}

function onSelect(e) {
    selectedObject = e.selected[0];
    syncPropertiesPanel();
}

function syncPropertiesPanel() {
    if (!selectedObject || !selectedObject.meta) return;

    document.getElementById("propName").value =
        selectedObject.meta.field_name || "";

    if (selectedObject.meta.field_type === "text") {
        document.getElementById("propFontSize").value =
            selectedObject.fontSize || 24;

        document.getElementById("propColor").value =
            selectedObject.fill || "#000000";
    }
}

function updateName() {
    if (!selectedObject) return;
    selectedObject.meta.field_name =
        document.getElementById("propName").value;
    refreshLayerPanel();
}

function updateFontSize() {
    if (!selectedObject || selectedObject.meta.field_type !== "text") return;
    selectedObject.set("fontSize", parseInt(propFontSize.value));
    canvas.renderAll();
}

function updateColor() {
    if (!selectedObject || selectedObject.meta.field_type !== "text") return;
    selectedObject.set("fill", propColor.value);
    canvas.renderAll();
}

/* =========================================================
   DELETE FIELD
========================================================= */

function deleteSelectedField() {
    if (!selectedObject) return;

    canvas.remove(selectedObject);
    selectedObject = null;
    refreshLayerPanel();
}

/* =========================================================
   LAYERS PANEL
========================================================= */

function refreshLayerPanel() {
    const list = document.getElementById("layerList");
    list.innerHTML = "";

    canvas.getObjects().forEach((obj, i) => {
        if (!obj.meta) return;

        const li = document.createElement("li");
        li.innerHTML = `
            <span>${obj.meta.field_name}</span>
            <i class="bi bi-trash" style="cursor:pointer"></i>
        `;

        li.onclick = () => {
            canvas.setActiveObject(obj);
            canvas.renderAll();
        };

        li.querySelector("i").onclick = e => {
            e.stopPropagation();
            canvas.remove(obj);
            refreshLayerPanel();
        };

        list.appendChild(li);
    });
}

/* =========================================================
   DRAWER TOGGLES
========================================================= */

function toggleProperties() {
    document.getElementById("propertiesPanel").classList.toggle("open");
}

function toggleLayers() {
    document.getElementById("layersPanel").classList.toggle("open");
}

/* =========================================================
   SAVE TO BACKEND
========================================================= */

function saveTemplate() {
    const fields = [];

    canvas.getObjects().forEach(obj => {
        if (!obj.meta) return;

        const base = {
            field_name: obj.meta.field_name,
            field_type: obj.meta.field_type,
            x: Math.round(obj.left),
            y: Math.round(obj.top)
        };

        if (obj.meta.field_type === "text") {
            base.font_size = obj.fontSize;
            base.color = obj.fill;
        }

        if (obj.meta.field_type === "image") {
            base.shape = obj.meta.shape;
            base.width = Math.round(obj.width * obj.scaleX);
            base.height = Math.round(obj.height * obj.scaleY);
        }

        fields.push(base);
    });

    fetch(`/admin/template/${TEMPLATE_ID}/builder`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields })
    })
        .then(res => res.json())
        .then(res => {
            if (res.status === "ok") {
                alert("Template saved successfully");
            } else {
                alert("Save failed");
            }
        })
        .catch(() => alert("Server error"));
}
