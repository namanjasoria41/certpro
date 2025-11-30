from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    wallet_balance = db.Column(db.Float, default=0.0)

    # NEW – who referred this user (optional, for analytics)
    referred_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    referred_by = db.relationship('User', remote_side=[id], backref='referred_users')

    transactions = db.relationship('Transaction', backref='user', lazy=True)

class Template(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, default=0.0)
    image_path = db.Column(db.String(300), nullable=False)
    fields = db.relationship(
        'TemplateField',
        backref='template',
        lazy=True,
        cascade='all, delete-orphan'
    )

class TemplateField(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('template.id'), nullable=False)
    field_name = db.Column(db.String(100), nullable=False)
    field_type = db.Column(db.String(20), nullable=False)  # 'text' or 'image'
    x_position = db.Column(db.Integer, nullable=False)
    y_position = db.Column(db.Integer, nullable=False)

    # Text field properties
    font_size = db.Column(db.Integer)
    font_color = db.Column(db.String(20))

    # Image field properties
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    shape = db.Column(db.String(20))  # 'rect' or 'circle'

# NEW – referral code model
class ReferralCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)

    # Which user owns/shares this code
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    owner = db.relationship('User', backref='referral_codes')

    # How much wallet credit this code gives when used
    reward_amount = db.Column(db.Float, nullable=False, default=0.0)

    # How many times this code can be used (None = unlimited)
    max_uses = db.Column(db.Integer, nullable=True)
    used_count = db.Column(db.Integer, default=0)

    # Optional expiry
    expires_at = db.Column(db.DateTime, nullable=True)

    is_active = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

# NEW – log of each referral redemption
class ReferralRedemption(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    referral_code_id = db.Column(db.Integer, db.ForeignKey('referral_code.id'), nullable=False)
    referral_code = db.relationship('ReferralCode', backref='redemptions')

    redeemed_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    redeemed_by_user = db.relationship('User', backref='referral_redemptions')

    reward_amount = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)  # 'credit' or 'debit'
    description = db.Column(db.String(200))
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())
