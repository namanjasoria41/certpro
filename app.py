import os
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

from sqlalchemy.exc import ProgrammingError

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
        return None


def _ensure_template_image_exists_or_redirect(template):
    """
    Return absolute image path or None (and flash) if missing.
    """
    base_image_path = os.path.join(Config.TEMPLATE_FOLDER, template.image_path or "")
    if not os.path.exists(base_image_path):
        app.logger.error(f"Template image missing: {base_image_path} (template id {template.id})")
        flash("Base template image not found on server. Please contact admin or re-upload the template.", "danger")
        return None
    return base_image_path


def set_field_attr_safe(field_obj, attr_name, value):
    """
    Set attribute on a TemplateField object only if attribute exists on model.
    This lets us support different DB column naming conventions.
    """
    # TemplateField class may have attribute as InstrumentedAttribute on class
    if hasattr(TemplateField, attr_name):
        setattr(field_obj, attr_name, value)


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
        # If model doesn't have phone column, SQLAlchemy will ignore an unknown kwarg at init? if not, set after.
        try:
            user = User(email=email or None, phone=phone or None, password=hashed_password)
        except TypeError:
            # fallback — create without phone
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
                    # Valid referral
                    try:
                        user.referred_by = rc.owner
                        if hasattr(user, "wallet_balance"):
                            user.wallet_balance = (user.wallet_balance or 0.0) + getattr(Config, "REFERRAL_NEW_USER_BONUS", 0.0)
                    except Exception:
                        app.logger.exception("Failed to set referral on new user")

                    # Create a referral redemption entry
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

    # Delete the image file if it exists
    if template.image_path:
        image_path = os.path.join(Config.TEMPLATE_FOLDER, template.image_path)
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


# Compatibility adapter: older frontends post to /admin/templates/<id>/fields
@app.route("/admin/templates/<int:template_id>/fields", methods=["POST"])
@login_required
def admin_templates_fields_compat(template_id):
    return admin_template_builder(template_id)


# Admin template builder (robust, accepts JSON or form encoded)
@app.route("/admin/template/<int:template_id>/builder", methods=["GET", "POST"])
@login_required
def admin_template_builder(template_id):
    if not getattr(current_user, "is_admin", False):
        flash("Access denied.", "danger")
        return redirect(url_for("index"))

    template = Template.query.get_or_404(template_id)

    if request.method == "POST":
        # robust parsing
        try:
            if request.is_json:
                payload = request.get_json()
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

        # save fields defensively — support both naming conventions
        try:
            # remove old fields
            TemplateField.query.filter_by(template_id=template.id).delete()

            for fd in fields_list:
                # read values from fd with fallback names
                name = fd.get("name") or fd.get("field_name") or fd.get("key") or ""
                x = fd.get("x", fd.get("x_position", fd.get("left", 0))) or 0
                y = fd.get("y", fd.get("y_position", fd.get("top", 0))) or 0
                font_size = fd.get("font_size", fd.get("size", 24)) or 24
                color = fd.get("color", fd.get("font_color", "#000000")) or "#000000"
                align = fd.get("align", "left") or "left"

                # create model instance then set whichever attributes exist on model
                obj = TemplateField()
                set_field_attr_safe(obj, "template_id", template.id)
                set_field_attr_safe(obj, "name", name)
                set_field_attr_safe(obj, "field_name", name)
                set_field_attr_safe(obj, "x", int(x))
                set_field_attr_safe(obj, "x_position", int(x))
                set_field_attr_safe(obj, "y", int(y))
                set_field_attr_safe(obj, "y_position", int(y))
                set_field_attr_safe(obj, "font_size", int(font_size))
                set_field_attr_safe(obj, "font_color", color)
                set_field_attr_safe(obj, "color", color)
                set_field_attr_safe(obj, "align", align)

                db.session.add(obj)

            db.session.commit()
            return jsonify({"status": "ok"})
        except Exception:
            db.session.rollback()
            app.logger.exception("Failed saving template fields")
            return jsonify({"status": "error", "message": "Database error"}), 500

    # GET → render builder UI with fields normalized for JS
    fields = TemplateField.query.filter_by(template_id=template.id).all()
    normalized = []
    for f in fields:
        # try a number of attribute names
        name = getattr(f, "name", None) or getattr(f, "field_name", None) or ""
        x = getattr(f, "x", None)
        if x is None:
            x = getattr(f, "x_position", 0)
        y = getattr(f, "y", None)
    #    fallback for older names
        if y is None:
            y = getattr(f, "y_position", 0)
        font_size = getattr(f, "font_size", None) or getattr(f, "size", 24) or 24
        color = getattr(f, "color", None) or getattr(f, "font_color", None) or "#000000"
        align = getattr(f, "align", "left") or "left"

        normalized.append({
            "name": name,
            "x": int(x or 0),
            "y": int(y or 0),
            "font_size": int(font_size or 24),
            "color": color or "#000000",
            "align": align,
        })

    return render_template("admin_template_builder.html", template=template, fields=normalized)


