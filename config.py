import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    # Secret key
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

    # Neon PostgreSQL database URL (Render env: DATABASE_URL)
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///certpro.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Static / template storage
    STATIC_FOLDER = os.path.join(BASE_DIR, "static")
    TEMPLATE_FOLDER = os.path.join(STATIC_FOLDER, "templates")
    GENERATED_FOLDER = os.path.join(STATIC_FOLDER, "generated")
    PREVIEW_FOLDER = os.path.join(BASE_DIR, "static", "previews")

    # Font used to draw text on certificates
# config.py additions
# map token -> font file path (absolute or relative to project)
  FONT_FAMILIES = {
    "default": Config.FONT_PATH if hasattr(Config, "FONT_PATH") else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "inter": "/path/to/fonts/Inter-Regular.ttf",
    "roboto": "/path/to/fonts/Roboto-Regular.ttf",
    "open_sans": "/path/to/fonts/OpenSans-Regular.ttf",
    "noto_sans": "/path/to/fonts/NotoSans-Regular.ttf",
    "times": "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "arial": "/path/to/fonts/Arial.ttf"
}
# Ensure the files above exist on your server; point to TTFs in your repo or system fonts.


    # Razorpay
    RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")

    # Referral bonuses
    REFERRAL_NEW_USER_BONUS = float(os.getenv("REFERRAL_NEW_USER_BONUS", 50))
    REFERRAL_OWNER_BONUS = float(os.getenv("REFERRAL_OWNER_BONUS", 50))


