// ========================================
// GLOBAL VARIABLES
// ========================================

let canvas;
let selected = null;
let undoStack = [];
let redoStack = [];
let zoomLevel = 1;
let fieldCounter = 0;

// ========================================
// INITIALIZATION
// ========================================

window.onload = () => {
  initializeCanvas();
  setupKeyboardShortcuts();
  updateFieldList();
};

function initializeCanvas() {
  canvas = new fabric.Canvas("builderCanvas", {
    preserveObjectStacking: true,
    selection: true,
  });

  // Load template background image
  fabric.Image.fromURL(TEMPLATE_IMAGE, (img) => {
    canvas.setWidth(img.width);
    canvas.setHeight(img.height);
    canvas.setBackgroundImage(img, canvas.renderAll.bind(canvas));
    
    // Load existing fields
    loadExistingFields();
  });

  // Canvas event listeners
  canvas.on("selection:created", handleSelection);
  canvas.on("selection:updated", handleSelection);
  canvas.on("selection:cleared", clearSelection);
  canvas.on("object:modified", saveState);
  canvas.on("object:added", () => {
    updateFieldList();
    updateFieldCount();
  });
  canvas.on("object:removed", () => {
    updateFieldList();
    updateFieldCount();
  });
}

// ========================================
// LOAD EXISTING FIELDS
// ========================================

function loadExistingFields() {
  EXISTING_FIELDS.forEach((field) => {
    const fieldType = field.field_type || "text";
    
    if (fieldType === "text") {
      createTextField(field);
    } else if (fieldType === "image") {
      createImageField(field);
    }
  });
  
  canvas.renderAll();
  updateFieldList();
  updateFieldCount();
}

function createTextField(config = {}) {
  const text = new fabric.Textbox(config.text || "Sample Text", {
    left: config.x || canvas.width / 2 - 75,
    top: config.y || canvas.height / 2 - 20,
    fontSize: config.font_size || 32,
    fill: config.color || "#ffffff",
    fontFamily: getFontFamily(config.font_family || "default"),
    textAlign: config.align || "left",
    width: 200,
  });
  
  text.fieldData = {
    name: config.name || config.field_name || `text_${++fieldCounter}`,
    type: "text",
    align: config.align || "left",
    font_family: config.font_family || "default",
  };
  
  canvas.add(text);
  canvas.setActiveObject(text);
  saveState();
  return text;
}

function createImageField(config = {}) {
  const width = config.width || 150;
  const height = config.height || 150;
  const shape = config.shape || "rect";
  
  let placeholder;
  
  if (shape === "circle") {
    const radius = Math.min(width, height) / 2;
    placeholder = new fabric.Circle({
      left: config.x || canvas.width / 2 - radius,
      top: config.y || canvas.height / 2 - radius,
      radius: radius,
      fill: "rgba(255, 255, 255, 0.15)",
      stroke: "#00ffd5",
      strokeWidth: 2,
      strokeDashArray: [8, 4],
    });
  } else {
    placeholder = new fabric.Rect({
      left: config.x || canvas.width / 2 - width / 2,
      top: config.y || canvas.height / 2 - height / 2,
      width: width,
      height: height,
      fill: "rgba(255, 255, 255, 0.15)",
      stroke: "#00ffd5",
      strokeWidth: 2,
      strokeDashArray: [8, 4],
    });
  }
  
  placeholder.fieldData = {
    name: config.name || config.field_name || `image_${++fieldCounter}`,
    type: "image",
    shape: shape,
  };
  
  canvas.add(placeholder);
  canvas.setActiveObject(placeholder);
  saveState();
  return placeholder;
}

// ========================================
// FONT FAMILY MAPPING
// ========================================

function getFontFamily(token) {
  const fontMap = {
    default: "Arial, sans-serif",
    roboto: "Roboto, sans-serif",
    inter: "Inter, sans-serif",
    open_sans: "Open Sans, sans-serif",
    noto_sans: "Noto Sans, sans-serif",
    times: "Times New Roman, serif",
  };
  return fontMap[token] || fontMap.default;
}

// ========================================
// ADD FIELD FUNCTIONS
// ========================================

function addText() {
  createTextField();
}

function addImagePlaceholder() {
  createImageField();
}

// ========================================
// SELECTION HANDLING
// ========================================

function handleSelection(e) {
  selected = e.selected ? e.selected[0] : e.target;
  showProperties();
}

function clearSelection() {
  selected = null;
  hideProperties();
}

function showProperties() {
  if (!selected || !selected.fieldData) return;
  
  const propertiesContent = document.getElementById("propertiesContent");
  
  if (selected.fieldData.type === "text") {
    showTextProperties();
  } else if (selected.fieldData.type === "image") {
    showImageProperties();
  }
  
  updateFieldListSelection();
}

