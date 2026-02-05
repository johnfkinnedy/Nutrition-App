from flask import Blueprint, render_template_string, request, redirect, url_for, session, jsonify
from werkzeug.utils import secure_filename
from PIL import Image
import json
import uuid
from pathlib import Path

import torch
import torch.nn as nn
from torchvision import models, transforms


food_bp = Blueprint("food", __name__, url_prefix="/food")

# --------- Model files ----------
BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "food_model_out"
WEIGHTS_PATH = MODEL_DIR / "best_model.pt"
IDX_TO_CLASS_PATH = MODEL_DIR / "idx_to_class.json"

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# --------- Upload dir for persisted previews ----------
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = STATIC_DIR / "food_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

# --------- Load class mapping ----------
with open(IDX_TO_CLASS_PATH, "r") as f:
    idx_to_class = json.load(f)
idx_to_class = {int(k): v for k, v in idx_to_class.items()}
class_names = sorted(set(idx_to_class.values()))
num_classes = len(idx_to_class)

print(f"[FOOD_ML] Loaded {num_classes} classes from idx_to_class.json")
print(f"[FOOD_ML] Sample classes: {class_names[:5]}")

# --------- Build model (must match training) ----------
def build_model(num_classes: int) -> torch.nn.Module:
    model = models.resnet50(weights=None)
    in_features = model.fc.in_features
    model.fc = nn.Linear(in_features, num_classes)
    return model


model = None

def _load_model():
    global model
    if model is not None:
        return model

    try:
        print(f"[FOOD_ML] Loading model from {WEIGHTS_PATH}...")
        print(f"[FOOD_ML] Model will have {num_classes} output classes")
        model = build_model(num_classes).to(DEVICE)
        state = torch.load(WEIGHTS_PATH, map_location=DEVICE)
        model.load_state_dict(state)
        model.eval()
        print(f"[FOOD_ML] Model loaded successfully with {num_classes} classes")
        return model
    except Exception as e:
        print(f"[FOOD_ML] ERROR loading model: {e}")
        import traceback
        traceback.print_exc()
        raise

# --------- Preprocess (must match your test_tfms) ----------
preprocess = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225]),
])


@torch.no_grad()
def predict_topk(pil_img: Image.Image, k: int = 3):
    m = _load_model()
    img = pil_img.convert("RGB")
    x = preprocess(img).unsqueeze(0).to(DEVICE)
    logits = m(x)
    probs = torch.softmax(logits, dim=1)[0]
    topk = torch.topk(probs, k=min(k, probs.numel()))

    results = []
    for idx, p in zip(topk.indices.tolist(), topk.values.tolist()):
        label = idx_to_class.get(idx, f"class_{idx}")
        results.append((label, float(p)))
    return results


def _require_login():
    return session.get("user_id") is not None


def _session_get_pred_history():
    hist = session.get("predicted_history", [])
    if not isinstance(hist, list):
        hist = []
    return hist


def _save_upload_to_static(file_storage) -> str:
    orig_name = secure_filename(file_storage.filename or "upload.jpg")
    ext = Path(orig_name).suffix.lower()
    if ext not in ALLOWED_EXTS:
        ext = ".jpg"

    out_name = f"{uuid.uuid4().hex}_{Path(orig_name).stem}{ext}"
    out_path = UPLOAD_DIR / out_name
    file_storage.save(out_path)

    return url_for("static", filename=f"food_uploads/{out_name}")


def _build_nav_buttons() -> str:
    """
    Same idea as home.py:
    build nav HTML in Python based on session data.
    """
    logout_url = url_for("auth.logout")
    maps_url = url_for("maps.index")
    home_url = url_for("home.home")
    clock_url = url_for("clock.index")

    nav_buttons = f"""
        <li><a href="{home_url}">Home</a></li>
        <li><a href="{maps_url}">Maps</a></li>
        <li><a href="{clock_url}">Clock In/Out</a></li>
        
        <li>
            <form method="post" action="{logout_url}" style="display:inline;">
                <button type="submit">Logout</button>
            </form>
        </li>
    """
    return nav_buttons


@food_bp.route("/", methods=["GET"])
def index():
    if not _require_login():
        return redirect(url_for("auth.login"))

    meal = session.get("meal_items", [])
    if not isinstance(meal, list):
        meal = []

    search_query = session.get("last_search_query", "")
    current_image_url = session.get("current_image_url", None)
    current_preds = session.get("current_preds", None)
    history = _session_get_pred_history()

    nav_buttons = _build_nav_buttons()

    return render_template_string(
        PAGE_HTML,
        nav_buttons=nav_buttons,
        meal=meal,
        search_query=search_query,
        class_names=class_names[:5000],
        current_image_url=current_image_url,
        current_preds=current_preds,
        history=history,
    )


