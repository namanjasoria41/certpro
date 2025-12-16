import os
import json
import string
import random
from io import BytesIO
from datetime import datetime, timedelta

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    send_from_directory,
    send_file,
    session,
    abort,
    Response,
)
from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user,
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image, ImageDraw, ImageFont

from sqlalchemy.exc import ProgrammingError, IntegrityError

# Import config and models (make sure these modules exist)
from config import Config
from models import (
    db,
    User,
    Template,
    TemplateField,
    Transaction,
    ReferralCode,
    ReferralRedemption,
)

import razorpay
from razorpay.errors import SignatureVerificationError

from weasyprint import HTML
import io

# --------------------------------------------------------------------------
# App / DB / Login setup
# --------------------------------------------------------------------------

app = Flask(__name__)
app.config.from_object(Config)

# Optional: limit upload size (e.g. 8MB)
app.config.setdefault("MAX_CONTENT_LENGTH", 8 * 1024 * 1024)

# Make DB connections robust
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
}

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except Exception:
        return None


# Razorpay client
razorpay_client = razorpay.Client(
    auth=(getattr(Config, "RAZORPAY_KEY_ID", ""), getattr(Config, "RAZORPAY_KEY_SECRET", ""))
)

# Ensure folders exist
os.makedirs(getattr(Config, "TEMPLATE_FOLDER", "static/templates"), exist_ok=True)
os.makedirs(getattr(Config, "PREVIEW_FOLDER", "static/previews"), exist_ok=True)
os.makedirs(getattr(Config, "GENERATED_FOLDER", "static/generated"), exist_ok=True)

# Create tables on startup (safe if models match DB)
with app.app_context():
    try:
        db.create_all()
    except Exception:
        app.logger.exception("db.create_all() failed — make sure models and DB are in sync")


@app.context_processor
def inject_jinja_globals():
    return {"globals": app.jinja_env.globals}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def generate_referral_code(length: int = 8) -> str:
    chars = string.ascii_uppercase + string.digits
    while True:
        code = "".join(random.choice(chars) for _ in range(length))
        if not ReferralCode.query.filter_by(code=code).first():
            return code


def safe_query_user_by_phone(phone_value):
    try:
        return User.query.filter_by(phone=phone_value).first()
    except ProgrammingError:
        app.logger.warning("Phone column missing in DB; skipping phone lookup.")
        db.session.rollback()
        return None
    except Exception:
        app.logger.exception("Unexpected error while querying by phone.")
        return None


def safe_query_user_by_email(email_value):
    try:
        return User.query.filter_by(email=email_value).first()
    except Exception:
        app.logger.exception("Error querying user by email.")
        db.session.rollback()
        return None


def get_font_path_for_token(token: str):
    """
    Resolve font token to TTF path using Config.FONT_FAMILIES or Config.FONT_PATH fallback.
    """
    try:
        families = getattr(Config, "FONT_FAMILIES", None)
        if isinstance(families, dict):
            path = families.get(token)
            if path and os.path.exists(path):
                return path
        default_fp = getattr(Config, "FONT_PATH", None)
        if default_fp and os.path.exists(default_fp):
            return default_fp
    except Exception:
        app.logger.exception("Error resolving font path for token %s", token)
    return None


def _safe_int(v, default=0):
    try:
        if v is None or v == "":
            return default
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return default


def open_template_image_for_pil(template):
    # 1️⃣ DB FIRST (permanent)
    if template.image_data:
        return Image.open(BytesIO(template.image_data)).convert("RGBA")

    # 2️⃣ Disk fallback (optional)
    if template.image_path:
        path = os.path.join(Config.TEMPLATE_FOLDER, template.image_path)
        if os.path.exists(path):
            return Image.open(path).convert("RGBA")

    # 3️⃣ External URL
    if template.image_url:
        import requests
        r = requests.get(template.image_url, timeout=5)
        r.raise_for_status()
        return Image.open(BytesIO(r.content)).convert("RGBA")

    raise RuntimeError("Template image missing")



@app.route("/template_image/<int:template_id>")
def serve_template_image(template_id):
    """
    Serve template image to browsers. Priority:
      1) filesystem file
      2) DB image_data (bytea)
      3) redirect to image_url
    """
    template = Template.query.get(template_id)
    if not template:
        abort(404)

    # 1) disk file
    if template.image_path:
        disk_path = os.path.join(getattr(Config, "TEMPLATE_FOLDER", "static/templates"), template.image_path)
        if os.path.exists(disk_path):
            return send_file(disk_path)

    # 2) DB binary
    if getattr(template, "image_data", None):
        data = template.image_data
        mime = getattr(template, "image_mime", None) or "image/png"
        buf = BytesIO(data)
        # flask.send_file supports file-like objects
        return send_file(buf, mimetype=mime, as_attachment=False, download_name=template.image_path or f"template_{template.id}.png")

    # 3) external URL
    if template.image_url:
        return redirect(template.image_url)

    abort(404)


def _ensure_template_image_exists_or_redirect(template):
    """
    Return either:
      - absolute filesystem path (string) if present, OR
      - a URL (string) to `/template_image/<id>` if image available only in DB,
      - or None (and flash) if missing.
    """
    disk_path = os.path.join(getattr(Config, "TEMPLATE_FOLDER", "static/templates"), template.image_path or "")
    if template.image_path and os.path.exists(disk_path):
        return disk_path

    if getattr(template, "image_data", None) or template.image_url:
        return url_for("serve_template_image", template_id=template.id)

    app.logger.error(f"Template image missing: disk({disk_path}) and no DB/image_url (template id {template.id})")
    flash("Base template image not found on server. Please contact admin or re-upload the template.", "danger")
    return None


