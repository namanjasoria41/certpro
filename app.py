import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image, ImageDraw, ImageFont, ImageOps
from config import Config
from models import db, User, Template, TemplateField, Transaction, ReferralCode, ReferralRedemption
import json
import string
import random
from datetime import datetime

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def generate_referral_code(length=8):
    chars = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(random.choices(chars, k=length))
        if not ReferralCode.query.filter_by(code=code).first():
            return code


def validate_referral_code(code_str):
    ref = ReferralCode.query.filter_by(code=code_str, is_active=True).first()
    if not ref:
        return None, "Invalid referral code"

    if ref.expires_at and ref.expires_at < datetime.utcnow():
        return None, "Referral code expired"

    if ref.max_uses is not None and ref.used_count >= ref.max_uses:
        return None, "Referral code usage limit reached"

    return ref, None


def redeem_referral_code_for_user(referral_code, user):
    existing = ReferralRedemption.query.filter_by(
        referral_code_id=referral_code.id,
        redeemed_by_user_id=user.id
    ).first()
    if existing:
        return False, "You have already used this referral code"

    reward = referral_code.reward_amount or 0.0
    user.wallet_balance = (user.wallet_balance or 0.0) + reward

    referral_code.used_count += 1

    redemption = ReferralRedemption(
        referral_code_id=referral_code.id,
        redeemed_by_user_id=user.id,
        reward_amount=reward
    )

    tx = Transaction(
        user_id=user.id,
        amount=reward,
        transaction_type='credit',
        description=f"Referral reward via code {referral_code.code}"
    )

    db.session.add(redemption)
    db.session.add(tx)
    db.session.commit()

    # CURRENCY CHANGED TO ₹
    return True, f"₹{reward:.2f} added to your wallet via referral."


# Ensure directories exist
os.makedirs(app.config['TEMPLATE_FOLDER'], exist_ok=True)
os.makedirs(app.config['GENERATED_FOLDER'], exist_ok=True)

# Initialize database and default admin
with app.app_context():
    db.create_all()
    if not User.query.filter_by(email='admin@example.com').first():
        admin = User(
            email='admin@example.com',
            password=generate_password_hash('admin123'),
            is_admin=True,
            wallet_balance=0.0
        )
        db.session.add(admin)
        db.session.commit()


# Routes
@app.route('/')
def index():
    # NEW: redirect to login first if user not logged in
    if not current_user.is_authenticated:
        return redirect(url_for('login'))

    categories = db.session.query(Template.category).distinct().all()
    categories = [c[0] for c in categories]
    templates = Template.query.all()
    return render_template('index.html', categories=categories, templates=templates)


@app.route('/category/<category>')
def category(category):
    templates = Template.query.filter_by(category=category).all()
    return render_template('category.html', category=category, templates=templates)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        referral_code_str = request.form.get('referral_code')

        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'danger')
            return redirect(url_for('register'))

        user = User(
            email=email,
            password=generate_password_hash(password),
            is_admin=False,
            wallet_balance=0.0
        )

        if referral_code_str:
            ref, err = validate_referral_code(referral_code_str.strip())
            if err:
                flash(err, 'warning')
                db.session.add(user)
            else:
                user.referred_by_id = ref.owner_id
                db.session.add(user)
                db.session.flush()
                ok, msg = redeem_referral_code_for_user(ref, user)
                flash(msg, 'success' if ok else 'warning')
        else:
            db.session.add(user)

        db.session.commit()

        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash('Logged in successfully.', 'success')
            return redirect(url_for('index'))

        flash('Invalid email or password', 'danger')

    return render_template('login.html')


# NEW: Forgot Password route
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not email or not new_password or not confirm_password:
            flash('Please fill all fields.', 'warning')
            return redirect(url_for('forgot_password'))

        if new_password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('forgot_password'))

        user = User.query.filter_by(email=email).first()
        if not user:
            flash('No account found with that email.', 'danger')
            return redirect(url_for('forgot_password'))

        # DEMO-ONLY reset: no email verification
        user.password = generate_password_hash(new_password)
        db.session.commit()

        flash('Password reset successful! You can now log in with your new password.', 'success')
        return redirect(url_for('login'))

    return render_template('forgot_password.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('index'))


@app.route('/wallet', methods=['GET', 'POST'])
@login_required
def wallet():
    if request.method == 'POST':
        try:
            amount = float(request.form.get('amount'))
        except (TypeError, ValueError):
            flash('Invalid amount.', 'danger')
            return redirect(url_for('wallet'))

        if amount <= 0:
            flash('Amount must be greater than zero.', 'danger')
            return redirect(url_for('wallet'))

        current_user.wallet_balance += amount
        transaction = Transaction(
            user_id=current_user.id,
            amount=amount,
            transaction_type='credit',
            description='Wallet recharge'
        )
        db.session.add(transaction)
        db.session.commit()

        # CURRENCY CHANGED TO ₹
        flash(f'Wallet recharged with ₹{amount:.2f}', 'success')
        return redirect(url_for('wallet'))

    transactions = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.timestamp.desc()).all()
    return render_template('wallet.html', transactions=transactions)


# Admin Routes
@app.route('/admin/templates')
@login_required
def admin_templates():
    if not current_user.is_admin:
        flash('Access denied', 'danger')
        return redirect(url_for('index'))

    templates = Template.query.all()
    return render_template('admin_templates.html', templates=templates)


