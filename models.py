from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy import LargeBinary
from datetime import datetime

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=True)
    phone = db.Column(db.String(20), unique=True, nullable=True)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    wallet_balance = db.Column(db.Float, default=0.0)

    # Referral: who referred this user (optional)
    referred_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    referred_by = db.relationship("User", remote_side=[id], backref="referred_users")

    # relationships
    transactions = db.relationship("Transaction", backref="user", lazy=True)
    referral_codes = db.relationship("ReferralCode", backref="owner", lazy=True)
    referral_redemptions = db.relationship(
        "ReferralRedemption", backref="redeemed_by_user", lazy=True
    )

    def __repr__(self):
        return f"<User id={self.id} email={self.email} admin={self.is_admin}>"


class Template(db.Model):
    __tablename__ = "template"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100), nullable=True)
    price = db.Column(db.Float, default=0.0)

    # Local filesystem filename (legacy / optional)
    image_path = db.Column(db.String(500), nullable=True)

    # Store binary image in DB (bytea) so templates don't go missing on ephemeral storage
    image_data = db.Column(LargeBinary, nullable=True)
    image_mime = db.Column(db.String(120), nullable=True)

    # Optional: URL if you store image on S3/Cloudinary
    image_url = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    fields = db.relationship(
        "TemplateField",
        backref="template",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="TemplateField.id",
    )

    def __repr__(self):
        return f"<Template id={self.id} name={self.name}>"


class TemplateField(db.Model):
    """
    Single field on a template. Supports both text and image fields, and provides
    legacy alias properties (field_name, x_position, y_position) for compatibility.
    """

    __tablename__ = "template_field"

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey("template.id"), nullable=False)

    # Primary name (used in app code)
    name = db.Column(db.String(120), nullable=False)

    # Field type: 'text' or 'image'
    field_type = db.Column(db.String(20), default="text", nullable=False)

    # Coordinates & layout
    x = db.Column(db.Integer, nullable=False, default=0)
    y = db.Column(db.Integer, nullable=False, default=0)

    # Text-specific props
    font_size = db.Column(db.Integer, nullable=True)
    color = db.Column(db.String(30), nullable=True)  # hex or color name
    align = db.Column(db.String(20), nullable=True, default="left")

    # Image-specific props
    width = db.Column(db.Integer, nullable=True)
    height = db.Column(db.Integer, nullable=True)
    shape = db.Column(db.String(20), nullable=True)  # 'rect' or 'circle'

    # Optional font family token (maps to Config.FONT_FAMILIES)
    font_family = db.Column(db.String(80), nullable=True)

    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    # --- Legacy aliases for compatibility with older schema names / templates ---
    @property
    def field_name(self):
        return self.name

    @field_name.setter
    def field_name(self, v):
        self.name = v

    @property
    def x_position(self):
        return self.x

    @x_position.setter
    def x_position(self, v):
        try:
            self.x = int(v)
        except Exception:
            self.x = 0

    @property
    def y_position(self):
        return self.y

    @y_position.setter
    def y_position(self, v):
        try:
            self.y = int(v)
        except Exception:
            self.y = 0

    def __repr__(self):
        return f"<TemplateField id={self.id} name={self.name} type={self.field_type} x={self.x} y={self.y}>"


class ReferralCode(db.Model):
    __tablename__ = "referral_code"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False)

    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    reward_amount = db.Column(db.Float, nullable=False, default=0.0)
    max_uses = db.Column(db.Integer, nullable=True)
    used_count = db.Column(db.Integer, default=0)
    expires_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

    redemptions = db.relationship("ReferralRedemption", backref="referral_code", lazy=True)

    def __repr__(self):
        return f"<ReferralCode {self.code} owner={self.owner_id} used={self.used_count}>"


class ReferralRedemption(db.Model):
    __tablename__ = "referral_redemption"

    id = db.Column(db.Integer, primary_key=True)
    referral_code_id = db.Column(db.Integer, db.ForeignKey("referral_code.id"), nullable=False)

    redeemed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    reward_amount = db.Column(db.Float, nullable=False, default=0.0)
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())

    def __repr__(self):
        return f"<ReferralRedemption code_id={self.referral_code_id} user={self.redeemed_by_user_id}>"


class Transaction(db.Model):
    __tablename__ = "transaction"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    amount = db.Column(db.Float, nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)  # 'credit' or 'debit'
    description = db.Column(db.String(300), nullable=True)

    # optional: mark Razorpay payment id for idempotency
    razorpay_payment_id = db.Column(db.String(200), nullable=True, unique=False)

    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())

    def __repr__(self):
        return f"<Transaction id={self.id} user={self.user_id} {self.transaction_type} {self.amount}>"

