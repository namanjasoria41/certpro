import os
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
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont, ImageOps
from sqlalchemy import inspect, text

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

app = Flask(__name__)
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


# Razorpay client
razorpay_client = razorpay.Client(
    auth=(Config.RAZORPAY_KEY_ID, Config.RAZORPAY_KEY_SECRET)
)

# Users ki photos ke liye upload limit (har request ke liye)
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024


def ensure_template_field_columns():
    """
    Purane database mein naye columns apne aap jod deta hai
    (db.create_all() purani table mein naye column nahi jodta).
    Kuch bhi delete nahi hota, sirf missing columns add hote hain.
    """
    wanted = {
        "width": "INTEGER",
        "height": "INTEGER",
        "font_size": "INTEGER",
        "font_color": "VARCHAR(20)",
        "font_family": "VARCHAR(60)",
        "align": "VARCHAR(10)",
        "is_bold": "BOOLEAN DEFAULT FALSE",
        "is_upper": "BOOLEAN DEFAULT FALSE",
        "shape": "VARCHAR(20)",
        "remove_bg": "VARCHAR(10)",
    }
    try:
        existing = {c["name"] for c in inspect(db.engine).get_columns("template_field")}
        for col, ddl in wanted.items():
            if col not in existing:
                with db.engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE template_field ADD COLUMN {col} {ddl}"))
                app.logger.info("Added column template_field.%s", col)
    except Exception as e:
        app.logger.error("Column check failed: %s", e)


# Create tables on startup (Flask 3-compatible)
with app.app_context():
    db.create_all()
    ensure_template_field_columns()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg"}


def allowed_file(filename: str) -> bool:
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS
    )


def generate_referral_code(length: int = 8) -> str:
    """Generate a unique referral code."""
    chars = string.ascii_uppercase + string.digits
    while True:
        code = "".join(random.choice(chars) for _ in range(length))
        if not ReferralCode.query.filter_by(code=code).first():
            return code


# --------------------------------------------------------------------------
# Poster rendering helpers
# --------------------------------------------------------------------------

# font ka naam -> (regular file, bold file), static/fonts folder mein
FONT_FILES = {
    "Poppins": ("Poppins-Regular.ttf", "Poppins-Bold.ttf"),
    "Rajdhani": ("Rajdhani-Regular.ttf", "Rajdhani-Bold.ttf"),
    "Hind": ("Hind-Regular.ttf", "Hind-Bold.ttf"),
    "Mukta": ("Mukta-Regular.ttf", "Mukta-Bold.ttf"),
    "Kalam": ("Kalam-Regular.ttf", "Kalam-Bold.ttf"),
    "Bebas Neue": ("BebasNeue-Regular.ttf", "BebasNeue-Regular.ttf"),
    "Anton": ("Anton-Regular.ttf", "Anton-Regular.ttf"),
    "Pacifico": ("Pacifico-Regular.ttf", "Pacifico-Regular.ttf"),
    "Lobster": ("Lobster-Regular.ttf", "Lobster-Regular.ttf"),
    "Great Vibes": ("GreatVibes-Regular.ttf", "GreatVibes-Regular.ttf"),
    "Yatra One": ("YatraOne-Regular.ttf", "YatraOne-Regular.ttf"),
    "Rozha One": ("RozhaOne-Regular.ttf", "RozhaOne-Regular.ttf"),
}
DEFAULT_FONT = "Poppins"


@lru_cache(maxsize=256)
def load_font(family: str, bold: bool, size: int):
    files = FONT_FILES.get(family) or FONT_FILES[DEFAULT_FONT]
    fname = files[1] if bold else files[0]
    for path in (os.path.join(Config.STATIC_FOLDER, "fonts", fname), Config.FONT_PATH):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def shape_mask(w: int, h: int, shape: str) -> Image.Image:
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    if shape == "circle":
        d.ellipse((0, 0, w - 1, h - 1), fill=255)
    elif shape == "round":
        d.rounded_rectangle((0, 0, w - 1, h - 1), radius=int(min(w, h) * 0.08), fill=255)
    else:
        d.rectangle((0, 0, w, h), fill=255)
    return mask


def paste_photo(base: Image.Image, file_storage, field) -> None:
    """User ki photo ko field ke box mein cover-fit karke lagata hai."""
    w, h = int(field.width or 200), int(field.height or 200)
    im = Image.open(file_storage.stream)
    im = ImageOps.exif_transpose(im).convert("RGBA")

    scale = max(w / im.width, h / im.height)
    nw, nh = max(w, round(im.width * scale)), max(h, round(im.height * scale))
    im = im.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    im = im.crop((left, top, left + w, top + h))

    mask = shape_mask(w, h, field.shape or "rect")
    alpha = Image.composite(im.getchannel("A"), Image.new("L", (w, h), 0), mask)
    im.putalpha(alpha)
    base.paste(im, (int(field.x_position), int(field.y_position)), im)