function hideProperties() {
  const propertiesContent = document.getElementById("propertiesContent");
  propertiesContent.innerHTML = `
    <div class="no-selection">
      <i class="bi bi-cursor"></i>
      <p>Select a field to edit properties</p>
    </div>
  `;
  updateFieldListSelection();
}

function showTextProperties() {
  const template = document.getElementById("textPropertiesTemplate");
  const propertiesContent = document.getElementById("propertiesContent");
  propertiesContent.innerHTML = template.innerHTML;
  
  // Populate values
  document.getElementById("propFieldName").value = selected.fieldData.name || "";
  document.getElementById("propTextContent").value = selected.text || "";
  document.getElementById("propFontSize").value = selected.fontSize || 32;
  document.getElementById("propColor").value = rgbToHex(selected.fill) || "#ffffff";
  document.getElementById("propFontFamily").value = selected.fieldData.font_family || "default";
  document.getElementById("propX").value = Math.round(selected.left);
  document.getElementById("propY").value = Math.round(selected.top);
  
  // Set alignment buttons
  const align = selected.fieldData.align || selected.textAlign || "left";
  document.querySelectorAll(".btn-toggle[data-align]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.align === align);
  });
  
  // Add event listeners
  document.getElementById("propFieldName").addEventListener("input", updateFieldName);
  document.getElementById("propTextContent").addEventListener("input", updateTextContent);
  document.getElementById("propFontSize").addEventListener("input", updateFontSize);
  document.getElementById("propColor").addEventListener("input", updateColor);
  document.getElementById("propFontFamily").addEventListener("change", updateFontFamily);
  document.getElementById("propX").addEventListener("input", updatePosition);
  document.getElementById("propY").addEventListener("input", updatePosition);
}

function showImageProperties() {
  const template = document.getElementById("imagePropertiesTemplate");
  const propertiesContent = document.getElementById("propertiesContent");
  propertiesContent.innerHTML = template.innerHTML;
  
  // Populate values
  document.getElementById("propFieldNameImg").value = selected.fieldData.name || "";
  
  if (selected.type === "circle") {
    document.getElementById("propWidth").value = Math.round(selected.radius * 2);
    document.getElementById("propHeight").value = Math.round(selected.radius * 2);
  } else {
    document.getElementById("propWidth").value = Math.round(selected.width * selected.scaleX);
    document.getElementById("propHeight").value = Math.round(selected.height * selected.scaleY);
  }
  
  document.getElementById("propXImg").value = Math.round(selected.left);
  document.getElementById("propYImg").value = Math.round(selected.top);
  
  // Set shape buttons
  const shape = selected.fieldData.shape || "rect";
  document.querySelectorAll(".btn-toggle[data-shape]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.shape === shape);
  });
  
  // Add event listeners
  document.getElementById("propFieldNameImg").addEventListener("input", updateFieldName);
  document.getElementById("propWidth").addEventListener("input", updateImageSize);
  document.getElementById("propHeight").addEventListener("input", updateImageSize);
  document.getElementById("propXImg").addEventListener("input", updatePosition);
  document.getElementById("propYImg").addEventListener("input", updatePosition);
}

// ========================================
// PROPERTY UPDATE FUNCTIONS
// ========================================

function updateFieldName(e) {
  if (!selected) return;
  selected.fieldData.name = e.target.value;
  updateFieldList();
  saveState();
}

function updateTextContent(e) {
  if (!selected || selected.fieldData.type !== "text") return;
  selected.set("text", e.target.value);
  canvas.renderAll();
  saveState();
}

function updateFontSize(e) {
  if (!selected || selected.fieldData.type !== "text") return;
  selected.set("fontSize", parseInt(e.target.value) || 32);
  canvas.renderAll();
  saveState();
}

function updateColor(e) {
  if (!selected || selected.fieldData.type !== "text") return;
  selected.set("fill", e.target.value);
  canvas.renderAll();
  saveState();
}

function updateFontFamily(e) {
  if (!selected || selected.fieldData.type !== "text") return;
  const token = e.target.value;
  selected.fieldData.font_family = token;
  selected.set("fontFamily", getFontFamily(token));
  canvas.renderAll();
  saveState();
}

function setAlignment(align) {
  if (!selected || selected.fieldData.type !== "text") return;
  selected.set("textAlign", align);
  selected.fieldData.align = align;
  
  // Update button states
  document.querySelectorAll(".btn-toggle[data-align]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.align === align);
  });
  
  canvas.renderAll();
  saveState();
}

function updateImageSize(e) {
  if (!selected || selected.fieldData.type !== "image") return;
  
  const width = parseInt(document.getElementById("propWidth").value) || 150;
  const height = parseInt(document.getElementById("propHeight").value) || 150;
  
  if (selected.type === "circle") {
    const radius = Math.min(width, height) / 2;
    selected.set({ radius: radius });
  } else {
    selected.set({
      width: width,
      height: height,
      scaleX: 1,
      scaleY: 1,
    });
  }
  
  canvas.renderAll();
  saveState();
}

