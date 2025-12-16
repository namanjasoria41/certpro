let canvas;
let activeObject = null;

/* ───────── INIT ───────── */
window.onload = () => {
  canvas = new fabric.Canvas("builderCanvas", {
    preserveObjectStacking: true,
    selection: true
  });

  fabric.Image.fromURL(TEMPLATE_URL, img => {
    canvas.setWidth(img.width);
    canvas.setHeight(img.height);
    img.selectable = false;
    img.evented = false;
    canvas.setBackgroundImage(img, canvas.renderAll.bind(canvas));
  });

  loadExistingFields();

  canvas.on("selection:created", e => selectObject(e.target));
  canvas.on("selection:updated", e => selectObject(e.target));
  canvas.on("selection:cleared", () => (activeObject = null));
};

/* ───────── LOAD FIELDS ───────── */
function loadExistingFields() {
  EXISTING_FIELDS.forEach(f => {
    if (f.field_type === "image") {
      const rect = new fabric.Rect({
        left: f.x,
        top: f.y,
        width: f.width || 120,
        height: f.height || 120,
        fill: "rgba(255,255,255,0.15)",
        stroke: "#3b82f6",
        strokeDashArray: [5, 5],
        objectType: "image",
        fieldName: f.field_name,
        shape: f.shape || "rect"
      });
      canvas.add(rect);
    } else {
      const text = new fabric.Textbox(f.field_name, {
        left: f.x,
        top: f.y,
        fontSize: f.font_size || 28,
        fill: f.color || "#ffffff",
        objectType: "text",
        fieldName: f.field_name
      });
      canvas.add(text);
    }
  });
}

/* ───────── ADD MODES ───────── */
function enableAddTextMode() {
  const text = new fabric.Textbox("Text", {
    left: canvas.width / 2,
    top: canvas.height / 2,
    fontSize: 28,
    fill: "#ffffff",
    objectType: "text",
    fieldName: "text_" + Date.now()
  });
  canvas.add(text).setActiveObject(text);
}

function enableAddImageMode() {
  const rect = new fabric.Rect({
    left: canvas.width / 2,
    top: canvas.height / 2,
    width: 140,
    height: 140,
    fill: "rgba(255,255,255,0.15)",
    stroke: "#22c55e",
    strokeDashArray: [6, 4],
    objectType: "image",
    shape: "rect",
    fieldName: "image_" + Date.now()
  });
  canvas.add(rect).setActiveObject(rect);
}

function enableAddCircleImageMode() {
  const circle = new fabric.Circle({
    left: canvas.width / 2,
    top: canvas.height / 2,
    radius: 70,
    fill: "rgba(255,255,255,0.15)",
    stroke: "#22c55e",
    strokeDashArray: [6, 4],
    objectType: "image",
    shape: "circle",
    fieldName: "image_" + Date.now()
  });
  canvas.add(circle).setActiveObject(circle);
}

/* ───────── SELECTION ───────── */
function selectObject(obj) {
  activeObject = obj;
  document.getElementById("propName").value = obj.fieldName || "";
  if (obj.fontSize) {
    document.getElementById("propFontSize").value = obj.fontSize;
  }
}

/* ───────── UPDATE PROPS ───────── */
function updateName() {
  if (activeObject) activeObject.fieldName = propName.value;
}

function updateFontSize() {
  if (activeObject?.fontSize) {
    activeObject.set("fontSize", parseInt(propFontSize.value));
    canvas.renderAll();
  }
}

function updateColor() {
  if (activeObject) {
    activeObject.set("fill", propColor.value);
    canvas.renderAll();
  }
}

/* ───────── DELETE FIELD ───────── */
function deleteSelectedField() {
  if (!activeObject) return alert("Select a field first");
  canvas.remove(activeObject);
  activeObject = null;
}

/* ───────── PANELS ───────── */
function toggleProperties() {
  const p = document.getElementById("propertiesPanel");
  p.style.display = p.style.display === "block" ? "none" : "block";
}

function toggleLayers() {
  const l = document.getElementById("layersPanel");
  l.style.display = l.style.display === "block" ? "none" : "block";
}

/* ───────── SAVE ───────── */
function saveTemplate() {
  const payload = canvas.getObjects().map(o => ({
    field_name: o.fieldName,
    field_type: o.objectType,
    x: Math.round(o.left),
    y: Math.round(o.top),
    width: o.width ? Math.round(o.width * o.scaleX) : null,
    height: o.height ? Math.round(o.height * o.scaleY) : null,
    font_size: o.fontSize || null,
    color: o.fill || null,
    shape: o.shape || null
  }));

  fetch(`/admin/template/${TEMPLATE_ID}/save-fields`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  }).then(() => alert("Template saved"));
}