def draw_field_text(draw: ImageDraw.ImageDraw, text_value: str, field) -> None:
    """Text ko box ke andar fit karke, align ke hisaab se likhta hai."""
    text_value = (text_value or "").strip()
    if not text_value:
        return
    if field.is_upper:
        text_value = text_value.upper()

    x, y = int(field.x_position), int(field.y_position)
    w, h = int(field.width or 400), int(field.height or 60)
    family = field.font_family or DEFAULT_FONT
    bold = bool(field.is_bold)

    size = int(field.font_size or h * 0.85)
    font = load_font(family, bold, size)
    while size > 8 and draw.textlength(text_value, font=font) > w:
        size -= 2
        font = load_font(family, bold, size)

    align = field.align or "left"
    if align == "center":
        tx, anchor = x + w / 2, "mm"
    elif align == "right":
        tx, anchor = x + w, "rm"
    else:
        tx, anchor = x, "lm"
    draw.text((tx, y + h / 2), text_value, fill=field.font_color or "#000000", font=font, anchor=anchor)


def field_to_dict(f) -> dict:
    return {
        "id": f.id,
        "field_name": f.field_name,
        "field_type": f.field_type,
        "x_position": f.x_position or 0,
        "y_position": f.y_position or 0,
        "width": f.width or (200 if f.field_type == "image" else 400),
        "height": f.height or (200 if f.field_type == "image" else 60),
        "font_size": f.font_size or 0,
        "font_color": f.font_color or "#000000",
        "font_family": f.font_family or DEFAULT_FONT,
        "align": f.align or "left",
        "is_bold": bool(f.is_bold),
        "is_upper": bool(f.is_upper),
        "shape": f.shape or "rect",
        "remove_bg": f.remove_bg if f.remove_bg in ("always", "optional", "off") else "optional",
    }


# --------------------------------------------------------------------------
# Auth routes
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
            existing_email = User.query.filter_by(email=email).first()
            if existing_email:
                flash("An account with this email already exists. Please log in.", "warning")
                return redirect(url_for("login"))

        # Check existing by phone
        if phone:
            existing_phone = User.query.filter_by(phone=phone).first()
            if existing_phone:
                flash("An account with this mobile number already exists. Please log in.", "warning")
                return redirect(url_for("login"))

        hashed_password = generate_password_hash(password)
        user = User(email=email or None, phone=phone or None, password=hashed_password)

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
                    # Valid referral
                    user.referred_by = rc.owner
                    # Credit wallet of the new user
                    user.wallet_balance += Config.REFERRAL_NEW_USER_BONUS

                    # Create a referral redemption entry
                    redemption = ReferralRedemption(
                        referral_code=rc,
                        redeemed_by_user=user,
                        reward_amount=Config.REFERRAL_OWNER_BONUS,
                    )

                    # Increase owner wallet balance
                    rc.owner.wallet_balance += Config.REFERRAL_OWNER_BONUS
                    rc.used_count += 1

                    db.session.add(redemption)
            else:
                flash("Invalid or inactive referral code.", "warning")

        db.session.add(user)
        db.session.commit()

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
            user = User.query.filter_by(email=identifier.lower()).first()
        else:
            # Treat as phone
            user = User.query.filter_by(phone=identifier).first()

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

        user = User.query.filter_by(email=email).first()
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
    data = request.form

    params_dict = {
        "razorpay_order_id": data.get("razorpay_order_id"),
        "razorpay_payment_id": data.get("razorpay_payment_id"),
        "razorpay_signature": data.get("razorpay_signature"),
    }

    try:
        razorpay_client.utility.verify_payment_signature(params_dict)
    except SignatureVerificationError:
        flash(
            "Payment verification failed. If money was deducted, contact support.",
            "danger",
        )
        return redirect(url_for("wallet"))

    amount = session.pop("wallet_topup_amount", None)
    session_order_id = session.pop("wallet_order_id", None)

    if not amount or session_order_id != params_dict["razorpay_order_id"]:
        flash(
            "Payment verified but session mismatched or expired. Contact support.",
            "warning",
        )
        return redirect(url_for("wallet"))

    # Credit wallet
    current_user.wallet_balance += amount
    transaction = Transaction(
        user_id=current_user.id,
        amount=amount,
        transaction_type="credit",
        description="Wallet recharge via Razorpay",
    )
    db.session.add(transaction)
    db.session.commit()

    flash(f"Payment successful! Wallet recharged with ₹{amount:.2f}", "success")
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

    templates = Template.query.order_by(Template.id.desc()).all()
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
        price = float(request.form.get("price") or 0)

        image_file = request.files.get("image")
        if not image_file or image_file.filename == "":
            flash("Image file is required.", "danger")
            return redirect(url_for("admin_new_template"))

        if not allowed_file(image_file.filename):
            flash("Only JPG, JPEG, PNG allowed.", "danger")
            return redirect(url_for("admin_new_template"))

        filename = secure_filename(image_file.filename)

        save_dir = Config.TEMPLATE_FOLDER
        os.makedirs(save_dir, exist_ok=True)

        save_path = os.path.join(save_dir, filename)
        image_file.save(save_path)

        template = Template(
            name=name,
            category=category,
            price=price,
            image_path=filename,  # store only filename
        )

        db.session.add(template)
        db.session.commit()

        flash("Template added successfully.", "success")
        return redirect(url_for("admin_templates"))

    return render_template("admin_new_template.html")