function setShape(shape) {
  if (!selected || selected.fieldData.type !== "image") return;
  
  const oldObj = selected;
  const config = {
    name: oldObj.fieldData.name,
    x: oldObj.left,
    y: oldObj.top,
    width: oldObj.type === "circle" ? oldObj.radius * 2 : oldObj.width * oldObj.scaleX,
    height: oldObj.type === "circle" ? oldObj.radius * 2 : oldObj.height * oldObj.scaleY,
    shape: shape,
  };
  
  canvas.remove(oldObj);
  createImageField(config);
  
  // Update button states
  document.querySelectorAll(".btn-toggle[data-shape]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.shape === shape);
  });
}

function updatePosition(e) {
  if (!selected) return;
  
  const xInput = selected.fieldData.type === "text" 
    ? document.getElementById("propX") 
    : document.getElementById("propXImg");
  const yInput = selected.fieldData.type === "text" 
    ? document.getElementById("propY") 
    : document.getElementById("propYImg");
  
  selected.set({
    left: parseInt(xInput.value) || 0,
    top: parseInt(yInput.value) || 0,
  });
  
  canvas.renderAll();
  saveState();
}

// ========================================
// FIELD LIST MANAGEMENT
// ========================================

function updateFieldList() {
  const fieldList = document.getElementById("fieldList");
  const objects = canvas.getObjects().filter((obj) => obj.fieldData);
  
  if (objects.length === 0) {
    fieldList.innerHTML = `
      <div style="text-align: center; color: #a8a8c7; padding: 20px; font-size: 13px;">
        No fields yet. Add text or image fields to get started.
      </div>
    `;
    return;
  }
  
  fieldList.innerHTML = objects
    .map((obj, index) => {
      const icon = obj.fieldData.type === "text" ? "bi-fonts" : "bi-image";
      const name = obj.fieldData.name || `Field ${index + 1}`;
      const type = obj.fieldData.type;
      
      return `
        <div class="field-item" onclick="selectFieldByIndex(${index})">
          <i class="bi ${icon}"></i>
          <span class="field-item-name">${name}</span>
          <span class="field-item-type">${type}</span>
        </div>
      `;
    })
    .join("");
}

function updateFieldListSelection() {
  const items = document.querySelectorAll(".field-item");
  const objects = canvas.getObjects().filter((obj) => obj.fieldData);
  
  items.forEach((item, index) => {
    item.classList.toggle("active", objects[index] === selected);
  });
}

function selectFieldByIndex(index) {
  const objects = canvas.getObjects().filter((obj) => obj.fieldData);
  if (objects[index]) {
    canvas.setActiveObject(objects[index]);
    canvas.renderAll();
  }
}

function updateFieldCount() {
  const count = canvas.getObjects().filter((obj) => obj.fieldData).length;
  document.getElementById("fieldCount").textContent = count;
}

// ========================================
// FIELD ACTIONS
// ========================================

function duplicateField() {
  if (!selected || !selected.fieldData) return;
  
  const config = {
    name: selected.fieldData.name + "_copy",
    x: selected.left + 20,
    y: selected.top + 20,
  };
  
  if (selected.fieldData.type === "text") {
    config.text = selected.text;
    config.font_size = selected.fontSize;
    config.color = selected.fill;
    config.font_family = selected.fieldData.font_family;
    config.align = selected.fieldData.align;
    createTextField(config);
  } else {
    if (selected.type === "circle") {
      config.width = selected.radius * 2;
      config.height = selected.radius * 2;
    } else {
      config.width = selected.width * selected.scaleX;
      config.height = selected.height * selected.scaleY;
    }
    config.shape = selected.fieldData.shape;
    createImageField(config);
  }
}

function deleteField() {
  if (!selected) return;
  canvas.remove(selected);
  selected = null;
  hideProperties();
  saveState();
}

// ========================================
// UNDO/REDO FUNCTIONALITY
// ========================================

function saveState() {
  const state = JSON.stringify(canvas.toJSON(["fieldData"]));
  undoStack.push(state);
  redoStack = []; // Clear redo stack on new action
  
  // Limit undo stack to 50 states
  if (undoStack.length > 50) {
    undoStack.shift();
  }
}

function undo() {
  if (undoStack.length <= 1) return;
  
  const currentState = undoStack.pop();
  redoStack.push(currentState);
  
  const previousState = undoStack[undoStack.length - 1];
  loadState(previousState);
}

function redo() {
  if (redoStack.length === 0) return;
  
  const state = redoStack.pop();
  undoStack.push(state);
  loadState(state);
}

function loadState(state) {
  canvas.loadFromJSON(state, () => {
    canvas.renderAll();
    updateFieldList();
    updateFieldCount();
    clearSelection();
  });
}

