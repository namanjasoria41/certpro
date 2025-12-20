let canvas;
let selectedObject = null;

/* INIT */
window.addEventListener("load", () => {
  const bg = document.getElementById("templateBg");

  bg.onload = () => {
    canvas = new fabric.Canvas("builderCanvas", {
      preserveObjectStacking: true
    });

    canvas.setWidth(bg.naturalWidth);
    canvas.setHeight(bg.naturalHeight);

    document.getElementById("builderCanvas").style.width = bg.clientWidth + "px";
    document.getElementById("builderCanvas").style.height = bg.clientHeight + "px";

    loadExistingFields();

    canvas.on("selection:created", e => selectObject(e.selected[0]));
    canvas.on("selection:updated", e => selectObject(e.selected[0]));
    canvas.on("selection:cleared", () => selectObject(null));
  };
});

/* LOAD */
function loadExistingFields() {
  EXISTING_FIELDS.forEach(f => {
    let obj;

    if (f.field_type === "text") {
      obj = new fabric.Textbox("Text", {
        left: f.x,
        top: f.y,
        fontSize: f.font_size || 28,
        fill: f.color || "#ffffff",
        name: f.field_name
      });
    } else {
      obj = new fabric.Rect({
        left: f.x,
        top: f.y,
        width: f.width || 140,
        height: f.height || 80,
        fill: "rgba(255,255,255,0.2)",
        stroke: "#00ffd5",
        strokeDashArray: [6,6],
        name: f.field_name
      });
    }

    canvas.add(obj);
  });

  canvas.renderAll();
}

/* ADD */
function enableAddTextMode() {
  const t = new fabric.Textbox("Text", {
    left: 100,
    top: 100,
    fontSize: 30,
    fill: "#ffffff",
    name: "text"
  });
  canvas.add(t).setActiveObject(t);
}

function enableAddImageMode() {
  const r = new fabric.Rect({
    left: 100,
    top: 100,
    width: 140,
    height: 80,
    fill: "rgba(255,255,255,0.2)",
    stroke: "#00ffd5",
    strokeDashArray: [6,6],
    name: "image"
  });
  canvas.add(r).setActiveObject(r);
}

/* PROPS */
function selectObject(obj) {
  selectedObject = obj;
  if (!obj) return;

  document.getElementById("propName").value = obj.name || "";
  document.getElementById("propFontSize").value = obj.fontSize || "";
  document.getElementById("propColor").value = obj.fill || "#ffffff";
}

function updateName() {
  if (selectedObject) selectedObject.name = propName.value;
}

function updateFontSize() {
  if (selectedObject?.fontSize) {
    selectedObject.set("fontSize", parseInt(propFontSize.value));
    canvas.renderAll();
  }
}

function updateColor() {
  if (selectedObject) {
    selectedObject.set("fill", propColor.value);
    canvas.renderAll();
  }
}

function deleteSelectedField() {
  if (selectedObject) {
    canvas.remove(selectedObject);
    selectedObject = null;
  }
}

/* PANELS */
function toggleProperties() {
  document.getElementById("propertiesPanel").classList.toggle("open");
}

function toggleLayers() {
  document.getElementById("layersPanel").classList.toggle("open");
}

/* SAVE */
function saveTemplate() {
  const payload = canvas.getObjects().map(o => ({
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
    body: JSON.stringify({ fields: payload })
  }).then(() => alert("Saved"));
}