@app.route("/admin/template/<int:template_id>/edit", methods=["GET", "POST"])
@login_required
def admin_edit_template(template_id):
    # Only admin can edit
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

        db.session.commit()

        flash("Template updated successfully.", "success")
        return redirect(url_for("admin_templates"))

    # GET request → show form
    return render_template("admin_edit_template.html", template=template)


@app.route("/admin/template/<int:template_id>/delete", methods=["POST"])
@login_required
def admin_delete_template(template_id):
    # Only admin can delete
    if not getattr(current_user, "is_admin", False):
        flash("Access denied.", "danger")
        return redirect(url_for("index"))

    template = Template.query.get_or_404(template_id)

    # Delete all fields for this template
    TemplateField.query.filter_by(template_id=template.id).delete()

    # Delete the image file if it exists
    if template.image_path:
        image_path = os.path.join(Config.TEMPLATE_FOLDER, template.image_path)
        try:
            if os.path.exists(image_path):
                os.remove(image_path)
        except Exception as e:
            app.logger.warning(f"Failed to delete template image {image_path}: {e}")

    db.session.delete(template)
    db.session.commit()

    flash(f"Template '{template.name}' deleted successfully.", "success")
    return redirect(url_for("admin_templates"))


@app.route("/admin/template/<int:template_id>/builder")
@login_required
def admin_template_builder(template_id):
    if not getattr(current_user, "is_admin", False):
        flash("Access denied.", "danger")
        return redirect(url_for("index"))

    template = Template.query.get_or_404(template_id)
    fields = TemplateField.query.filter_by(template_id=template.id).order_by(TemplateField.id).all()
    return render_template(
        "admin_template_builder.html",
        template=template,
        fields_json=[field_to_dict(f) for f in fields],
        font_names=list(FONT_FILES.keys()),
    )


@app.route("/admin/template/<int:template_id>/fields", methods=["POST"])
@login_required
def admin_save_fields(template_id):
    """Builder ke saare fields ek saath save karta hai (purane replace ho jaate hain)."""
    if not getattr(current_user, "is_admin", False):
        return jsonify({"ok": False, "error": "Access denied"}), 403

    template = Template.query.get_or_404(template_id)
    data = request.get_json(silent=True) or {}
    items = data.get("fields", [])

    def to_int(v, default=0):
        try:
            return int(round(float(v)))
        except (TypeError, ValueError):
            return default

    new_fields = []
    for it in items:
        ftype = it.get("field_type") if it.get("field_type") in ("text", "image") else "text"
        name = (it.get("field_name") or "").strip() or ("Photo" if ftype == "image" else "Text")
        family = it.get("font_family") if it.get("font_family") in FONT_FILES else DEFAULT_FONT
        align = it.get("align") if it.get("align") in ("left", "center", "right") else "left"
        shape = it.get("shape") if it.get("shape") in ("rect", "round", "circle") else "rect"
        color = it.get("font_color") or "#000000"
        if not (isinstance(color, str) and color.startswith("#") and len(color) in (4, 7)):
            color = "#000000"
        new_fields.append(
            TemplateField(
                template_id=template.id,
                field_name=name[:100],
                field_type=ftype,
                x_position=max(0, to_int(it.get("x_position"))),
                y_position=max(0, to_int(it.get("y_position"))),
                width=max(5, to_int(it.get("width"), 200)),
                height=max(5, to_int(it.get("height"), 60)),
                font_size=max(0, to_int(it.get("font_size"))),
                font_color=color,
                font_family=family,
                align=align,
                is_bold=bool(it.get("is_bold")),
                is_upper=bool(it.get("is_upper")),
                shape=shape,
                remove_bg=(it.get("remove_bg") if it.get("remove_bg") in ("always", "optional", "off") else "optional"),
            )
        )

    try:
        TemplateField.query.filter_by(template_id=template.id).delete()
        db.session.add_all(new_fields)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.error("Saving fields failed: %s", e)
        return jsonify({"ok": False, "error": "Save failed"}), 500

    return jsonify({"ok": True, "count": len(new_fields)})