// ========================================
// ZOOM CONTROLS
// ========================================

function zoomIn() {
  zoomLevel = Math.min(zoomLevel + 0.1, 2);
  applyZoom();
}

function zoomOut() {
  zoomLevel = Math.max(zoomLevel - 0.1, 0.3);
  applyZoom();
}

function resetZoom() {
  zoomLevel = 1;
  applyZoom();
}

function applyZoom() {
  canvas.setZoom(zoomLevel);
  document.getElementById("zoomLevel").textContent = Math.round(zoomLevel * 100) + "%";
}

// ========================================
// KEYBOARD SHORTCUTS
// ========================================

function setupKeyboardShortcuts() {
  document.addEventListener("keydown", (e) => {
    // Delete key
    if (e.key === "Delete" && selected) {
      deleteField();
    }
    
    // Ctrl+Z (Undo)
    if (e.ctrlKey && e.key === "z") {
      e.preventDefault();
      undo();
    }
    
    // Ctrl+Y (Redo)
    if (e.ctrlKey && e.key === "y") {
      e.preventDefault();
      redo();
    }
    
    // Ctrl+D (Duplicate)
    if (e.ctrlKey && e.key === "d") {
      e.preventDefault();
      duplicateField();
    }
    
    // Ctrl+S (Save)
    if (e.ctrlKey && e.key === "s") {
      e.preventDefault();
      saveTemplate();
    }
  });
}

// ========================================
// SAVE TEMPLATE
// ========================================

function saveTemplate() {
  const objects = canvas.getObjects().filter((obj) => obj.fieldData);
  
  const fields = objects.map((obj) => {
    const baseData = {
      field_name: obj.fieldData.name,
      name: obj.fieldData.name,
      field_type: obj.fieldData.type,
      x: Math.round(obj.left),
      y: Math.round(obj.top),
    };
    
    if (obj.fieldData.type === "text") {
      return {
        ...baseData,
        font_size: obj.fontSize || 32,
        color: obj.fill || "#ffffff",
        font_family: obj.fieldData.font_family || "default",
        align: obj.fieldData.align || obj.textAlign || "left",
      };
    } else {
      let width, height;
      if (obj.type === "circle") {
        width = Math.round(obj.radius * 2);
        height = Math.round(obj.radius * 2);
      } else {
        width = Math.round(obj.width * obj.scaleX);
        height = Math.round(obj.height * obj.scaleY);
      }
      
      return {
        ...baseData,
        width: width,
        height: height,
        shape: obj.fieldData.shape || "rect",
      };
    }
  });
  
  // Send to backend
  fetch(`/admin/template/${TEMPLATE_ID}/builder`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ fields: fields }),
  })
    .then((response) => response.json())
    .then((data) => {
      if (data.status === "ok") {
        showNotification("Template saved successfully!", "success");
      } else {
        showNotification("Error: " + (data.message || "Save failed"), "error");
      }
    })
    .catch((error) => {
      console.error("Save error:", error);
      showNotification("Network error. Please try again.", "error");
    });
}

// ========================================
// UTILITY FUNCTIONS
// ========================================

function rgbToHex(rgb) {
  if (!rgb) return "#ffffff";
  if (rgb.startsWith("#")) return rgb;
  
  const match = rgb.match(/^rgb\((\d+),\s*(\d+),\s*(\d+)\)$/);
  if (!match) return "#ffffff";
  
  const r = parseInt(match[1]);
  const g = parseInt(match[2]);
  const b = parseInt(match[3]);
  
  return "#" + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
}

function showNotification(message, type = "info") {
  // Create notification element
  const notification = document.createElement("div");
  notification.style.cssText = `
    position: fixed;
    top: 80px;
    right: 20px;
    padding: 16px 24px;
    background: ${type === "success" ? "rgba(0, 255, 213, 0.2)" : "rgba(255, 59, 59, 0.2)"};
    border: 1px solid ${type === "success" ? "#00ffd5" : "#ff3b3b"};
    color: ${type === "success" ? "#00ffd5" : "#ff3b3b"};
    border-radius: 12px;
    font-weight: 600;
    z-index: 10000;
    animation: slideIn 0.3s ease;
  `;
  notification.textContent = message;
  
  document.body.appendChild(notification);
  
  setTimeout(() => {
    notification.style.animation = "slideOut 0.3s ease";
    setTimeout(() => notification.remove(), 300);
  }, 3000);
}

// Add CSS animations
const style = document.createElement("style");
style.textContent = `
  @keyframes slideIn {
    from { transform: translateX(400px); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
  }
  @keyframes slideOut {
    from { transform: translateX(0); opacity: 1; }
    to { transform: translateX(400px); opacity: 0; }
  }
`;
document.head.appendChild(style);
