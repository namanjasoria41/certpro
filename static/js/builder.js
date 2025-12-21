let canvas;
let selected = null;

window.onload = () => {
  canvas = new fabric.Canvas("builderCanvas", {
    preserveObjectStacking: true
  });

  fabric.Image.fromURL(TEMPLATE_IMAGE, img => {
    canvas.setWidth(img.width);
    canvas.setHeight(img.height);

    canvas.setBackgroundImage(img, canvas.renderAll.bind(canvas));

    loadExisting();
  });

  canvas.on("selection:created", e => selected = e.selected[0]);
  canvas.on("selection:updated", e => selected = e.selected[0]);
  canvas.on("selection:cleared", () => selected = null);
};

function loadExisting() {
  EXISTING_FIELDS.forEach(f => {
    let obj;

    if (f.field_type === "text") {
      obj = new fabric.Textbox("Text", {
        left: f.x,
        top: f.y,
        fontSize: f.font_size || 30,
        fill: f.color || "#fff",
        name: f.field_name
      });
    } else {
      obj = new fabric.Rect({
        left: f.x,
        top: f.y,
        width: f.width || 150,
        height: f.height || 80,
        fill: "rgba(255,255,255,.2)",
        stroke: "#00ffd5",
        strokeDashArray: [6,6],
        name: f.field_name
      });
    }

    canvas.add(obj);
  });

  canvas.renderAll();
}

function addText() {
  const t = new fabric.Textbox("New Text", {
    left: canvas.width / 2 - 50,
    top: canvas.height / 2,
    fontSize: 32,
    fill: "#ffffff",
    name: "text"
  });
  canvas.add(t).setActiveObject(t);
}

function addRect() {
  const r = new fabric.Rect({
    left: canvas.width / 2 - 75,
    top: canvas.height / 2,
    width: 150,
    height: 80,
    fill: "rgba(255,255,255,.2)",
    stroke: "#00ffd5",
    strokeDashArray: [6,6],
    name: "image"
  });
  canvas.add(r).setActiveObject(r);
}

function updateName() {
  if (selected) selected.name = propName.value;
}

function updateFontSize() {
  if (selected?.fontSize) {
    selected.set("fontSize", parseInt(propFontSize.value));
    canvas.renderAll();
  }
}

function updateColor() {
  if (selected) {
    selected.set("fill", propColor.value);
    canvas.renderAll();
  }
}

function deleteSelected() {
  if (selected) {
    canvas.remove(selected);
    selected = null;
  }
}

function toggleProperties() {
  document.getElementById("propertiesPanel").classList.toggle("open");
}

function saveTemplate() {
  const data = canvas.getObjects().map(o => ({
    field_name: o.name,
    field_type: o.type === "textbox" ? "text" : "image",
    x: o.left,
    y: o.top,
    width: o.width * o.scaleX,
    height: o.height * o.scaleY,
    font_size: o.fontSize,
    color: o.fill
  }));

  fetch(`/admin/template/${TEMPLATE_ID}/save_fields`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fields: data })
  }).then(() => alert("Saved"));
}



