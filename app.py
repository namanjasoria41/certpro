import os
import io
import json
import string
import random
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
    session,
    Response,
    send_file,
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

# --------------------------------------------------------------------------
# App / DB / Login setup
# --------------------------------------------------------------------------

app = Flask(__name__, static_folder=getattr(Config, "STATIC_FOLDER", "static"))
app.config.from_object(Config)

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
    """Reload user object from the user ID stored in the session."""
    try:
        return User.query.get(int(user_id))
    except Exception:
        return None


# Razorpay client (if keys missing, this will fail on calls — keep keys in Config)
razorpay_client = razorpay.Client(
    auth=(getattr(Config, "RAZORPAY_KEY_ID", ""), getattr(Config, "RAZORPAY_KEY_SECRET", ""))
)

# Create tables on startup (safe if models match DB)
with app.app_context():
    try:
        db.create_all()
    except Exception:
        app.logger.exception("db.create_all() failed — make sure models and DB are in sync")

# Make 'globals' available inside Jinja templates (fixes templates that call "globals")
@app.context_processor
def inject_jinja_globals():
    return {"globals": app.jinja_env.globals}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg"}


def allowed_file(filename: str) -> bool:
    return (
        filename
        and "."
        in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS
    )


def generate_referral_code(length: int = 8) -> str:
    """Generate a unique referral code."""
    chars = string.ascii_uppercase + string.digits
    while True:
        code = "".join(random.choice(chars) for _ in range(length))
        if not ReferralCode.query.filter_by(code=code).first():
            return code


def safe_query_user_by_phone(phone_value):
    """
    Attempt to query User by phone, but don't crash if the phone column doesn't exist.
    Returns User or None.
    """
    try:
        return User.query.filter_by(phone=phone_value).first()
    except ProgrammingError:
        # phone column may not exist in DB schema (no migration)
        app.logger.warning("Phone column missing in DB; skipping phone lookup.")
        db.session.rollback()
        return None
    except Exception:
        app.logger.exception("Unexpected error while querying by phone.")
        return None


def safe_query_user_by_email(email_value):
    """Query user by email with minimal exception handling."""
    try:
        return User.query.filter_by(email=email_value).first()
    except Exception:
        app.logger.exception("Error querying user by email.")
        db.session.rollback()
        return None


def get_font_path_for_token(token: str):
    """
    Resolve a font token (e.g. 'roboto') to an actual TTF path using Config.FONT_FAMILIES,
    falling back to Config.FONT_PATH or None.
    """
    try:
        families = getattr(Config, "FONT_FAMILIES", None)
        if isinstance(families, dict):
            path = families.get(token)
            if path and os.path.exists(path):
                return path
        # fallback to default
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


def get_base_image_for_template(template):
    """
    Return a PIL.Image.Image for the given template.
    Prefers template.image_data (DB) if present, otherwise tries filesystem path.
    Returns PIL Image or None.
    """
    try:
        if getattr(template, "image_data", None):
            bio = io.BytesIO(template.image_data)
            img = Image.open(bio).convert("RGBA")
            return img
        # else fallback to path on disk
        base_image_path = os.path.join(getattr(Config, "TEMPLATE_FOLDER", "static/templates"), template.image_path or "")
        if os.path.exists(base_image_path):
            return Image.open(base_image_path).convert("RGBA")
        app.logger.error("Template base image not found for template id %s", template.id)
    except Exception:
        app.logger.exception("Failed to load base image for template %s", getattr(template, "id", None))
    return None