@food_bp.route("/predict", methods=["POST"])
def predict():
    if not _require_login():
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"ok": False, "error": "not_logged_in"}), 401
        return redirect(url_for("auth.login"))

    file = request.files.get("image")
    if not file or file.filename == "":
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"ok": False, "error": "no_file"}), 400
        return redirect(url_for("food.index"))

    try:
        image_url = _save_upload_to_static(file)
    except Exception:
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"ok": False, "error": "save_failed"}), 400
        return redirect(url_for("food.index"))

    try:
        rel = image_url.split("/static/", 1)[-1]
        img_path = STATIC_DIR / rel
        pil_img = Image.open(img_path)
    except Exception:
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"ok": False, "error": "bad_image"}), 400
        return redirect(url_for("food.index"))

    preds = predict_topk(pil_img, k=3)
    preds_fmt = [(lbl, f"{prob*100:.2f}%") for lbl, prob in preds]

    session["current_image_url"] = image_url
    session["current_preds"] = preds_fmt
    session["last_search_query"] = ""

    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify({"ok": True, "image_url": image_url, "preds": preds_fmt})

    return redirect(url_for("food.index"))


@food_bp.route("/set_search", methods=["POST"])
def set_search():
    if not _require_login():
        return redirect(url_for("auth.login"))

    q = (request.form.get("search", "") or "").strip().lower()
    session["last_search_query"] = q
    return redirect(url_for("food.index"))


@food_bp.route("/add", methods=["POST"])
def add_food():
    if not _require_login():
        return redirect(url_for("auth.login"))

    chosen = (request.form.get("chosen_label", "") or "").strip()
    if chosen:
        meal = session.get("meal_items", [])
        if not isinstance(meal, list):
            meal = []
        meal.append(chosen)
        session["meal_items"] = meal

        current_image_url = session.get("current_image_url", None)
        current_preds = session.get("current_preds", None) or []

        chosen_prob = ""
        for lbl, prob in current_preds:
            if lbl == chosen:
                chosen_prob = prob
                break

        if current_image_url:
            hist = _session_get_pred_history()
            hist.append({"image_url": current_image_url, "label": chosen, "prob": chosen_prob})
            session["predicted_history"] = hist[-30:]

    session["current_image_url"] = None
    session["current_preds"] = None
    session["last_search_query"] = ""
    return redirect(url_for("food.index"))


@food_bp.route("/remove_meal_item", methods=["POST"])
def remove_meal_item():
    if not _require_login():
        return redirect(url_for("auth.login"))

    try:
        idx = int(request.form.get("index", "-1"))
    except ValueError:
        return redirect(url_for("food.index"))

    meal = session.get("meal_items", [])
    if not isinstance(meal, list):
        meal = []

    if 0 <= idx < len(meal):
        meal.pop(idx)
        session["meal_items"] = meal

    return redirect(url_for("food.index"))


@food_bp.route("/edit_meal_item", methods=["POST"])
def edit_meal_item():
    if not _require_login():
        return redirect(url_for("auth.login"))

    try:
        idx = int(request.form.get("index", "-1"))
    except ValueError:
        return redirect(url_for("food.index"))

    new_label = (request.form.get("new_label", "") or "").strip()
    if not new_label:
        return redirect(url_for("food.index"))

    meal = session.get("meal_items", [])
    if not isinstance(meal, list):
        meal = []

    if 0 <= idx < len(meal):
        meal[idx] = new_label
        session["meal_items"] = meal

    return redirect(url_for("food.index"))


@food_bp.route("/clear_meal", methods=["POST"])
def clear_meal():
    if not _require_login():
        return redirect(url_for("auth.login"))
    session["meal_items"] = []
    return redirect(url_for("food.index"))


@food_bp.route("/clear_history", methods=["POST"])
def clear_history():
    if not _require_login():
        return redirect(url_for("auth.login"))
    session["predicted_history"] = []
    return redirect(url_for("food.index"))


