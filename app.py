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
from PIL import Image, ImageDraw, ImageFont

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

# Create tables on startup (Flask 3-compatible)
with app.app_context():
    db.create_all()


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


@app.route("/admin/template/<int:template_id>/builder", methods=["GET", "POST"])
@login_required
def admin_template_builder(template_id):
    if not getattr(current_user, "is_admin", False):
        flash("Access denied.", "danger")
        return redirect(url_for("index"))

    template = Template.query.get_or_404(template_id)

    if request.method == "POST":
        data = request.get_json()
        fields = data.get("fields", [])

        # Clear existing fields
        TemplateField.query.filter_by(template_id=template.id).delete()

        for field_data in fields:
            field = TemplateField(
                template_id=template.id,
                name=field_data.get("name", ""),
                x=field_data.get("x", 0),
                y=field_data.get("y", 0),
                font_size=field_data.get("font_size", 24),
                color=field_data.get("color", "#000000"),
                align=field_data.get("align", "left"),
            )
            db.session.add(field)

        db.session.commit()
        return jsonify({"status": "success"})

    fields = TemplateField.query.filter_by(template_id=template.id).all()
    return render_template(
        "admin_template_builder.html",
        template=template,
        fields=fields,
    )


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
    fields = TemplateField.query.filter_by(template_id=template.id).all()

    if request.method == "POST":
        if current_user.wallet_balance < template.price:
            flash("Insufficient wallet balance. Please add money first.", "danger")
            return redirect(url_for("wallet"))

        # Collect user-entered values
        field_values = {field.name: request.form.get(field.name, "") for field in fields}

        # Open base image
        base_image_path = os.path.join(Config.TEMPLATE_FOLDER, template.image_path)
        base_image = Image.open(base_image_path).convert("RGBA")

        draw = ImageDraw.Draw(base_image)

        for field in fields:
            text = field_values.get(field.name, "")
            color = field.color or "#000000"
            font_size = field.font_size or 24

            try:
                font = ImageFont.truetype(Config.FONT_PATH, font_size)
            except Exception:
                font = ImageFont.load_default()

            text_bbox = draw.textbbox((0, 0), text, font=font)
            text_width = text_bbox[2] - text_bbox[0]

            x = field.x
            y = field.y

            if field.align == "center":
                x -= text_width // 2
            elif field.align == "right":
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
# Preview + Purchase flow (Option A)
# ---------------------------

@app.route("/template/<int:template_id>/preview", methods=["GET", "POST"])
@login_required
def preview_template(template_id):
    """
    Show a form where user enters field values and generate a temporary preview image (no charge).
    GET: render form
    POST: generate preview image and show it with pay/wallet options
    """
    template = Template.query.get_or_404(template_id)
    fields = TemplateField.query.filter_by(template_id=template.id).all()

    if request.method == "POST":
        # collect field values
        field_values = {field.name: request.form.get(field.name, "") for field in fields}

        # open base image and draw text (same as fill_template but saved to PREVIEW_FOLDER)
        base_image_path = os.path.join(Config.TEMPLATE_FOLDER, template.image_path)
        base_image = Image.open(base_image_path).convert("RGBA")
        draw = ImageDraw.Draw(base_image)

        for field in fields:
            text = field_values.get(field.name, "")
            color = field.color or "#000000"
            font_size = field.font_size or 24

            try:
                font = ImageFont.truetype(Config.FONT_PATH, font_size)
            except Exception:
                font = ImageFont.load_default()

            text_bbox = draw.textbbox((0, 0), text, font=font)
            text_width = text_bbox[2] - text_bbox[0]

            x = field.x
            y = field.y

            if field.align == "center":
                x -= text_width // 2
            elif field.align == "right":
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


@app.route("/template/<int:template_id>/purchase", methods=["POST"])
@login_required
def purchase_template(template_id):
    """
    Create a Razorpay order for this template price and render payment page (or let user pay from wallet).
    Expects that session['preview_info'] exists and corresponds to this template.
    """
    template = Template.query.get_or_404(template_id)

    # confirm correct preview exists in session
    preview_info = session.get("preview_info")
    if not preview_info or int(preview_info.get("template_id", 0)) != template.id:
        flash("Preview missing or expired. Please re-generate preview.", "warning")
        return redirect(url_for("preview_template", template_id=template.id))

    # If user selected wallet payment (form includes pay_with_wallet)
    if request.form.get("pay_with_wallet"):
        # check balance
        if current_user.wallet_balance < (template.price or 0):
            flash("Insufficient wallet balance. Please add money first.", "danger")
            return redirect(url_for("wallet"))

        # Deduct from wallet
        current_user.wallet_balance -= template.price
        # Generate final certificate and record transaction
        filename = _generate_final_certificate_from_preview(current_user, template, preview_info)

        # Record debit transaction
        transaction = Transaction(
            user_id=current_user.id,
            amount=template.price,
            transaction_type="debit",
            description=f"Certificate purchase - {template.name}",
        )
        db.session.add(transaction)
        db.session.commit()

        # Clear preview info
        session.pop("preview_info", None)

        flash("Purchase successful. Certificate generated.", "success")
        return redirect(url_for("view_certificate", filename=filename))

    # Otherwise create Razorpay order
    amount_paise = int((template.price or 0) * 100)
    order = razorpay_client.order.create(
        {
            "amount": amount_paise,
            "currency": "INR",
            "payment_capture": "1",
            "notes": {
                "purpose": "template_purchase",
                "user_id": str(current_user.id),
                "template_id": str(template.id),
            },
        }
    )

    # store order and preview info in session for verification step
    session["purchase_order_id"] = order["id"]

    # Render a payment page that posts to /payment/verify (existing route)
    return render_template(
        "purchase_payment.html",
        razorpay_key_id=Config.RAZORPAY_KEY_ID,
        razorpay_order_id=order["id"],
        amount=template.price,
        amount_paise=amount_paise,
        template=template,
    )


def _generate_final_certificate_from_preview(user, template, preview_info):
    """
    Helper: create the final generated certificate using preview_info's field_values,
    save final to GENERATED_FOLDER, deduct wallet if needed, and log transaction.
    """
    field_values = preview_info.get("field_values", {})

    base_image_path = os.path.join(Config.TEMPLATE_FOLDER, template.image_path)
    base_image = Image.open(base_image_path).convert("RGBA")
    draw = ImageDraw.Draw(base_image)

    fields = TemplateField.query.filter_by(template_id=template.id).all()
    for field in fields:
        text = field_values.get(field.name, "")
        color = field.color or "#000000"
        font_size = field.font_size or 24
        try:
            font = ImageFont.truetype(Config.FONT_PATH, font_size)
        except Exception:
            font = ImageFont.load_default()

        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        x = field.x
        y = field.y
        if field.align == "center":
            x -= text_width // 2
        elif field.align == "right":
            x -= text_width
        draw.text((x, y), text, fill=color, font=font)

    os.makedirs(Config.GENERATED_FOLDER, exist_ok=True)
    filename = (
        f"certificate_{user.id}_{template.id}_{int(datetime.utcnow().timestamp())}.png"
    )
    output_path = os.path.join(Config.GENERATED_FOLDER, filename)
    base_image.save(output_path)

    # Log transaction row (if not already logged by calling context)
    transaction = Transaction(
        user_id=user.id,
        amount=template.price,
        transaction_type="debit",
        description=f"Certificate purchase - {template.name}",
    )
    db.session.add(transaction)
    db.session.commit()

    return filename



# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)