# Admin helper: list missing template files
@app.route("/admin/templates/missing-files")
@login_required
def admin_templates_missing_files():
    if not getattr(current_user, "is_admin", False):
        flash("Access denied.", "danger")
        return redirect(url_for("index"))

    missing = []
    for t in Template.query.all():
        path = os.path.join(Config.TEMPLATE_FOLDER, t.image_path or "")
        if not os.path.exists(path):
            missing.append({"id": t.id, "name": t.name, "image_path": t.image_path})
    return render_template("admin_missing_templates.html", missing=missing)


# --------------------------------------------------------------------------
# Public routes: index, category, fill template, etc.
# --------------------------------------------------------------------------

@app.route("/")
def index():
    if not current_user.is_authenticated:
        return redirect(url_for("login"))

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
    fields = TemplateField.query.filter_by(template_id=template.id).all()

    if request.method == "POST":
        if current_user.wallet_balance < (template.price or 0):
            flash("Insufficient wallet balance. Please add money first.", "danger")
            return redirect(url_for("wallet"))

        # Collect user-entered values
        # handle both naming patterns
        field_values = {}
        for field in fields:
            key = getattr(field, "name", None) or getattr(field, "field_name", None)
            if not key:
                continue
            field_values[key] = request.form.get(key, "")

        base_image_path = _ensure_template_image_exists_or_redirect(template)
        if not base_image_path:
            return redirect(url_for("admin_templates") if getattr(current_user, "is_admin", False) else url_for("index"))

        base_image = Image.open(base_image_path).convert("RGBA")
        draw = ImageDraw.Draw(base_image)

        for field in fields:
            key = getattr(field, "name", None) or getattr(field, "field_name", None)
            if not key:
                continue
            text = field_values.get(key, "")
            color = getattr(field, "color", None) or getattr(field, "font_color", None) or "#000000"
            font_size = getattr(field, "font_size", None) or 24

            try:
                font = ImageFont.truetype(Config.FONT_PATH, int(font_size))
            except Exception:
                font = ImageFont.load_default()

            text_bbox = draw.textbbox((0, 0), text, font=font)
            text_width = text_bbox[2] - text_bbox[0]

            x = getattr(field, "x", None)
            if x is None:
                x = getattr(field, "x_position", 0)
            y = getattr(field, "y", None)
            if y is None:
                y = getattr(field, "y_position", 0)

            align = getattr(field, "align", "left") or "left"

            if align == "center":
                x -= text_width // 2
            elif align == "right":
                x -= text_width

            draw.text((x, y), text, fill=color, font=font)

        # Save generated certificate
        os.makedirs(Config.GENERATED_FOLDER, exist_ok=True)
        filename = (
            f"certificate_{current_user.id}_{template.id}_"
            f"{int(datetime.utcnow().timestamp())}.png"
        )
        output_path = os.path.join(Config.GENERATED_FOLDER, filename)
        base_image.save(output_path)

        # Deduct from wallet and log transaction
        current_user.wallet_balance -= template.price
        transaction = Transaction(
            user_id=current_user.id,
            amount=template.price,
            transaction_type="debit",
            description=f"Certificate purchase - {template.name}",
        )
        db.session.add(transaction)
        db.session.commit()

        flash("Certificate generated successfully.", "success")
        return redirect(url_for("view_certificate", filename=filename))

    return render_template("fill_template.html", template=template, fields=fields)


@app.route("/generated/<filename>")
@login_required
def view_certificate(filename):
    return send_from_directory(Config.GENERATED_FOLDER, filename)


