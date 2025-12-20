let canvas;
let activeObject = null;

window.onload = () => {
  canvas = new fabric.Canvas("builderCanvas", {
    preserveObjectStacking: true,
    selection: true
  });

  // Load template image at REAL size (no scaling)
  fabric.Image.fromURL(TEMPLATE_URL, img => {
    img.selectable = false;
    img.evented = false;

    canvas.setWidth(img.width);
    canvas.setHeight(img.height);

    canvas.setBackgroundImage(img, canvas.renderAll.bind(canvas), {
      scaleX: 1,
      scaleY: 1
    });
  });

  loadExistingFields();

  canvas.on("selection:created", e => activeObject = e.target);
  canvas.on("selection:updated", e => activeObject = e.target);
  canvas.on("selection:cleared", () => activeObject = null);
};

/* ======================
   LOAD EXISTING FIELDS
====================== */
function loadExistingFields() {
  EXISTING_FIELDS.forEach(f => {
    if (f.field_type === "image") {
      const rect = new fabric.Rect({
        left: f.x,
        top: f.y,
        width: f.width || 120,
        height: f.height || 120,
        fill: "rgba(255,255,255,0.15)",
        stroke: "#22c55e",
        strokeDashArray: [6, 4],
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
        fieldName: f.field_name,
        editable: false
      });
      canvas.add(text);
    }
  });
}

/* ======================
   ADD TEXT FIELD
====================== */
function enableAddTextMode() {
  const t = new fabric.Textbox("Text", {
    left: 100,
    top: 100,
    fontSize: 28,
    fill: "#ffffff",
    objectType: "text",
    fieldName: "text_" + Date.now()
  });
  canvas.add(t).setActiveObject(t);
}

/* ======================
   ADD IMAGE FIELD
====================== */
function enableAddImageMode(circle = false) {
  const obj = circle
    ? new fabric.Circle({
        radius: 60,
        fill: "rgba(255,255,255,0.15)",
        stroke: "#22c55e",
        strokeDashArray: [6, 4]
      })
    : new fabric.Rect({
        width: 120,
        height: 120,
        fill: "rgba(255,255,255,0.15)",
        stroke: "#22c55e",
        strokeDashArray: [6, 4]
      });

  obj.left = 120;
  obj.top = 120;
  obj.objectType = "image";
  obj.shape = circle ? "circle" : "rect";
  obj.fieldName = "image_" + Date.now();

  canvas.add(obj).setActiveObject(obj);
}

/* ======================
   SAVE TEMPLATE FIELDS
====================== */
function saveTemplate() {
  const payload = {
    fields: canvas.getObjects().map(o => ({
      field_name: o.fieldName,
      field_type: o.objectType,
      x: Math.round(o.left),
      y: Math.round(o.top),
      width: o.width ? Math.round(o.width * o.scaleX) : null,
      height: o.height ? Math.round(o.height * o.scaleY) : null,
      font_size: o.fontSize || null,
      color: o.fill || null,
      shape: o.shape || null
    }))
  };

  fetch(`/admin/template/${TEMPLATE_ID}/builder`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  })
    .then(r => r.json())
    .then(() => alert("Template saved successfully"));
}