# Compose a PIL image with the provided fields and form data / file mapping.
# `fields` is an iterable of TemplateField model instances.
# `values` is a dict of text values (key -> text).
# `file_map` is a dict mapping field_name -> path to uploaded file (on disk) (optional).
# Accepts base_image which may be a PIL.Image.Image (preferred)
def compose_image_from_fields(base_image, fields, values=None, file_map=None):
    values = values or {}
    file_map = file_map or {}

    # If base_image is string path, open it, else assume PIL image
    if isinstance(base_image, str):
        base_image = Image.open(base_image).convert("RGBA")
    else:
        # If it's already a PIL image, ensure RGBA
        try:
            if getattr(base_image, "mode", None) != "RGBA":
                base_image = base_image.convert("RGBA")
        except Exception:
            base_image = Image.new("RGBA", (800, 600), (255, 255, 255, 255))

    draw = ImageDraw.Draw(base_image)

    for field in fields:
        # canonical key
        key = getattr(field, "field_name", None) or getattr(field, "name", None)
        if not key:
            continue

        # detect field type
        field_type = getattr(field, "field_type", None) or getattr(field, "type", None) or "text"

        # coordinates & geometry
        x = getattr(field, "x", None)
        if x is None:
            x = getattr(field, "x_position", 0) or 0
        y = getattr(field, "y", None)
        if y is None:
            y = getattr(field, "y_position", 0) or 0

        # common props
        color = getattr(field, "color", None) or getattr(field, "font_color", None) or "#000000"
        font_size = getattr(field, "font_size", None) or getattr(field, "size", None) or 24
        align = getattr(field, "align", "left") or "left"
        width = getattr(field, "width", None)
        height = getattr(field, "height", None)
        shape = getattr(field, "shape", None) or "rect"
        font_family_token = getattr(field, "font_family", None) or getattr(field, "font", None) or "default"

        if (field_type or "text").lower() == "image":
            # for image fields, look for a file in file_map
            file_path = file_map.get(key)
            if not file_path or not os.path.exists(file_path):
                app.logger.debug("No file to paste for image field %s", key)
                continue
            try:
                user_img = Image.open(file_path).convert("RGBA")
            except Exception:
                app.logger.exception("Failed to open image file for field %s", key)
                continue

            # optionally resize
            if width and height:
                try:
                    user_img = user_img.resize((int(width), int(height)), Image.LANCZOS)
                except Exception:
                    app.logger.exception("Failed resizing uploaded image for field %s", key)

            if shape == "circle":
                # make circular alpha mask
                w, h = user_img.size
                size = min(w, h)
                left = (w - size) // 2
                top = (h - size) // 2
                user_img = user_img.crop((left, top, left + size, top + size))
                mask = Image.new("L", user_img.size, 0)
                mdraw = ImageDraw.Draw(mask)
                mdraw.ellipse((0, 0, user_img.size[0], user_img.size[1]), fill=255)
                user_img.putalpha(mask)

            # paste at x,y (top-left)
            try:
                base_image.alpha_composite(user_img, dest=(int(x), int(y)))
            except Exception:
                try:
                    base_image.paste(user_img, (int(x), int(y)), user_img)
                except Exception:
                    app.logger.exception("Failed to paste image for field %s", key)

        else:
            # TEXT
            text = values.get(key, "")
            if text is None or text == "":
                # skip empty text fields to avoid accidental blanking
                continue

            # resolve font path
            font_path = get_font_path_for_token(font_family_token)
            try:
                if font_path:
                    font = ImageFont.truetype(font_path, int(font_size))
                else:
                    font = ImageFont.load_default()
            except Exception:
                app.logger.exception("Loading font failed for token %s", font_family_token)
                font = ImageFont.load_default()

            # compute width for alignment
            try:
                text_bbox = draw.textbbox((0, 0), text, font=font)
                text_width = text_bbox[2] - text_bbox[0]
            except Exception:
                text_width = 0

            tx = int(x)
            if align == "center":
                tx = int(tx - (text_width // 2))
            elif align == "right":
                tx = int(tx - text_width)

            try:
                draw.text((tx, int(y)), text, fill=color, font=font)
            except Exception:
                app.logger.exception("Failed to draw text for field %s", key)

    return base_image


# --------------------------------------------------------------------------
# Routes that serve template images from DB (or fallback to disk)
# --------------------------------------------------------------------------
@app.route("/template-image/<int:template_id>")
def template_image(template_id):
    template = Template.query.get_or_404(template_id)

    # If image_data stored in DB, serve it
    if getattr(template, "image_data", None):
        mime = template.image_mime or "image/png"
        bio = io.BytesIO(template.image_data)
        bio.seek(0)
        return send_file(bio, mimetype=mime)
    # fallback to filesystem
    image_path = os.path.join(getattr(Config, "TEMPLATE_FOLDER", "static/templates"), template.image_path or "")
    if os.path.exists(image_path):
        return send_file(image_path)
    return ("Not found", 404)


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

        # At least one of email or phone is required
        if (not email and not phone) or not password:
            flash("Please provide at least an email or mobile number, and a password.", "danger")
            return redirect(url_for("register"))

        # Check password confirmation
        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("register"))

        # Check existing by email
        if email:
            existing_email = safe_query_user_by_email(email)
            if existing_email:
                flash("An account with this email already exists. Please log in.", "warning")
                return redirect(url_for("login"))

        # Check existing by phone
        if phone:
            existing_phone = safe_query_user_by_phone(phone)
            if existing_phone:
                flash("An account with this mobile number already exists. Please log in.", "warning")
                return redirect(url_for("login"))

        hashed_password = generate_password_hash(password)
        # If model doesn't have phone column, SQLAlchemy may raise — fallback handled
        try:
            user = User(email=email or None, phone=phone or None, password=hashed_password)
        except TypeError:
            user = User(email=email or None, password=hashed_password)
            try:
                if hasattr(User, "phone"):
                    setattr(user, "phone", phone or None)
            except Exception:
                pass

        # Handle referral code if provided
        if referral_code_input:
            code_str = referral_code_input.strip().upper()
            rc = ReferralCode.query.filter_by(code=code_str, is_active=True).first()

            if rc:
                # Check expiry
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

        # Decide whether identifier is email or phone
        if "@" in identifier:
            # Treat as email
            user = safe_query_user_by_email(identifier.lower())
        else:
            # Treat as phone (safe)
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

    # Minimum 300
    if amount < 300:
        flash("Minimum wallet top-up amount is ₹300.", "danger")
        return redirect(url_for("wallet"))

    amount_paise = int(amount * 100)

    order = razorpay_client.order.create(
        {
            "amount": amount_paise,
            "currency": "INR",
            "payment_capture": "1",
            "notes": {
                "purpose": "wallet_topup",
                "user_id": str(current_user.id),
            },
        }
    )

    # Store in session for later verification
    session["wallet_topup_amount"] = amount
    session["wallet_order_id"] = order["id"]

    # Reload transactions for the wallet page
    transactions = (
        Transaction.query.filter_by(user_id=current_user.id)
        .order_by(Transaction.timestamp.desc())
        .all()
    )

    # Render wallet page with Razorpay checkout details
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
    """
    Robust payment verify — supports both wallet and purchase flows (keeps your previous logic).
    """
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

    # Verify signature
    try:
        razorpay_client.utility.verify_payment_signature(params_dict)
    except SignatureVerificationError:
        flash("Payment verification failed. If money was deducted, contact support.", "danger")
        return redirect(url_for("wallet"))

    # determine flow by session
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

    # fetch order for amount verification
    try:
        razorpay_order = razorpay_client.order.fetch(razorpay_order_id)
        razorpay_order_amount = int(razorpay_order.get("amount", 0))
    except Exception:
        app.logger.exception("Failed to fetch razorpay order")
        flash("Could not verify payment with Razorpay. Contact support.", "danger")
        return redirect(url_for("wallet"))

    # idempotency
    existing_tx = Transaction.query.filter_by(razorpay_payment_id=razorpay_payment_id).first()
    if existing_tx:
        flash("Payment already processed.", "info")
        # cleanup session keys
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

    # purchase flow
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

    # try a full model query, but fallback to select-only if DB missing columns
    try:
        templates = Template.query.order_by(Template.id.desc()).all()
    except ProgrammingError:
        app.logger.warning("Template full-query failed (schema mismatch). Falling back to with_entities.")
        db.session.rollback()
        templates = Template.query.with_entities(
            Template.id, Template.name, Template.category, Template.price, Template.image_path
        ).order_by(Template.id.desc()).all()
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
            flash("Only JPG, JPEG, PNG allowed.", "danger")
            return redirect(url_for("admin_new_template"))

        # Decide: store in DB by default (safer on ephemeral hosts). Also keep image_path for compatibility.
        filename = secure_filename(image_file.filename)
        image_bytes = image_file.read()
        mime = image_file.mimetype or "image/png"

        template = Template(
            name=name,
            category=category,
            price=price,
            image_path=filename,  # legacy field
            image_data=image_bytes,
            image_mime=mime,
        )

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

    # Delete all fields for this template
    TemplateField.query.filter_by(template_id=template.id).delete()

    # If filesystem image exists (legacy), try to remove
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


# Add admin referrals endpoints (so base.html links work)
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
    referral_code = ReferralCode(
        code=code,
        owner=owner,
        used_count=0,
        is_active=True,
    )

    if max_uses.isdigit():
        referral_code.max_uses = int(max_uses)

    if expires_in_days.isdigit():
        referral_code.expires_at = datetime.utcnow() + timedelta(
            days=int(expires_in_days)
        )

    db.session.add(referral_code)
    db.session.commit()

    flash("Referral code created successfully.", "success")
    return redirect(url_for("admin_referrals"))


# ---------------------------
# Save helper
# ---------------------------
def save_template_fields(template, fields_list):
    """
    Save fields to DB for template.
    Ensures required DB columns (name, x, y) are written.
    Returns (True, {"saved": n}) or (False, {"message": ...})
    """
    if not isinstance(fields_list, (list, tuple)):
        return False, {"message": "fields must be a list"}

    try:
        # Delete existing fields for this template
        TemplateField.query.filter_by(template_id=template.id).delete()
        db.session.flush()

        for idx, fd in enumerate(fields_list):
            # Normalize field dict keys (support many variants)
            raw_name = (fd.get("field_name") or fd.get("name") or fd.get("key") or "").strip()
            # Guarantee non-empty name
            name_val = raw_name or f"field_{idx+1}"

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

            # canonical assignments with fallbacks
            try:
                obj.template_id = template.id
            except Exception:
                app.logger.exception("Could not set template_id on TemplateField instance")

            try:
                obj.name = name_val
            except Exception:
                pass

            try:
                obj.x = x_val
            except Exception:
                pass

            try:
                obj.y = y_val
            except Exception:
                pass

            try:
                obj.font_size = font_size_val
            except Exception:
                pass

            try:
                obj.color = color_val
            except Exception:
                pass

            try:
                obj.align = align_val
            except Exception:
                pass

            try:
                obj.field_type = field_type_val
            except Exception:
                pass

            try:
                obj.font_family = font_family_val
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
# Canonical admin template builder route (single definition)
# ---------------------------
@app.route("/admin/template/<int:template_id>/builder", methods=["GET", "POST"])
@login_required
def admin_template_builder(template_id):
    # Admin-only
    if not getattr(current_user, "is_admin", False):
        flash("Access denied.", "danger")
        return redirect(url_for("index"))

    template = Template.query.get_or_404(template_id)

    if request.method == "POST":
        # robust payload parsing
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

    # GET: send normalized fields to template JS
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

    # Render the admin builder template (assumes admin_template_builder.html exists)
    return render_template("admin_template_builder.html", template=template, fields=normalized)


# ---------------------------
# Compatibility endpoint (older frontends)
# ---------------------------
@app.route("/admin/templates/<int:template_id>/fields", methods=["POST"])
@login_required
def admin_templates_fields_compat(template_id):
    # Admin-only
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


# Admin helper: list missing template files
@app.route("/admin/templates/missing-files")
@login_required
def admin_templates_missing_files():
    if not getattr(current_user, "is_admin", False):
        flash("Access denied.", "danger")
        return redirect(url_for("index"))

    missing = []
    for t in Template.query.all():
        # if DB has image_data it's fine; otherwise check filesystem
        if getattr(t, "image_data", None):
            continue
        path = os.path.join(getattr(Config, "TEMPLATE_FOLDER", "static/templates"), t.image_path or "")
        if not os.path.exists(path):
            missing.append({"id": t.id, "name": t.name, "image_path": t.image_path})
    return render_template("admin_missing_templates.html", missing=missing)


from flask import Response, send_file, abort
from io import BytesIO

@app.route("/template_image/<int:template_id>")
def serve_template_image(template_id):
    """
    Return the template image. Prefer filesystem file (TEMPLATE_FOLDER + image_path).
    If missing, serve image_data (bytea) from DB. If image_url present, redirect to it.
    """
    template = Template.query.get(template_id)
    if not template:
        abort(404)

    # 1) disk file (preferred)
    if template.image_path:
        disk_path = os.path.join(getattr(Config, "TEMPLATE_FOLDER", "static/templates"), template.image_path)
        if os.path.exists(disk_path):
            return send_file(disk_path)

    # 2) image_data stored in DB
    if getattr(template, "image_data", None):
        data = template.image_data
        mime = getattr(template, "image_mime", None) or "image/png"
        buf = BytesIO(data)
        return send_file(buf, mimetype=mime, as_attachment=False, download_name=template.image_path or f"template_{template.id}.png")

    # 3) image_url fallback
    if template.image_url:
        return redirect(template.image_url)

    # not found
    abort(404)



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
        flash("Only JPG/PNG allowed", "danger")
        return redirect(url_for("admin_templates_missing_files"))
    filename = secure_filename(image_file.filename)
    # save both to DB and optional filesystem path
    image_bytes = image_file.read()
    mime = image_file.mimetype or "image/png"
    template.image_data = image_bytes
    template.image_mime = mime
    template.image_path = filename
    save_dir = getattr(Config, "TEMPLATE_FOLDER", "static/templates")
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, filename)
    try:
        # write file to disk for convenience
        with open(save_path, "wb") as f:
            f.write(image_bytes)
    except Exception:
        app.logger.exception("Failed to write restored file to disk")
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

    # robust template listing (avoid hitting missing DB columns)
    try:
        templates = Template.query.order_by(Template.id.desc()).all()
    except ProgrammingError:
        app.logger.warning("Index: Template query failed, falling back to minimal select")
        db.session.rollback()
        templates = Template.query.with_entities(
            Template.id, Template.name, Template.category, Template.price, Template.image_path
        ).order_by(Template.id.desc()).all()

    categories = sorted(set(getattr(t, "category", None) for t in templates if getattr(t, "category", None)))
    return render_template("index.html", templates=templates, categories=categories)