# ---------------------------
# Preview + Purchase flow (kept largely as your previous implementation)
# ---------------------------

@app.route("/template/<int:template_id>/preview", methods=["GET", "POST"])
@login_required
def preview_template(template_id):
    template = Template.query.get_or_404(template_id)
    fields = TemplateField.query.filter_by(template_id=template.id).all()

    if request.method == "POST":
        # collect field values
        field_values = {}
        for field in fields:
            key = getattr(field, "name", None) or getattr(field, "field_name", None)
            if not key:
                continue
            field_values[key] = request.form.get(key, "")

        # open base image (defensive)
        base_image_path = _ensure_template_image_exists_or_redirect(template)
        if not base_image_path:
            return redirect(url_for("admin_templates") if getattr(current_user, "is_admin", False) else url_for("index"))

        base_image = Image.open(base_image_path).convert("RGBA")
        draw = ImageDraw.Draw(base_image)

        for field in fields:
            key = getattr(field, "name", None) or getattr(field, "field_name", None)
            if not key:
                continue
            text = field_values.get(key, "")
            color = getattr(field, "color", None) or getattr(field, "font_color", None) or "#000000"
            font_size = getattr(field, "font_size", None) or 24
            try:
                font = ImageFont.truetype(Config.FONT_PATH, int(font_size))
            except Exception:
                font = ImageFont.load_default()

            text_bbox = draw.textbbox((0, 0), text, font=font)
            text_width = text_bbox[2] - text_bbox[0]

            x = getattr(field, "x", None)
            if x is None:
                x = getattr(field, "x_position", 0)
            y = getattr(field, "y", None)
            if y is None:
                y = getattr(field, "y_position", 0)

            align = getattr(field, "align", "left") or "left"
            if align == "center":
                x -= text_width // 2
            elif align == "right":
                x -= text_width

            draw.text((x, y), text, fill=color, font=font)

        # Save preview
        os.makedirs(Config.PREVIEW_FOLDER, exist_ok=True)
        preview_filename = f"preview_{current_user.id}_{template.id}_{int(datetime.utcnow().timestamp())}.png"
        preview_path = os.path.join(Config.PREVIEW_FOLDER, preview_filename)
        base_image.save(preview_path)

        # Store preview info in session so we can generate final after payment
        session["preview_info"] = {
            "preview_filename": preview_filename,
            "field_values": field_values,
            "template_id": template.id,
        }

        # Render the preview view that shows image and payment options
        return render_template(
            "preview_template.html",
            template=template,
            fields=fields,
            preview_url=url_for("static", filename=f"previews/{preview_filename}"),
            preview_filename=preview_filename,
        )

    # GET -> show form
    return render_template("preview_template.html", template=template, fields=fields)


def _generate_final_certificate_from_preview(user, template, preview_info):
    field_values = preview_info.get("field_values", {})

    base_image_path = _ensure_template_image_exists_or_redirect(template)
    if not base_image_path:
        raise RuntimeError("Template base image missing when generating final certificate.")

    base_image = Image.open(base_image_path).convert("RGBA")
    draw = ImageDraw.Draw(base_image)

    fields = TemplateField.query.filter_by(template_id=template.id).all()
    for field in fields:
        key = getattr(field, "name", None) or getattr(field, "field_name", None)
        if not key:
            continue
        text = field_values.get(key, "")
        color = getattr(field, "color", None) or getattr(field, "font_color", None) or "#000000"
        font_size = getattr(field, "font_size", None) or 24
        try:
            font = ImageFont.truetype(Config.FONT_PATH, int(font_size))
        except Exception:
            font = ImageFont.load_default()

        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        x = getattr(field, "x", None)
        if x is None:
            x = getattr(field, "x_position", 0)
        y = getattr(field, "y", None)
        if y is None:
            y = getattr(field, "y_position", 0)

        align = getattr(field, "align", "left") or "left"
        if align == "center":
            x -= text_width // 2
        elif align == "right":
            x -= text_width

        draw.text((x, y), text, fill=color, font=font)

    os.makedirs(Config.GENERATED_FOLDER, exist_ok=True)
    filename = (
        f"certificate_{user.id}_{template.id}_{int(datetime.utcnow().timestamp())}.png"
    )
    output_path = os.path.join(Config.GENERATED_FOLDER, filename)
    base_image.save(output_path)

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