@app.route('/admin/templates/new', methods=['GET', 'POST'])
@login_required
def admin_new_template():
    if not current_user.is_admin:
        flash('Access denied', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        name = request.form.get('name')
        category = request.form.get('category')
        price = float(request.form.get('price', 0))
        file = request.files.get('template_image')

        if file and file.filename:
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['TEMPLATE_FOLDER'], filename)
            file.save(filepath)

            template = Template(
                name=name,
                category=category,
                price=price,
                image_path=filename
            )
            db.session.add(template)
            db.session.commit()

            flash('Template created successfully!', 'success')
            return redirect(url_for('admin_template_builder', template_id=template.id))

    return render_template('admin_new_template.html')


@app.route('/admin/templates/<int:template_id>/builder')
@login_required
def admin_template_builder(template_id):
    if not current_user.is_admin:
        flash('Access denied', 'danger')
        return redirect(url_for('index'))

    template = Template.query.get_or_404(template_id)
    fields = TemplateField.query.filter_by(template_id=template_id).all()
    return render_template('admin_template_builder.html', template=template, fields=fields)


@app.route('/admin/templates/<int:template_id>/fields', methods=['POST'])
@login_required
def add_template_field(template_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Access denied'}), 403

    data = request.json
    field = TemplateField(
        template_id=template_id,
        field_name=data['field_name'],
        field_type=data['field_type'],
        x_position=data['x_position'],
        y_position=data['y_position'],
        font_size=data.get('font_size'),
        font_color=data.get('font_color'),
        width=data.get('width'),
        height=data.get('height'),
        shape=data.get('shape')
    )
    db.session.add(field)
    db.session.commit()

    return jsonify({'success': True, 'field_id': field.id})


@app.route('/admin/templates/<int:template_id>/fields/<int:field_id>', methods=['DELETE'])
@login_required
def delete_template_field(template_id, field_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Access denied'}), 403

    field = TemplateField.query.get_or_404(field_id)
    db.session.delete(field)
    db.session.commit()

    return jsonify({'success': True})


@app.route('/admin/referrals', methods=['GET', 'POST'])
@login_required
def admin_referrals():
    if not current_user.is_admin:
        flash('Access denied', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        user_email = request.form.get('user_email')
        reward_amount = float(request.form.get('reward_amount') or 0)
        max_uses = request.form.get('max_uses')
        expires_at = request.form.get('expires_at')

        user = User.query.filter_by(email=user_email).first()
        if not user:
            flash('User not found', 'danger')
            return redirect(url_for('admin_referrals'))

        max_uses_val = int(max_uses) if max_uses else None
        expires_dt = datetime.strptime(expires_at, '%Y-%m-%d') if expires_at else None

        code_str = generate_referral_code()

        ref = ReferralCode(
            code=code_str,
            owner_id=user.id,
            reward_amount=reward_amount,
            max_uses=max_uses_val,
            expires_at=expires_dt,
            is_active=True
        )
        db.session.add(ref)
        db.session.commit()

        flash(f'Referral code {code_str} created for {user.email}', 'success')
        return redirect(url_for('admin_referrals'))

    codes = ReferralCode.query.order_by(ReferralCode.created_at.desc()).all()
    return render_template('admin_referrals.html', codes=codes)


# User Template Routes
@app.route('/templates/<int:template_id>', methods=['GET', 'POST'])
@login_required
def fill_template(template_id):
    template = Template.query.get_or_404(template_id)
    fields = TemplateField.query.filter_by(template_id=template_id).all()

    if request.method == 'POST':
        if current_user.wallet_balance < template.price:
            flash('Insufficient wallet balance. Please recharge your wallet.', 'danger')
            return redirect(url_for('wallet'))

        current_user.wallet_balance -= template.price
        transaction = Transaction(
            user_id=current_user.id,
            amount=template.price,
            transaction_type='debit',
            description=f'Purchase of template: {template.name}'
        )
        db.session.add(transaction)

        data = request.form.to_dict()
        image = Image.open(os.path.join(app.config['TEMPLATE_FOLDER'], template.image_path)).convert('RGBA')
        draw = ImageDraw.Draw(image)

        for field in fields:
            if field.field_type == 'text':
                text = data.get(field.field_name, '')
                font_path = os.path.join(os.path.dirname(__file__), 'static', 'fonts', 'arial.ttf')
                font = ImageFont.truetype(font_path, field.font_size or 40)
                draw.text((field.x_position, field.y_position), text, font=font, fill=field.font_color or 'black')
            elif field.field_type == 'image':
                if field.field_name in request.files:
                    file = request.files[field.field_name]
                    if file and file.filename:
                        user_image = Image.open(file.stream).convert('RGBA')
                        user_image = user_image.resize((field.width or 100, field.height or 100))

                        if field.shape == 'circle':
                            mask = Image.new('L', user_image.size, 0)
                            mask_draw = ImageDraw.Draw(mask)
                            mask_draw.ellipse((0, 0, user_image.size[0], user_image.size[1]), fill=255)
                            user_image = ImageOps.fit(user_image, mask.size, centering=(0.5, 0.5))
                            user_image.putalpha(mask)

                        image.paste(user_image, (field.x_position, field.y_position), user_image)

        output_filename = f"cert_{current_user.id}_{template.id}_{os.urandom(4).hex()}.png"
        output_path = os.path.join(app.config['GENERATED_FOLDER'], output_filename)
        image.save(output_path, 'PNG')

        db.session.commit()

        # CURRENCY CHANGED TO ₹
        flash(f'Certificate generated successfully! ₹{template.price:.2f} deducted from your wallet.', 'success')
        return redirect(url_for('view_certificate', filename=output_filename))

    return render_template('fill_template.html', template=template, fields=fields)


@app.route('/generated/<filename>')
@login_required
def view_certificate(filename):
    return send_from_directory(app.config['GENERATED_FOLDER'], filename)


if __name__ == '__main__':
    app.run(debug=True)