PAGE_HTML = r"""
<!doctype html>
<html>
<head>
  <title>Add Food</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='styles.css') }}">
  <style>
    .card { border:1px solid #ddd; border-radius:12px; padding:16px; margin:16px auto; max-width:900px; background:#fff; }
    .row { display:flex; gap:18px; flex-wrap:wrap; }
    .col { flex:1; min-width:280px; }
    .pred { padding:10px; border:1px solid #eee; border-radius:10px; margin:8px 0; }
    .meal-item { padding:10px; border:1px solid #eee; border-radius:14px; margin:8px 0; background:#fff; }
    input[type="text"] { width: 100%; padding:10px; }
    select { width: 100%; padding:10px; }
    .muted { color:#666; }

    .preview-wrap { margin-top:12px; }
    .preview-img {
      width:160px;
      height:120px;
      object-fit:cover;
      border-radius:10px;
      border:1px solid #eaeaea;
      display:none;
    }

    .history-row {
      display:flex;
      gap:12px;
      overflow-x:auto;
      padding:10px 2px;
      margin-top:10px;
    }
    .history-item {
      min-width:160px;
      border:1px solid #eee;
      border-radius:12px;
      padding:10px;
      background:#fafafa;
      flex:0 0 auto;
    }
    .history-item img {
      width:160px;
      height:120px;
      object-fit:cover;
      border-radius:10px;
      border:1px solid #eaeaea;
      display:block;
    }

    .history-meta { margin-top:8px; font-size:13px; }

    .small { padding:8px 10px; font-size:14px; }
    .edit-row { display:flex; gap:8px; align-items:center; margin-top:8px; }
    .edit-row select { flex:1; }
  </style>
</head>

<body class="home">

  <!-- Header like home.py -->
  <div class="hero-section">
      <div class="hero-image">
          <img src="{{ url_for('static', filename='nutrilog_icon.png') }}" alt="NutriLog Icon">
      </div>
  </div>

  <!-- ✅ Nav menu injected from Python (like home.py) -->
  <nav>
      <ul class="menu">
          {{ nav_buttons|safe }}
      </ul>
  </nav>

  <div class="card">
    <h2>Add Food (Upload → Auto Predict → Pick → Add to Meal)</h2>

    <form id="predictForm" action="{{ url_for('food.predict') }}" method="post" enctype="multipart/form-data">
      <label><b>Upload a food image:</b></label><br><br>
      <input id="imageInput" type="file" name="image" accept="image/*" required>

      <div class="preview-wrap">
        <p id="pickedFileText" class="muted">No file selected yet.</p>
        <img id="mainImg" class="preview-img" alt="Food preview">
      </div>

      <p id="predictStatus" class="muted" style="margin-top:10px;"></p>
    </form>
  </div>

  <div class="card">
    <div class="row">
      <div class="col">
        <h3>Top 3 Predictions</h3>

        <div id="predArea">
          {% if current_preds %}
            <form action="{{ url_for('food.add_food') }}" method="post" id="addFoodForm">
              {% for lbl, prob in current_preds %}
                <div class="pred">
                  <label style="display:flex; justify-content:space-between; align-items:center;">
                    <span>
                      <input type="radio" name="chosen_label" value="{{ lbl }}" required>
                      <b>{{ lbl }}</b>
                    </span>
                    <span>{{ prob }}</span>
                  </label>
                </div>
              {% endfor %}
              <button type="submit">Add Selected To Meal</button>
            </form>
          {% else %}
            <p id="noPredText">No predictions yet. Upload an image above.</p>
          {% endif %}
        </div>

        <hr>

        <h3>Wrong? Search and pick a food</h3>

        <form action="{{ url_for('food.set_search') }}" method="post" style="margin-bottom:10px;">
          <input type="text" name="search" placeholder="Search food label..." value="{{ search_query }}">
          <button type="submit" style="margin-top:8px;">Search</button>
        </form>

        {% if search_query %}
          {% set matches = [] %}
          {% for name in class_names %}
            {% if search_query in name.lower() %}
              {% set _ = matches.append(name) %}
            {% endif %}
          {% endfor %}

          <form action="{{ url_for('food.add_food') }}" method="post">
            <label><b>Matches:</b></label>
            <select name="chosen_label" required>
              {% for m in matches[:50] %}
                <option value="{{ m }}">{{ m }}</option>
              {% endfor %}
            </select>
            <button type="submit" style="margin-top:8px;">Add Selected To Meal</button>
          </form>

          {% if matches|length == 0 %}
            <p>No matches found.</p>
          {% endif %}
        {% endif %}
      </div>

      <div class="col">
        <h3>Current Meal</h3>
        {% if meal and meal|length > 0 %}
          {% for item in meal %}
            {% set i = loop.index0 %}
            <div class="meal-item">
              <div style="display:flex; justify-content:space-between; align-items:center; gap:12px;">
                <div><b>{{ item }}</b></div>

                <form action="{{ url_for('food.remove_meal_item') }}" method="post" style="margin:0;">
                  <input type="hidden" name="index" value="{{ i }}">
                  <button type="submit" class="small">Remove</button>
                </form>
              </div>

              <form action="{{ url_for('food.edit_meal_item') }}" method="post" class="edit-row">
                <input type="hidden" name="index" value="{{ i }}">
                <select name="new_label" required>
                  <option value="" disabled selected>Change to…</option>
                  {% for n in class_names[:5000] %}
                    <option value="{{ n }}">{{ n }}</option>
                  {% endfor %}
                </select>
                <button type="submit" class="small">Edit</button>
              </form>
            </div>
          {% endfor %}

          <form action="{{ url_for('food.clear_meal') }}" method="post" style="margin-top:12px;">
            <button type="submit">Clear Meal</button>
          </form>
        {% else %}
          <p>No items added yet. Add foods and they’ll appear here.</p>
        {% endif %}

        <p style="margin-top:14px; color:#666;">
          (Right now this “meal” list is stored in your session. Next step is saving it to MySQL with a timestamp so you can view past meals.)
        </p>
      </div>
    </div>
  </div>

  <div class="card">
    <h3 style="display:flex; justify-content:space-between; align-items:center;">
      <span>Last Predicted (added to meal)</span>
      <form action="{{ url_for('food.clear_history') }}" method="post"
            onsubmit="return confirm('Clear all last predicted images?');" style="margin:0;">
        <button type="submit">Clear</button>
      </form>
    </h3>

    {% if history and history|length > 0 %}
      <div class="history-row">
        {% for item in history %}
          <div class="history-item">
            <img src="{{ item.image_url }}" alt="predicted">
            <div class="history-meta">
              <div><b>{{ item.label }}</b></div>
              {% if item.prob %}
                <div class="muted">{{ item.prob }}</div>
              {% endif %}
            </div>
          </div>
        {% endfor %}
      </div>
    {% else %}
      <p class="muted">No history yet. Add a predicted item to your meal to start building history.</p>
    {% endif %}
  </div>

  <script>
    const input = document.getElementById("imageInput");
    const mainImg = document.getElementById("mainImg");
    const pickedFileText = document.getElementById("pickedFileText");
    const predictStatus = document.getElementById("predictStatus");
    const predictForm = document.getElementById("predictForm");
    const predArea = document.getElementById("predArea");

    let lastObjectUrl = null;

    function renderPredictions(preds) {
      if (!preds || preds.length === 0) {
        predArea.innerHTML = '<p id="noPredText">No predictions yet. Upload an image above.</p>';
        return;
      }

      let html = '';
      html += `<form action="{{ url_for('food.add_food') }}" method="post" id="addFoodForm">`;
      for (const [lbl, prob] of preds) {
        const safeLbl = String(lbl).replace(/"/g, '&quot;');
        html += `
          <div class="pred">
            <label style="display:flex; justify-content:space-between; align-items:center;">
              <span>
                <input type="radio" name="chosen_label" value="${safeLbl}" required>
                <b>${lbl}</b>
              </span>
              <span>${prob}</span>
            </label>
          </div>
        `;
      }
      html += `<button type="submit">Add Selected To Meal</button></form>`;
      predArea.innerHTML = html;
    }

    async function autoPredict() {
      const file = input.files && input.files[0];
      if (!file) return;

      predictStatus.textContent = "Predicting...";

      const formData = new FormData(predictForm);

      try {
        const resp = await fetch(predictForm.action, {
          method: "POST",
          body: formData,
          headers: { "X-Requested-With": "fetch" }
        });

        const data = await resp.json();
        if (!resp.ok || !data.ok) {
          predictStatus.textContent = "Predict failed. Try a different image.";
          return;
        }

        if (data.image_url) {
          if (lastObjectUrl) {
            URL.revokeObjectURL(lastObjectUrl);
            lastObjectUrl = null;
          }
          mainImg.src = data.image_url;
          mainImg.style.display = "block";
        }

        renderPredictions(data.preds);
        predictStatus.textContent = "Prediction ready. Select the correct one and add to meal.";
      } catch (err) {
        console.error(err);
        predictStatus.textContent = "Predict crashed. Check your Flask console for the error.";
      }
    }

    input.addEventListener("change", () => {
      const file = input.files && input.files[0];

      if (!file) {
        pickedFileText.textContent = "No file selected yet.";
        mainImg.style.display = "none";
        if (lastObjectUrl) URL.revokeObjectURL(lastObjectUrl);
        lastObjectUrl = null;
        return;
      }

      pickedFileText.textContent = `Selected: ${file.name}`;

      if (lastObjectUrl) URL.revokeObjectURL(lastObjectUrl);
      lastObjectUrl = URL.createObjectURL(file);

      mainImg.src = lastObjectUrl;
      mainImg.style.display = "block";

      autoPredict();
    });
  </script>

</body>
</html>
"""