def compose_image_from_fields(template, fields, values=None, file_map=None):
    """
    Draw text and paste uploaded images on the template image.
    """
    values = values or {}
    file_map = file_map or {}

    # Always load base image safely (DB → disk → URL)
    base_image = open_template_image_for_pil(template)
    draw = ImageDraw.Draw(base_image)

    for field in fields:
        key = getattr(field, "field_name", None) or getattr(field, "name", None)
        if not key:
            continue

        ftype = (getattr(field, "field_type", None)
                 or getattr(field, "type", None)
                 or "text").lower()

        x = getattr(field, "x", None)
        if x is None:
            x = getattr(field, "x_position", 0) or 0

        y = getattr(field, "y", None)
        if y is None:
            y = getattr(field, "y_position", 0) or 0

        color = getattr(field, "color", None) or getattr(field, "font_color", None) or "#000000"
        font_size = getattr(field, "font_size", None) or getattr(field, "size", None) or 24
        align = getattr(field, "align", "left") or "left"
        width = getattr(field, "width", None)
        height = getattr(field, "height", None)
        shape = getattr(field, "shape", None) or "rect"
        font_family = getattr(field, "font_family", None) or getattr(field, "font", None)

        # ---------------- IMAGE FIELD ----------------
        if ftype == "image":
            img_path = file_map.get(key)
            if not img_path or not os.path.exists(img_path):
                continue

            try:
                user_img = Image.open(img_path).convert("RGBA")
            except Exception:
                continue

            if width and height:
                user_img = user_img.resize((int(width), int(height)), Image.LANCZOS)

            if shape == "circle":
                size = min(user_img.size)
                mask = Image.new("L", (size, size), 0)
                d = ImageDraw.Draw(mask)
                d.ellipse((0, 0, size, size), fill=255)
                user_img = user_img.crop((0, 0, size, size))
                user_img.putalpha(mask)

            base_image.paste(user_img, (int(x), int(y)), user_img)

        # ---------------- TEXT FIELD ----------------
        else:
            text = values.get(key, "")
            if not text:
                continue

            font_path = get_font_path_for_token(font_family)
            try:
                font = ImageFont.truetype(font_path, int(font_size)) if font_path else ImageFont.load_default()
            except Exception:
                font = ImageFont.load_default()

            text_width = draw.textbbox((0, 0), text, font=font)[2]
            tx = int(x)

            if align == "center":
                tx -= text_width // 2
            elif align == "right":
                tx -= text_width

            draw.text((tx, int(y)), text, fill=color, font=font)

    return base_image