@app.route("/category/<category_name>")
def category(category_name):
    templates = Template.query.filter_by(category=category_name).all()
    return render_template("category.html", templates=templates, category=category_name)


# Serve generated certificates
@app.route("/generated/<filename>")
@login_required
def view_certificate(filename):
    generated_folder = getattr(Config, "GENERATED_FOLDER", "static/generated")
    return send_from_directory(generated_folder, filename)


# Serve preview images (preview flow saves preview images in PREVIEW_FOLDER)
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
        if current_user.wallet_balance < (template.price or 0):
            flash("Insufficient wallet balance. Please add money first.", "danger")
            return redirect(url_for("wallet"))

        # Collect user-entered text values and prepare file_map for any image fields
        field_values = {}
        file_map = {}
        for field in fields:
            key = getattr(field, "field_name", None) or getattr(field, "name", None)
            if not key:
                continue
            # if this field is an image, expect a file input with same name
            ftype = (getattr(field, "field_type", None) or getattr(field, "type", None) or "text").lower()
            if ftype == "image":
                uploaded = request.files.get(key)
                if uploaded and uploaded.filename:
                    if allowed_file(uploaded.filename):
                        # save upload temporarily into PREVIEW_FOLDER/assets
                        save_dir = getattr(Config, "TEMP_UPLOAD_FOLDER", os.path.join(getattr(Config, "PREVIEW_FOLDER", "static/previews"), "assets"))
                        os.makedirs(save_dir, exist_ok=True)
                        fname = secure_filename(f"{int(datetime.utcnow().timestamp())}_{uploaded.filename}")
                        path = os.path.join(save_dir, fname)
                        uploaded.save(path)
                        file_map[key] = path
                    else:
                        flash(f"Uploaded file for {key} not allowed type.", "danger")
                        return redirect(url_for("fill_template", template_id=template.id))
                else:
                    # no upload, continue; image field optional
                    file_map[key] = None
            else:
                field_values[key] = request.form.get(key, "")

        base_image = get_base_image_for_template(template)
        if base_image is None:
            flash("Base template image missing (server). Contact admin.", "danger")
            return redirect(url_for("index"))

        # compose image (text + pasted user images)
        composed = compose_image_from_fields(base_image, fields, values=field_values, file_map=file_map)

        # Save generated certificate
        generated_folder = getattr(Config, "GENERATED_FOLDER", "static/generated")
        os.makedirs(generated_folder, exist_ok=True)
        filename = (
            f"certificate_{current_user.id}_{template.id}_"
            f"{int(datetime.utcnow().timestamp())}.png"
        )
        output_path = os.path.join(generated_folder, filename)
        composed.save(output_path)

        # Deduct from wallet and log transaction
        try:
            current_user.wallet_balance -= (template.price or 0)
            transaction = Transaction(
                user_id=current_user.id,
                amount=template.price,
                transaction_type="debit",
                description=f"Certificate purchase - {template.name}",
            )
            db.session.add(transaction)
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("Failed saving transaction after generating certificate")
            flash("Failed to record transaction. Contact support.", "danger")
            return redirect(url_for("wallet"))

        flash("Certificate generated successfully.", "success")
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
        # collect field values and any uploaded files (for image fields)
        field_values = {}
        file_map = {}  # saved file paths keyed by field_name

        # preview assets folder
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

        base_image = get_base_image_for_template(template)
        if base_image is None:
            flash("Base template image missing (server). Contact admin.", "danger")
            return redirect(url_for("index"))

        # compose preview image using saved assets
        composed = compose_image_from_fields(base_image, fields, values=field_values, file_map=file_map)

        # Save preview
        preview_folder = getattr(Config, "PREVIEW_FOLDER", "static/previews")
        os.makedirs(preview_folder, exist_ok=True)
        preview_filename = f"preview_{current_user.id}_{template.id}_{int(datetime.utcnow().timestamp())}.png"
        preview_path = os.path.join(preview_folder, preview_filename)
        composed.save(preview_path)

        # Build preview_info to store in session: include field_values and any saved asset filenames (absolute paths)
        preview_info = {
            "preview_filename": preview_filename,
            "field_values": field_values,
            "template_id": template.id,
            "asset_map": file_map,  # may contain absolute paths or None
        }
        session["preview_info"] = preview_info

        return render_template(
            "preview_template.html",
            template=template,
            fields=fields,
            preview_url=url_for("view_preview", filename=preview_filename),
            preview_filename=preview_filename,
        )

    # GET -> show form
    return render_template("preview_template.html", template=template, fields=fields)


def _generate_final_certificate_from_preview(user, template, preview_info):
    """
    Generate final certificate using preview_info stored in session.
    preview_info must contain:
      - 'field_values': dict of text values
      - 'asset_map': dict mapping field_name -> absolute saved file path (if uploaded)
    """
    field_values = preview_info.get("field_values", {}) if isinstance(preview_info, dict) else {}
    asset_map = preview_info.get("asset_map", {}) if isinstance(preview_info, dict) else {}

    base_image = get_base_image_for_template(template)
    if not base_image:
        raise RuntimeError("Template base image missing when generating final certificate.")

    fields = TemplateField.query.filter_by(template_id=template.id).all()

    # Compose using saved asset_map and field_values
    composed = compose_image_from_fields(base_image, fields, values=field_values, file_map=asset_map)

    # Save final to GENERATED_FOLDER
    generated_folder = getattr(Config, "GENERATED_FOLDER", "static/generated")
    os.makedirs(generated_folder, exist_ok=True)
    filename = (
        f"certificate_{user.id}_{template.id}_{int(datetime.utcnow().timestamp())}.png"
    )
    output_path = os.path.join(generated_folder, filename)
    composed.save(output_path)

    # Log transaction row (if not already logged by calling context)
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


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)


