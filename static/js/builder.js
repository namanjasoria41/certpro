let canvas;
let selectedObject = null;

window.addEventListener("load", () => {
  canvas = new fabric.Canvas("builderCanvas", {
    selection: true,
    preserveObjectStacking: true
  });

  fabric.Image.fromURL(TEMPLATE_URL, img => {
    canvas.setWidth(img.width);
    canvas.setHeight(img.height);
    canvas.setBackgroundImage(img, canvas.renderAll.bind(canvas));
  });

  EXISTING_FIELDS.forEach(f => {
    if (f.field_type === "text") {
      const t = new fabric.Textbox("Sample", {
        left: f.x,
        top: f.y,
        fontSize: f.font_size,
        fill: f.color,
        name: f.field_name,
        selectable: true,
        evented: true
      });
      canvas.add(t);
    }
  });

  canvas.on("selection:created", e => selectObject(e.selected[0]));
  canvas.on("selection:updated", e => selectObject(e.selected[0]));
  canvas.on("selection:cleared", () => selectedObject = null);
});

function selectObject(obj) {
  selectedObject = obj;
  document.getElementById("propName").value = obj.name || "";
  document.getElementById("propFontSize").value = obj.fontSize || 24;
  document.getElementById("propColor").value = obj.fill || "#ffffff";
}

function enableAddTextMode() {
  const t = new fabric.Textbox("Text", {
    left: 100,
    top: 100,
    fontSize: 28,
    fill: "#ffffff",
    name: "text_" + Date.now(),
    selectable: true,
    evented: true
  });
  canvas.add(t).setActiveObject(t);
}

function enableAddImageMode() {
  const r = new fabric.Rect({
    left: 120,
    top: 120,
    width: 140,
    height: 140,
    fill: "rgba(255,255,255,0.15)",
    stroke: "#00ffd5",
    strokeDashArray: [6,6],
    name: "image_" + Date.now(),
    selectable: true,
    evented: true
  });
  canvas.add(r).setActiveObject(r);
}

function enableAddCircleImageMode() {
  const c = new fabric.Circle({
    left: 140,
    top: 140,
    radius: 70,
    fill: "rgba(255,255,255,0.15)",
    stroke: "#00ffd5",
    strokeDashArray: [6,6],
    name: "circle_" + Date.now(),
    selectable: true,
    evented: true
  });
  canvas.add(c).setActiveObject(c);
}

function updateName() {
  if (selectedObject)
    selectedObject.name = document.getElementById("propName").value;
}

function updateFontSize() {
  if (selectedObject)
    selectedObject.set("fontSize", parseInt(propFontSize.value));
  canvas.renderAll();
}

function updateColor() {
  if (selectedObject)
    selectedObject.set("fill", propColor.value);
  canvas.renderAll();
}

function toggleProperties() {
  document.getElementById("propertiesPanel").classList.toggle("open");
}

function toggleLayers() {
  document.getElementById("layersPanel").classList.toggle("open");
}

function deleteSelectedField() {
  if (!selectedObject) return;
  canvas.remove(selectedObject);
  selectedObject = null;
}

function saveTemplate() {
  const fields = canvas.getObjects().map(o => ({
    field_name: o.name,
    x: o.left,
    y: o.top,
    font_size: o.fontSize || 24,
    color: o.fill || "#fff",
    field_type: o.type === "textbox" ? "text" : "image"
  }));

  fetch(`/admin/template/${TEMPLATE_ID}/builder`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fields })
  }).then(() => alert("Saved"));
}