# --------------------------------------------------------------------------
# Auth routes (register/login/logout/forgot-password)
# --------------------------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        referral_code_input = request.form.get("referral_code", "").strip()

        if (not email and not phone) or not password:
            flash("Please provide at least an email or mobile number, and a password.", "danger")
            return redirect(url_for("register"))
        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("register"))

        if email:
            existing_email = safe_query_user_by_email(email)
            if existing_email:
                flash("An account with this email already exists. Please log in.", "warning")
                return redirect(url_for("login"))
        if phone:
            existing_phone = safe_query_user_by_phone(phone)
            if existing_phone:
                flash("An account with this mobile number already exists. Please log in.", "warning")
                return redirect(url_for("login"))

        hashed_password = generate_password_hash(password)
        try:
            user = User(email=email or None, phone=phone or None, password=hashed_password)
        except TypeError:
            user = User(email=email or None, password=hashed_password)
            try:
                if hasattr(User, "phone"):
                    setattr(user, "phone", phone or None)
            except Exception:
                pass

        if referral_code_input:
            code_str = referral_code_input.strip().upper()
            rc = ReferralCode.query.filter_by(code=code_str, is_active=True).first()
            if rc:
                if rc.expires_at and rc.expires_at < datetime.utcnow():
                    flash("Referral code has expired.", "warning")
                elif rc.max_uses is not None and rc.used_count >= rc.max_uses:
                    flash("Referral code has reached maximum uses.", "warning")
                else:
                    try:
                        user.referred_by = rc.owner
                        if hasattr(user, "wallet_balance"):
                            user.wallet_balance = (user.wallet_balance or 0.0) + getattr(Config, "REFERRAL_NEW_USER_BONUS", 0.0)
                    except Exception:
                        app.logger.exception("Failed to set referral on new user")
                    try:
                        redemption = ReferralRedemption(
                            referral_code=rc,
                            redeemed_by_user=user,
                            reward_amount=getattr(Config, "REFERRAL_OWNER_BONUS", 0.0),
                        )
                        db.session.add(redemption)
                        if hasattr(rc.owner, "wallet_balance"):
                            rc.owner.wallet_balance = (rc.owner.wallet_balance or 0.0) + getattr(Config, "REFERRAL_OWNER_BONUS", 0.0)
                        rc.used_count = (rc.used_count or 0) + 1
                    except Exception:
                        app.logger.exception("Failed to create referral redemption")
            else:
                flash("Invalid or inactive referral code.", "warning")

        try:
            db.session.add(user)
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("Failed to create user during registration.")
            flash("Registration failed due to server error.", "danger")
            return redirect(url_for("register"))

        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "").strip()

        user = None
        if "@" in identifier:
            user = safe_query_user_by_email(identifier.lower())
        else:
            user = safe_query_user_by_phone(identifier)

        if user and check_password_hash(user.password, password):
            login_user(user)
            flash("Logged in successfully.", "success")
            return redirect(url_for("index"))
        else:
            flash("Invalid credentials. Check your email/mobile and password.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.", "info")
    return redirect(url_for("login"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not email or not new_password:
            flash("Email and new password are required.", "danger")
            return redirect(url_for("forgot_password"))
        if new_password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("forgot_password"))

        user = safe_query_user_by_email(email)
        if not user:
            flash("No account found with that email.", "warning")
            return redirect(url_for("forgot_password"))

        user.password = generate_password_hash(new_password)
        db.session.commit()
        flash("Password updated successfully. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


# --------------------------------------------------------------------------
# Wallet / Transactions
# --------------------------------------------------------------------------

@app.route("/wallet", methods=["GET"])
@login_required
def wallet():
    transactions = (
        Transaction.query.filter_by(user_id=current_user.id)
        .order_by(Transaction.timestamp.desc())
        .all()
    )
    return render_template("wallet.html", transactions=transactions)


@app.route("/add_money", methods=["POST"])
@login_required
def add_money():
    try:
        amount = float(request.form.get("amount"))
    except (TypeError, ValueError):
        flash("Invalid amount.", "danger")
        return redirect(url_for("wallet"))

    if amount < 300:
        flash("Minimum wallet top-up amount is ₹300.", "danger")
        return redirect(url_for("wallet"))

    amount_paise = int(round(amount * 100))
    order = razorpay_client.order.create(
        {
            "amount": amount_paise,
            "currency": "INR",
            "payment_capture": "1",
            "notes": {"purpose": "wallet_topup", "user_id": str(current_user.id)},
        }
    )
    session["wallet_topup_amount"] = amount
    session["wallet_order_id"] = order["id"]

    transactions = (
        Transaction.query.filter_by(user_id=current_user.id)
        .order_by(Transaction.timestamp.desc())
        .all()
    )

    return render_template(
        "wallet.html",
        transactions=transactions,
        razorpay_key_id=Config.RAZORPAY_KEY_ID,
        razorpay_order_id=order["id"],
        amount=amount,
        amount_paise=amount_paise,
    )


@app.route("/payment/verify", methods=["POST"])
@login_required
def payment_verify():
    data = request.form or request.get_json() or {}
    razorpay_order_id = data.get("razorpay_order_id")
    razorpay_payment_id = data.get("razorpay_payment_id")
    razorpay_signature = data.get("razorpay_signature")

    if not (razorpay_order_id and razorpay_payment_id and razorpay_signature):
        flash("Missing payment data.", "danger")
        return redirect(url_for("wallet"))

    params_dict = {
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": razorpay_payment_id,
        "razorpay_signature": razorpay_signature,
    }
    try:
        razorpay_client.utility.verify_payment_signature(params_dict)
    except SignatureVerificationError:
        flash("Payment verification failed. If money was deducted, contact support.", "danger")
        return redirect(url_for("wallet"))

    wallet_order_id = session.get("wallet_order_id")
    wallet_amount = session.get("wallet_topup_amount")
    purchase_order_id = session.get("purchase_order_id")
    preview_info = session.get("preview_info")

    flow = None
    if wallet_order_id and wallet_order_id == razorpay_order_id:
        flow = "wallet"
    elif purchase_order_id and purchase_order_id == razorpay_order_id:
        flow = "purchase"
    else:
        app.logger.warning("Payment verify: unknown order id")
        flash("Payment processed but session mismatched. Contact support.", "warning")
        return redirect(url_for("wallet"))

    try:
        razorpay_order = razorpay_client.order.fetch(razorpay_order_id)
        razorpay_order_amount = int(razorpay_order.get("amount", 0))
    except Exception:
        app.logger.exception("Failed to fetch razorpay order")
        flash("Could not verify payment with Razorpay. Contact support.", "danger")
        return redirect(url_for("wallet"))

    existing_tx = Transaction.query.filter_by(razorpay_payment_id=razorpay_payment_id).first()
    if existing_tx:
        flash("Payment already processed.", "info")
        session.pop("wallet_order_id", None)
        session.pop("wallet_topup_amount", None)
        session.pop("purchase_order_id", None)
        session.pop("preview_info", None)
        return redirect(url_for("wallet"))

    if flow == "wallet":
        if wallet_amount is None:
            flash("Session missing topup amount. Contact support.", "warning")
            return redirect(url_for("wallet"))
        expected_paise = int(round(wallet_amount * 100))
        if razorpay_order_amount != expected_paise:
            flash("Payment amount mismatch. Contact support.", "danger")
            return redirect(url_for("wallet"))

        try:
            current_user.wallet_balance += wallet_amount
            tx = Transaction(
                user_id=current_user.id,
                amount=wallet_amount,
                transaction_type="credit",
                description="Wallet recharge via Razorpay",
                razorpay_payment_id=razorpay_payment_id,
            )
            db.session.add(tx)
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("Failed to credit wallet")
            flash("Failed to update wallet. Contact support.", "danger")
            return redirect(url_for("wallet"))

        session.pop("wallet_order_id", None)
        session.pop("wallet_topup_amount", None)
        flash(f"Wallet recharged with ₹{wallet_amount:.2f}", "success")
        return redirect(url_for("wallet"))

    if flow == "purchase":
        if not preview_info or "template_id" not in preview_info:
            flash("Preview info missing after payment. Contact support.", "danger")
            return redirect(url_for("wallet"))

        template_id = int(preview_info["template_id"])
        template = Template.query.get(template_id)
        if not template:
            flash("Template not found after payment. Contact support.", "danger")
            return redirect(url_for("wallet"))

        expected_paise = int(round((template.price or 0) * 100))
        if razorpay_order_amount != expected_paise:
            flash("Payment amount mismatch for template purchase. Contact support.", "danger")
            return redirect(url_for("wallet"))

        try:
            filename = _generate_final_certificate_from_preview(current_user, template, preview_info)
            tx = Transaction(
                user_id=current_user.id,
                amount=template.price,
                transaction_type="debit",
                description=f"Certificate purchase - {template.name}",
                razorpay_payment_id=razorpay_payment_id,
            )
            db.session.add(tx)
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("Failed to finalize purchase")
            flash("Payment succeeded but server failed to finish purchase. Contact support.", "danger")
            return redirect(url_for("wallet"))

        session.pop("purchase_order_id", None)
        session.pop("preview_info", None)
        flash("Payment successful! Certificate generated.", "success")
        return redirect(url_for("view_certificate", filename=filename))

    flash("Unhandled payment flow", "warning")
    return redirect(url_for("wallet"))


# --------------------------------------------------------------------------
# Admin: Templates management
# --------------------------------------------------------------------------

@app.route("/admin/templates")
@login_required
def admin_templates():
    if not getattr(current_user, "is_admin", False):
        flash("Access denied.", "danger")
        return redirect(url_for("index"))

    try:
        templates = Template.query.order_by(Template.id.desc()).all()
    except ProgrammingError:
        app.logger.warning("Template full-query failed (schema mismatch). Falling back to with_entities.")
        db.session.rollback()
        templates = Template.query.with_entities(Template.id, Template.name, Template.category, Template.price, Template.image_path).order_by(Template.id.desc()).all()
    return render_template("admin_templates.html", templates=templates)


@app.route("/admin/templates/new", methods=["GET", "POST"])
@login_required
def admin_new_template():
    if not getattr(current_user, "is_admin", False):
        flash("Access denied.", "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()
        try:
            price = float(request.form.get("price") or 0)
        except Exception:
            price = 0.0

        image_file = request.files.get("image")
        if not image_file or image_file.filename == "":
            flash("Image file is required.", "danger")
            return redirect(url_for("admin_new_template"))
        if not allowed_file(image_file.filename):
            flash("Only JPG, JPEG, PNG, GIF allowed.", "danger")
            return redirect(url_for("admin_new_template"))

        filename = secure_filename(image_file.filename)
        save_dir = getattr(Config, "TEMPLATE_FOLDER", "static/templates")
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, filename)
        image_file.save(save_path)

        template = Template(name=name, category=category, price=price, image_path=filename)
        # optionally store binary in DB too
        try:
            with open(save_path, "rb") as f:
                template.image_data = f.read()
                template.image_mime = "image/" + filename.rsplit(".", 1)[1].lower()
        except Exception:
            app.logger.exception("Failed to read saved image to store in DB")

        try:
            db.session.add(template)
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("Failed to add new template")
            flash("Failed to add template.", "danger")
            return redirect(url_for("admin_new_template"))

        flash("Template added successfully.", "success")
        return redirect(url_for("admin_templates"))

    return render_template("admin_new_template.html")


@app.route("/admin/template/<int:template_id>/edit", methods=["GET", "POST"])
@login_required
def admin_edit_template(template_id):
    if not getattr(current_user, "is_admin", False):
        flash("Access denied.", "danger")
        return redirect(url_for("index"))

    template = Template.query.get_or_404(template_id)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()
        price_raw = request.form.get("price", "").strip()
        if not name or not category:
            flash("Name and category are required.", "danger")
            return redirect(url_for("admin_edit_template", template_id=template.id))
        try:
            price = float(price_raw or 0)
        except ValueError:
            flash("Invalid price.", "danger")
            return redirect(url_for("admin_edit_template", template_id=template.id))

        template.name = name
        template.category = category
        template.price = price

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("Failed to update template.")
            flash("Failed to update template.", "danger")
            return redirect(url_for("admin_edit_template", template_id=template.id))

        flash("Template updated successfully.", "success")
        return redirect(url_for("admin_templates"))

    return render_template("admin_edit_template.html", template=template)


@app.route("/admin/template/<int:template_id>/delete", methods=["POST"])
@login_required
def admin_delete_template(template_id):
    if not getattr(current_user, "is_admin", False):
        flash("Access denied.", "danger")
        return redirect(url_for("index"))

    template = Template.query.get_or_404(template_id)
    TemplateField.query.filter_by(template_id=template.id).delete()

    if template.image_path:
        image_path = os.path.join(getattr(Config, "TEMPLATE_FOLDER", "static/templates"), template.image_path)
        try:
            if os.path.exists(image_path):
                os.remove(image_path)
        except Exception as e:
            app.logger.warning(f"Failed to delete template image {image_path}: {e}")

    try:
        db.session.delete(template)
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("Failed to delete template")
        flash("Failed to delete template.", "danger")
        return redirect(url_for("admin_templates"))

    flash(f"Template '{template.name}' deleted successfully.", "success")
    return redirect(url_for("admin_templates"))


@app.route("/admin/referrals")
@login_required
def admin_referrals():
    if not getattr(current_user, "is_admin", False):
        flash("Access denied.", "danger")
        return redirect(url_for("index"))

    referral_codes = ReferralCode.query.order_by(ReferralCode.created_at.desc()).all()
    return render_template("admin_referrals.html", referral_codes=referral_codes)


@app.route("/admin/referrals/new", methods=["POST"])
@login_required
def admin_create_referral():
    if not getattr(current_user, "is_admin", False):
        flash("Access denied.", "danger")
        return redirect(url_for("index"))

    owner_email = request.form.get("owner_email", "").strip().lower()
    max_uses = request.form.get("max_uses", "").strip()
    expires_in_days = request.form.get("expires_in_days", "").strip()

    owner = safe_query_user_by_email(owner_email)
    if not owner:
        flash("User with that email not found.", "danger")
        return redirect(url_for("admin_referrals"))

    code = generate_referral_code()
    referral_code = ReferralCode(code=code, owner=owner, used_count=0, is_active=True)

    if max_uses.isdigit():
        referral_code.max_uses = int(max_uses)
    if expires_in_days.isdigit():
        referral_code.expires_at = datetime.utcnow() + timedelta(days=int(expires_in_days))

    db.session.add(referral_code)
    db.session.commit()
    flash("Referral code created successfully.", "success")
    return redirect(url_for("admin_referrals"))


# ---------------------------
# Save helper for template fields
# ---------------------------
def save_template_fields(template, fields_list):
    """
    Save fields to DB for template. Ensures required columns get values.
    Returns (True, {"saved": n}) or (False, {"message": ...})
    """
    if not isinstance(fields_list, (list, tuple)):
        return False, {"message": "fields must be a list"}

    try:
        TemplateField.query.filter_by(template_id=template.id).delete()
        db.session.flush()

        for idx, fd in enumerate(fields_list):
            raw_name = (fd.get("field_name") or fd.get("name") or fd.get("key") or "").strip()
            field_name_val = raw_name or f"field_{idx+1}"

            x_val = _safe_int(fd.get("x", fd.get("x_position", fd.get("left", 0))))
            y_val = _safe_int(fd.get("y", fd.get("y_position", fd.get("top", 0))))
            font_size_val = _safe_int(fd.get("font_size", fd.get("size", 24)), default=24)

            color_val = (fd.get("color") or fd.get("font_color") or "#000000") or "#000000"
            align_val = (fd.get("align") or "left") or "left"
            field_type_val = (fd.get("field_type") or fd.get("type") or "text") or "text"
            font_family_val = fd.get("font_family") or fd.get("font") or "default"
            width_val = fd.get("width")
            height_val = fd.get("height")
            shape_val = fd.get("shape")

            obj = TemplateField()
            try:
                obj.template_id = template.id
            except Exception:
                app.logger.exception("Could not set template_id on TemplateField instance")

            # set both canonical and legacy names
            try:
                obj.field_name = field_name_val
            except Exception:
                try:
                    obj.name = field_name_val
                except Exception:
                    pass
            try:
                obj.name = field_name_val
            except Exception:
                pass

            try:
                obj.x_position = x_val
            except Exception:
                try:
                    obj.x = x_val
                except Exception:
                    pass
            try:
                obj.x = x_val
            except Exception:
                pass

            try:
                obj.y_position = y_val
            except Exception:
                try:
                    obj.y = y_val
                except Exception:
                    pass
            try:
                obj.y = y_val
            except Exception:
                pass

            try:
                obj.font_size = font_size_val
            except Exception:
                try:
                    obj.size = font_size_val
                except Exception:
                    pass

            try:
                obj.color = color_val
            except Exception:
                try:
                    obj.font_color = color_val
                except Exception:
                    pass

            try:
                obj.align = align_val
            except Exception:
                pass

            try:
                obj.field_type = field_type_val
            except Exception:
                try:
                    obj.type = field_type_val
                except Exception:
                    pass

            try:
                obj.font_family = font_family_val
            except Exception:
                try:
                    obj.font = font_family_val
                except Exception:
                    pass

            try:
                if width_val is not None and width_val != "":
                    obj.width = _safe_int(width_val)
                if height_val is not None and height_val != "":
                    obj.height = _safe_int(height_val)
                if shape_val:
                    obj.shape = shape_val
            except Exception:
                pass

            app.logger.debug("Saving TemplateField: template_id=%s field_name=%s x_pos=%s y_pos=%s type=%s",
                             getattr(obj, "template_id", None),
                             getattr(obj, "field_name", getattr(obj, "name", None)),
                             getattr(obj, "x_position", getattr(obj, "x", None)),
                             getattr(obj, "y_position", getattr(obj, "y", None)),
                             getattr(obj, "field_type", None))

            db.session.add(obj)

        db.session.commit()
        return True, {"saved": len(fields_list)}
    except IntegrityError as ie:
        db.session.rollback()
        app.logger.exception("DB integrity error saving template fields: %s", ie)
        return False, {"message": "Database integrity error (likely required column missing or null). Ensure each field has a name and coordinates."}
    except Exception as e:
        db.session.rollback()
        app.logger.exception("Unexpected error saving template fields: %s", e)
        return False, {"message": "Unknown database error while saving fields."}


# ---------------------------
# Admin builder routes
# ---------------------------

# compatibility endpoint (older frontends)
@app.route("/admin/templates/<int:template_id>/fields", methods=["POST"])
@login_required
def admin_templates_fields_compat(template_id):
    if not getattr(current_user, "is_admin", False):
        return jsonify({"status": "error", "message": "access denied"}), 403

    template = Template.query.get_or_404(template_id)
    try:
        if request.is_json:
            payload = request.get_json() or {}
        else:
            fields_raw = request.form.get("fields") or request.form.get("data") or None
            if fields_raw:
                payload = {"fields": json.loads(fields_raw)}
            else:
                raw = request.get_data(as_text=True)
                payload = json.loads(raw) if raw else {}
    except Exception:
        app.logger.exception("compat: failed to parse fields payload")
        return jsonify({"status": "error", "message": "invalid JSON payload"}), 400

    fields_list = payload.get("fields", []) if isinstance(payload, dict) else []
    success, info = save_template_fields(template, fields_list)
    if success:
        return jsonify({"status": "ok", **(info or {})})
    else:
        return jsonify({"status": "error", "message": info.get("message", "save failed")}), 400


@app.route("/admin/template/<int:template_id>/builder", methods=["GET", "POST"])
@login_required
def admin_template_builder(template_id):
    if not getattr(current_user, "is_admin", False):
        flash("Access denied.", "danger")
        return redirect(url_for("index"))

    template = Template.query.get_or_404(template_id)

    if request.method == "POST":
        try:
            if request.is_json:
                payload = request.get_json() or {}
            else:
                fields_raw = request.form.get("fields") or request.form.get("data")
                if fields_raw:
                    payload = {"fields": json.loads(fields_raw)}
                else:
                    raw = request.get_data(as_text=True)
                    payload = json.loads(raw) if raw else {}
        except Exception:
            app.logger.exception("Builder payload parse error")
            return jsonify({"status": "error", "message": "Invalid JSON payload"}), 400

        fields_list = payload.get("fields", []) if isinstance(payload, dict) else []
        success, info = save_template_fields(template, fields_list)
        if success:
            return jsonify({"status": "ok", **(info or {})})
        else:
            return jsonify({"status": "error", "message": info.get("message", "save failed")}), 400

    # GET: normalized fields for the JS builder
    fields = TemplateField.query.filter_by(template_id=template.id).all()
    normalized = []
    for f in fields:
        name = getattr(f, "field_name", None) or getattr(f, "name", None) or ""
        x = getattr(f, "x", None)
        if x is None:
            x = getattr(f, "x_position", 0)
        y = getattr(f, "y", None)
        if y is None:
            y = getattr(f, "y_position", 0)
        font_size = getattr(f, "font_size", None) or getattr(f, "size", 24) or 24
        color = getattr(f, "color", None) or getattr(f, "font_color", None) or "#000000"
        align = getattr(f, "align", "left") or "left"
        field_type = getattr(f, "field_type", None) or getattr(f, "type", None) or "text"
        font_family = getattr(f, "font_family", None) or getattr(f, "font", None) or "default"
        width = getattr(f, "width", None)
        height = getattr(f, "height", None)
        shape = getattr(f, "shape", None) or "rect"

        normalized.append({
            "name": name,
            "field_name": name,
            "x": int(x or 0),
            "y": int(y or 0),
            "font_size": int(font_size or 24),
            "color": color or "#000000",
            "align": align,
            "field_type": field_type,
            "font_family": font_family,
            "width": width,
            "height": height,
            "shape": shape,
        })

    # Render builder template
    # Use the serve_template_image route for the <img> tag
    template_image_url = url_for("serve_template_image", template_id=template.id)
    return render_template("admin_template_builder.html", template=template, fields=normalized, template_image_url=template_image_url)


@app.route("/admin/templates/missing-files")
@login_required
def admin_templates_missing_files():
    if not getattr(current_user, "is_admin", False):
        flash("Access denied.", "danger")
        return redirect(url_for("index"))

    missing = []
    for t in Template.query.all():
        path = os.path.join(getattr(Config, "TEMPLATE_FOLDER", "static/templates"), t.image_path or "")
        if not os.path.exists(path):
            missing.append({"id": t.id, "name": t.name, "image_path": t.image_path})
    return render_template("admin_missing_templates.html", missing=missing)


@app.route("/admin/template/<int:template_id>/restore-image", methods=["POST"])
@login_required
def admin_restore_template_image(template_id):
    if not getattr(current_user, "is_admin", False):
        flash("Access denied.", "danger")
        return redirect(url_for("index"))
    template = Template.query.get_or_404(template_id)
    image_file = request.files.get("image")
    if not image_file or image_file.filename == "":
        flash("No file uploaded", "danger")
        return redirect(url_for("admin_templates_missing_files"))
    if not allowed_file(image_file.filename):
        flash("Only JPG/PNG/GIF allowed", "danger")
        return redirect(url_for("admin_templates_missing_files"))
    filename = secure_filename(image_file.filename)
    save_dir = getattr(Config, "TEMPLATE_FOLDER", "static/templates")
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, filename)
    image_file.save(save_path)
    template.image_path = filename
    try:
        with open(save_path, "rb") as f:
            template.image_data = f.read()
            template.image_mime = "image/" + filename.rsplit(".", 1)[1].lower()
    except Exception:
        app.logger.exception("Failed reading saved file into image_data")
    db.session.commit()
    flash("Template image restored.", "success")
    return redirect(url_for("admin_templates_missing_files"))


# --------------------------------------------------------------------------
# Public routes: index, category, fill template, etc.
# --------------------------------------------------------------------------

@app.route("/")
def index():
    if not current_user.is_authenticated:
        return redirect(url_for("login"))

    try:
        templates = Template.query.order_by(Template.id.desc()).all()
    except ProgrammingError:
        app.logger.warning("Index: Template query failed, falling back to minimal select")
        db.session.rollback()
        templates = Template.query.with_entities(Template.id, Template.name, Template.category, Template.price, Template.image_path).order_by(Template.id.desc()).all()

    categories = sorted(set(getattr(t, "category", None) for t in templates if getattr(t, "category", None)))
    return render_template("index.html", templates=templates, categories=categories)


@app.route("/category/<category_name>")
def category(category_name):
    templates = Template.query.filter_by(category=category_name).all()
    return render_template("category.html", templates=templates, category=category_name)


@app.route("/generated/<filename>")
@login_required
def view_certificate(filename):
    generated_folder = getattr(Config, "GENERATED_FOLDER", "static/generated")
    return send_from_directory(generated_folder, filename)


@app.route("/preview/<filename>")
@login_required
def view_preview(filename):
    preview_folder = getattr(Config, "PREVIEW_FOLDER", "static/previews")
    return send_from_directory(preview_folder, filename)

@app.route("/template/<int:template_id>/fill", methods=["GET", "POST"])
@login_required
def fill_template(template_id):
    template = Template.query.get_or_404(template_id)
    fields = TemplateField.query.filter_by(template_id=template.id).all()

    if request.method == "POST":



        field_values = {}     # For text fields
        file_map = {}         # For image fields

        # Base64 cropping support added
        import base64, uuid

        for field in fields:
            key = getattr(field, "field_name", None) or getattr(field, "name", None)
            if not key:
                continue

            ftype = (getattr(field, "field_type", None) 
                     or getattr(field, "type", None) 
                     or "text").lower()

            # ----------------------------
            # TEXT FIELD
            # ----------------------------
            if ftype == "text":
                field_values[key] = request.form.get(key, "")

            # ----------------------------
            # IMAGE FIELD
            # Supports: Base64 cropped OR direct upload
            # ----------------------------
            elif ftype == "image":

                # FIRST: Check if we received a CROPPED BASE64 STRING
                base64_data = request.form.get(key, "")

                if base64_data.startswith("data:image"):
                    try:
                        # Extract Base64 payload
                        header, encoded = base64_data.split(",", 1)
                        img_bytes = base64.b64decode(encoded)

                        # Save cropped output as PNG
                        save_dir = getattr(
                            Config,
                            "TEMP_UPLOAD_FOLDER",
                            os.path.join(getattr(Config, "PREVIEW_FOLDER", "static/previews"), "assets")
                        )
                        os.makedirs(save_dir, exist_ok=True)

                        filename = f"{uuid.uuid4()}.png"
                        filepath = os.path.join(save_dir, filename)

                        with open(filepath, "wb") as f:
                            f.write(img_bytes)

                        file_map[key] = filepath
                        continue  # Move to next field
                    except Exception:
                        app.logger.exception("Failed to decode cropped base64 image")
                        flash(f"Failed to process cropped image for {key}.", "danger")
                        return redirect(url_for("fill_template", template_id=template.id))

                # SECOND: Handle normal file uploads (fallback)
                uploaded = request.files.get(key)
                if uploaded and uploaded.filename:
                    if allowed_file(uploaded.filename):

                        save_dir = getattr(
                            Config,
                            "TEMP_UPLOAD_FOLDER",
                            os.path.join(getattr(Config, "PREVIEW_FOLDER", "static/previews"), "assets")
                        )
                        os.makedirs(save_dir, exist_ok=True)

                        fname = secure_filename(f"{int(datetime.utcnow().timestamp())}_{uploaded.filename}")
                        filepath = os.path.join(save_dir, fname)

                        uploaded.save(filepath)
                        file_map[key] = filepath
                    else:
                        flash(f"Uploaded file type not allowed for {key}.", "danger")
                        return redirect(url_for("fill_template", template_id=template.id))
                else:
                    # No image provided
                    file_map[key] = None

        # ----------------------------
        # BASE TEMPLATE IMAGE
        # ----------------------------
       try:
    composed = compose_image_from_fields(
        template,
        fields,
        values=field_values,
        file_map=file_map
    )



        except Exception:
            app.logger.exception("Failed to compose certificate image")
            flash("Failed to generate certificate image.", "danger")
            return redirect(url_for("fill_template", template_id=template.id))

        # ----------------------------
        # SAVE OUTPUT PNG
        # ----------------------------
        generated_folder = getattr(Config, "GENERATED_FOLDER", "static/generated")
        os.makedirs(generated_folder, exist_ok=True)

        filename = f"certificate_{current_user.id}_{template.id}_{int(datetime.utcnow().timestamp())}.png"
        output_path = os.path.join(generated_folder, filename)

        composed.save(output_path)

        # ----------------------------
        # WALLET DEDUCTION + TRANSACTION LOGGING
        # ----------------------------
        try:
        except Exception:
            db.session.rollback()
            app.logger.exception("Failed to log transaction")
            flash("Certificate generated but transaction failed. Contact support.", "danger")

        flash("Certificate generated successfully!", "success")
        return redirect(url_for("view_certificate", filename=filename))

    return render_template("fill_template.html", template=template, fields=fields)

# ---------------------------
# Preview + Purchase flow
# ---------------------------

@app.route("/template/<int:template_id>/preview", methods=["GET", "POST"])
@login_required
def preview_template(template_id):
    template = Template.query.get_or_404(template_id)
    fields = TemplateField.query.filter_by(template_id=template.id).all()

    if request.method == "POST":
        field_values = {}
        file_map = {}
        preview_folder = getattr(Config, "PREVIEW_FOLDER", "static/previews")
        preview_assets = os.path.join(preview_folder, "assets")
        os.makedirs(preview_assets, exist_ok=True)

        for field in fields:
            key = getattr(field, "field_name", None) or getattr(field, "name", None)
            if not key:
                continue
            ftype = (getattr(field, "field_type", None) or getattr(field, "type", None) or "text").lower()
            if ftype == "image":
                uploaded = request.files.get(key)
                if uploaded and uploaded.filename:
                    if not allowed_file(uploaded.filename):
                        flash(f"Uploaded file for {key} not allowed type.", "danger")
                        return redirect(url_for("preview_template", template_id=template.id))
                    fname = secure_filename(f"{int(datetime.utcnow().timestamp())}_{uploaded.filename}")
                    save_path = os.path.join(preview_assets, fname)
                    uploaded.save(save_path)
                    file_map[key] = save_path
                else:
                    file_map[key] = None
            else:
                field_values[key] = request.form.get(key, "")

        fields = TemplateField.query.filter_by(template_id=template.id).all()
        file_map = asset_map or {}

    composed = compose_image_from_fields(
    template,
    fields,
    values=field_values,
    file_map=file_map
      )


        except Exception:
            app.logger.exception("Failed to compose preview image")
            flash("Failed to create preview image.", "danger")
            return redirect(url_for("preview_template", template_id=template.id))

        os.makedirs(preview_folder, exist_ok=True)
        preview_filename = f"preview_{current_user.id}_{template.id}_{int(datetime.utcnow().timestamp())}.png"
        preview_path = os.path.join(preview_folder, preview_filename)
        composed.save(preview_path)

        preview_info = {
            "preview_filename": preview_filename,
            "field_values": field_values,
            "template_id": template.id,
            "asset_map": file_map,
        }
        session["preview_info"] = preview_info

        return render_template(
            "preview_template.html",
            template=template,
            fields=fields,
            preview_url=url_for("view_preview", filename=preview_filename),
            preview_filename=preview_filename,
        )

    return render_template("preview_template.html", template=template, fields=fields)


def _generate_final_certificate_from_preview(user, template, preview_info):
    field_values = preview_info.get("field_values", {}) if isinstance(preview_info, dict) else {}
    asset_map = preview_info.get("asset_map", {}) if isinstance(preview_info, dict) else {}

    composed = compose_image_from_fields(
    template,
    fields,
    values=field_values,
    file_map=file_map
)


    generated_folder = getattr(Config, "GENERATED_FOLDER", "static/generated")
    os.makedirs(generated_folder, exist_ok=True)
    filename = f"certificate_{user.id}_{template.id}_{int(datetime.utcnow().timestamp())}.png"
    output_path = os.path.join(generated_folder, filename)
    composed.save(output_path)

    try:
        transaction = Transaction(
            user_id=user.id,
            amount=template.price,
            transaction_type="debit",
            description=f"Certificate purchase - {template.name}",
        )
        db.session.add(transaction)
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("Failed to log transaction when generating final certificate")

    return filename


@app.route("/template/<int:template_id>/pdf", methods=["POST"])
@login_required
def generate_pdf(template_id):
    template = Template.query.get_or_404(template_id)
    fields = TemplateField.query.filter_by(template_id=template.id).all()

    data = request.json
    if not data:
        return {"status": "error", "message": "Missing JSON"}, 400

    field_values = data.get("values", {})

    # Load background (same as PNG system)
    im = open_template_image_for_pil(template)

    width, height = im.size

    html_fields = []
    for f in fields:
        key = f.name
        value = field_values.get(key, "")
        html_fields.append({
            "value": value,
            "x": f.x,
            "y": f.y,
            "font_size": f.font_size or 24,
            "color": f.color or "#000",
            "font_family": f.font_family or "default",
            "align": f.align or "left"
        })

    html = render_template("certificate_pdf.html",
                           width=width,
                           height=height,
                           background=url_for("serve_template_image", template_id=template.id),
                           fields=html_fields)

    pdf_content = HTML(string=html, base_url=request.host_url).write_pdf()

    fname = f"certificate_{current_user.id}_{template.id}_{int(datetime.utcnow().timestamp())}.pdf"
    path = os.path.join(Config.GENERATED_FOLDER, fname)

    with open(path, "wb") as f:
        f.write(pdf_content)

    return {"status": "ok", "url": url_for("view_certificate", filename=fname)}


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)