# --------------------------------------------------------------------------
# Admin: Referral Codes
# --------------------------------------------------------------------------

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

    owner = User.query.filter_by(email=owner_email).first()
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


# --------------------------------------------------------------------------
# Public routes: index, category, fill template, etc.
# --------------------------------------------------------------------------

@app.route("/")
def index():
    # If user is not logged in, send them to login page first
    if not current_user.is_authenticated:
        return redirect(url_for("login"))

    # If logged in, show the main template list
    templates = Template.query.order_by(Template.id.desc()).all()
    categories = sorted(set(t.category for t in templates if t.category))
    return render_template("index.html", templates=templates, categories=categories)



@app.route("/category/<category_name>")
def category(category_name):
    templates = Template.query.filter_by(category=category_name).all()
    return render_template("category.html", templates=templates, category=category_name)


@app.route("/template/<int:template_id>/fill", methods=["GET", "POST"])
@login_required
def fill_template(template_id):
    template = Template.query.get_or_404(template_id)
    fields = TemplateField.query.filter_by(template_id=template.id).order_by(TemplateField.id).all()
    wants_json = request.headers.get("X-Requested-With") == "fetch"

    if request.method == "POST":
        def fail(msg, code=400, endpoint=None):
            if wants_json:
                return jsonify({"ok": False, "error": msg}), code
            flash(msg, "danger")
            return redirect(url_for(endpoint or "fill_template", template_id=template.id))

        price = template.price or 0
        if current_user.wallet_balance < price:
            if wants_json:
                return jsonify({"ok": False, "error": "Wallet balance kam hai. Pehle paise add karo."}), 402
            flash("Insufficient wallet balance. Please add money first.", "danger")
            return redirect(url_for("wallet"))

        base_image_path = os.path.join(Config.TEMPLATE_FOLDER, template.image_path)
        try:
            base_image = Image.open(base_image_path).convert("RGBA")
        except Exception:
            return fail("Poster ki image nahi mili.", 500)

        try:
            # 1) photos
            for field in fields:
                if field.field_type != "image":
                    continue
                up = request.files.get(f"f_{field.id}")
                if up and up.filename:
                    paste_photo(base_image, up, field)

            # 2) text (photo ke upar)
            draw = ImageDraw.Draw(base_image)
            for field in fields:
                if field.field_type == "text":
                    draw_field_text(draw, request.form.get(f"f_{field.id}", ""), field)
        except Exception as e:
            app.logger.error("Poster render failed: %s", e)
            return fail("Poster nahi ban paya. Photo JPG ya PNG mein try karo.", 400)

        os.makedirs(Config.GENERATED_FOLDER, exist_ok=True)
        filename = (
            f"certificate_{current_user.id}_{template.id}_"
            f"{int(datetime.utcnow().timestamp())}.png"
        )
        output_path = os.path.join(Config.GENERATED_FOLDER, filename)
        base_image.convert("RGB").save(output_path, "PNG")

        # Poster ban gaya, ab wallet se paise kaato
        current_user.wallet_balance -= price
        db.session.add(
            Transaction(
                user_id=current_user.id,
                amount=price,
                transaction_type="debit",
                description=f"Certificate purchase - {template.name}",
            )
        )
        db.session.commit()

        if wants_json:
            return jsonify(
                {
                    "ok": True,
                    "view_url": url_for("view_certificate", filename=filename),
                    "download_url": url_for("view_certificate", filename=filename, download=1),
                    "balance": round(current_user.wallet_balance, 2),
                }
            )
        flash("Certificate generated successfully.", "success")
        return redirect(url_for("view_certificate", filename=filename))

    return render_template(
        "fill_template.html",
        template=template,
        fields_json=[field_to_dict(f) for f in fields],
    )


@app.route("/generated/<filename>")
@login_required
def view_certificate(filename):
    as_attachment = request.args.get("download") == "1"
    return send_from_directory(
        Config.GENERATED_FOLDER,
        filename,
        as_attachment=as_attachment,
        download_name="poster.png" if as_attachment else None,
    )


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)
