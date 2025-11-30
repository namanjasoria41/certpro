import os
import json
import string
import random
from datetime import datetime

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
from PIL import Image, ImageDraw, ImageFont, ImageOps

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


# ------------------------------------------------------------------------------
# App / DB / Login setup
# ------------------------------------------------------------------------------

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# Razorpay client
razorpay_client = razorpay.Client(
    auth=(Config.RAZORPAY_KEY_ID, Config.RAZORPAY_KEY_SECRET)
)
# 🔧 Create tables once at startup (Flask 3 compatible)
with app.app_context():
    db.create_all()


# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------

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


def create_tables():
    db.create_all()


# ------------------------------------------------------------------------------
# Auth routes
# ------------------------------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        referral_code_input = request.form.get("referral_code", "").strip()

        if not email or not password:
            flash("Email and password are required.", "danger")
            return redirect(url_for("register"))

        existing = User.query.filter_by(email=email).first()
        if existing:
            flash("Email already registered. Please log in.", "warning")
            return redirect(url_for("login"))

        hashed_password = generate_password_hash(password)
        user = User(email=email, password=hashed_password)

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
                    user.wallet_balance += rc.reward_amount

                    # Log redemption
                    redemption = ReferralRedemption(
                        referral_code=rc,
                        redeemed_by_user=user,
                        reward_amount=rc.reward_amount,
                    )
                    db.session.add(redemption)

                    # Update referral code stats
                    rc.used_count += 1
                    if rc.max_uses is not None and rc.used_count >= rc.max_uses:
                        rc.is_active = False
            else:
                flash("Invalid referral code.", "warning")

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
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash("Logged in successfully.", "success")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("index"))
        else:
            flash("Invalid email or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
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


# ------------------------------------------------------------------------------
# Public / user routes
# ------------------------------------------------------------------------------

@app.route("/")
def index():
    # Distinct categories for the home page
    categories = (
        db.session.query(Template.category)
        .distinct()
        .order_by(Template.category.asc())
        .all()
    )
    categories = [c[0] for c in categories]
    return render_template("index.html", categories=categories)


@app.route("/category/<category>")
def category(category):
    templates = Template.query.filter_by(category=category).all()
    return render_template("category.html", category=category, templates=templates)


# ------------------------------------------------------------------------------
# Wallet + Razorpay integration
# ------------------------------------------------------------------------------

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

    if amount <= 0:
        flash("Amount must be greater than zero.", "danger")
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

    return render_template(
        "pay.html",
        razorpay_key_id=Config.RAZORPAY_KEY_ID,
        razorpay_order_id=order["id"],
        amount=amount,
        amount_paise=amount_paise,
        user=current_user,
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


# ------------------------------------------------------------------------------
# Admin: Templates management
# ------------------------------------------------------------------------------

@app.route("/admin/templates")
@login_required
def admin_templates():
    if not current_user.is_admin:
        flash("Access denied.", "danger")
        return redirect(url_for("index"))

    templates = Template.query.order_by(Template.created_at.desc()).all() if hasattr(Template, "created_at") else Template.query.all()
    return render_template("admin_templates.html", templates=templates)


@app.route("/admin/templates/new", methods=["GET", "POST"])
@login_required
def admin_new_template():
    if not current_user.is_admin:
        flash("Access denied.", "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()
        price_raw = request.form.get("price", "0").strip()
        bg_image = request.files.get("image")

        if not name or not category or not bg_image:
            flash("Name, category and image are required.", "danger")
            return redirect(url_for("admin_new_template"))

        try:
            price = float(price_raw)
        except ValueError:
            price = 0.0

        if not allowed_file(bg_image.filename):
            flash("Invalid image format. Use PNG/JPG/JPEG.", "danger")
            return redirect(url_for("admin_new_template"))

        filename = secure_filename(bg_image.filename)
        templates_folder = Config.TEMPLATE_FOLDER
        os.makedirs(templates_folder, exist_ok=True)
        save_path = os.path.join(templates_folder, filename)
        bg_image.save(save_path)

        template = Template(
            name=name,
            category=category,
            price=price,
            image_path=filename,
        )
        db.session.add(template)
        db.session.commit()

        flash("Template created. Now configure its fields.", "success")
        return redirect(url_for("admin_template_builder", template_id=template.id))

    return render_template("admin_new_template.html")


@app.route("/admin/templates/<int:template_id>/builder")
@login_required
def admin_template_builder(template_id):
    if not current_user.is_admin:
        flash("Access denied.", "danger")
        return redirect(url_for("index"))

    template = Template.query.get_or_404(template_id)
    fields = TemplateField.query.filter_by(template_id=template.id).all()
    return render_template(
        "admin_template_builder.html", template=template, fields=fields
    )


@app.route("/admin/templates/<int:template_id>/fields", methods=["POST"])
@login_required
def admin_add_field(template_id):
    if not current_user.is_admin:
        return jsonify({"error": "Unauthorized"}), 403

    template = Template.query.get_or_404(template_id)

    try:
        data = request.get_json() or {}
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    field_name = data.get("field_name", "").strip()
    field_type = data.get("field_type")
    x_position = data.get("x_position")
    y_position = data.get("y_position")
    font_size = data.get("font_size")
    font_color = data.get("font_color")
    width = data.get("width")
    height = data.get("height")
    shape = data.get("shape")

    if not field_name or not field_type or x_position is None or y_position is None:
        return jsonify({"error": "Missing required fields"}), 400

    field = TemplateField(
        template_id=template.id,
        field_name=field_name,
        field_type=field_type,
        x_position=int(x_position),
        y_position=int(y_position),
        font_size=int(font_size) if font_size else None,
        font_color=font_color,
        width=int(width) if width else None,
        height=int(height) if height else None,
        shape=shape,
    )
    db.session.add(field)
    db.session.commit()

    return jsonify({"message": "Field added", "field_id": field.id}), 201


@app.route(
    "/admin/templates/<int:template_id>/fields/<int:field_id>", methods=["DELETE"]
)
@login_required
def admin_delete_field(template_id, field_id):
    if not current_user.is_admin:
        return jsonify({"error": "Unauthorized"}), 403

    field = TemplateField.query.filter_by(
        id=field_id, template_id=template_id
    ).first_or_404()
    db.session.delete(field)
    db.session.commit()

    return jsonify({"message": "Field deleted"}), 200


# ------------------------------------------------------------------------------
# Admin: Referral codes
# ------------------------------------------------------------------------------

@app.route("/admin/referrals", methods=["GET", "POST"])
@login_required
def admin_referrals():
    if not current_user.is_admin:
        flash("Access denied.", "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        user_email = request.form.get("user_email", "").strip().lower()
        reward_amount_raw = request.form.get("reward_amount", "0").strip()
        max_uses_raw = request.form.get("max_uses", "").strip()
        expires_at_raw = request.form.get("expires_at", "").strip()

        owner = User.query.filter_by(email=user_email).first()
        if not owner:
            flash("No user found with that email.", "danger")
            return redirect(url_for("admin_referrals"))

        try:
            reward_amount = float(reward_amount_raw)
        except ValueError:
            reward_amount = 0.0

        max_uses = None
        if max_uses_raw:
            try:
                max_uses = int(max_uses_raw)
            except ValueError:
                max_uses = None

        expires_at = None
        if expires_at_raw:
            try:
                # Date input is YYYY-MM-DD
                expires_at = datetime.strptime(expires_at_raw, "%Y-%m-%d")
            except ValueError:
                expires_at = None

        code_str = generate_referral_code()

        rc = ReferralCode(
            code=code_str,
            owner=owner,
            reward_amount=reward_amount,
            max_uses=max_uses,
            expires_at=expires_at,
            is_active=True,
        )

        db.session.add(rc)
        db.session.commit()

        flash(f"Referral code {code_str} created successfully.", "success")
        return redirect(url_for("admin_referrals"))

    codes = ReferralCode.query.order_by(ReferralCode.created_at.desc()).all()
    return render_template("admin_referrals.html", codes=codes)


# ------------------------------------------------------------------------------
# Certificate generation
# ------------------------------------------------------------------------------

@app.route("/template/<int:template_id>/fill", methods=["GET", "POST"])
@login_required
def fill_template(template_id):
    template = Template.query.get_or_404(template_id)
    fields = TemplateField.query.filter_by(template_id=template.id).all()

    if request.method == "POST":
        # Check wallet balance
        if current_user.wallet_balance < template.price:
            flash("Insufficient balance. Please add money to your wallet.", "danger")
            return redirect(url_for("wallet"))

        # Load base image
        base_path = os.path.join(Config.TEMPLATE_FOLDER, template.image_path)
        if not os.path.exists(base_path):
            flash("Template image not found on server.", "danger")
            return redirect(url_for("category", category=template.category))

        base_image = Image.open(base_path).convert("RGBA")
        draw = ImageDraw.Draw(base_image)

        font_path = os.path.join("fonts", "Roboto.ttf")
        if not os.path.exists(font_path):
            font_path = None  # Pillow will fallback

        for field in fields:
            if field.field_type == "text":
                text_value = request.form.get(field.field_name, "").strip()
                if not text_value:
                    continue

                font_size = field.font_size or 36
                if font_path:
                    font = ImageFont.truetype(font_path, font_size)
                else:
                    font = ImageFont.load_default()

                color = field.font_color or "#000000"
                draw.text(
                    (field.x_position, field.y_position),
                    text_value,
                    fill=color,
                    font=font,
                )

            elif field.field_type == "image":
                file_obj = request.files.get(field.field_name)
                if not file_obj or file_obj.filename == "":
                    continue
                if not allowed_file(file_obj.filename):
                    continue

                img = Image.open(file_obj).convert("RGBA")
                w = field.width or img.width
                h = field.height or img.height
                img = img.resize((w, h))

                # Handle circle shape
                if field.shape == "circle":
                    mask = Image.new("L", (w, h), 0)
                    mask_draw = ImageDraw.Draw(mask)
                    mask_draw.ellipse((0, 0, w, h), fill=255)
                    base_image.paste(
                        img,
                        (field.x_position, field.y_position),
                        mask=mask,
                    )
                else:
                    base_image.paste(
                        img,
                        (field.x_position, field.y_position),
                        img,
                    )

        # Save generated certificate
        os.makedirs(Config.GENERATED_FOLDER, exist_ok=True)
        filename = f"certificate_{current_user.id}_{template.id}_{int(datetime.utcnow().timestamp())}.png"
        output_path = os.path.join(Config.GENERATED_FOLDER, filename)
        base_image.save(output_path)

        # Deduct wallet
        current_user.wallet_balance -= template.price
        transaction = Transaction(
            user_id=current_user.id,
            amount=template.price,
            transaction_type="debit",
            description=f"Certificate purchase - {template.name}",
        )
        db.session.add(transaction)
        db.session.commit()

        flash(
            f"Certificate generated successfully! ₹{template.price:.2f} deducted from your wallet.",
            "success",
        )
        return redirect(url_for("view_certificate", filename=filename))

    return render_template("fill_template.html", template=template, fields=fields)


@app.route("/generated/<filename>")
@login_required
def view_certificate(filename):
    return send_from_directory(Config.GENERATED_FOLDER, filename)


# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------

if __name__ == "__main__":
    # For local debug only; on Render/Gunicorn, Procfile is used.
    app.run(debug=True)

