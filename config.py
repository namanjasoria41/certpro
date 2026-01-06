import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # ----------------------------
    # Core flask / secret
    # ----------------------------
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

    # ----------------------------
    # Database (Neon/Render: DATABASE_URL)
    # ----------------------------
    # Default to sqlite local for development convenience
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'certpro.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ----------------------------
    # Static / template storage
    # ----------------------------
    STATIC_FOLDER = os.path.join(BASE_DIR, "static")
    TEMPLATE_FOLDER = os.path.join(STATIC_FOLDER, "templates")
    GENERATED_FOLDER = os.path.join(STATIC_FOLDER, "generated")
    PREVIEW_FOLDER = os.path.join(STATIC_FOLDER, "previews")
    TEMP_UPLOAD_FOLDER = os.path.join(STATIC_FOLDER, "temp_uploads")

    # ----------------------------
    # Razorpay config (set as env vars on host)
    # ----------------------------
    RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")

    # ----------------------------
    # Referral amounts (wallet credits)
    # ----------------------------
    REFERRAL_NEW_USER_BONUS = float(os.getenv("REFERRAL_NEW_USER_BONUS", "50.0"))
    REFERRAL_OWNER_BONUS = float(os.getenv("REFERRAL_OWNER_BONUS", "50.0"))

    # ----------------------------
    # Default font (single fallback used by PIL)
    # ----------------------------
    # Point this to a reliable TTF on your server. Common Linux path below.
    FONT_PATH = os.getenv(
        "FONT_PATH", "/usr/share/fonts/truetype/dejavu/Roboto.ttf"
    )

    # ----------------------------
    # Named font families for builder UI
    # ----------------------------
    # Provide absolute paths or paths relative to project root.
    # If you don't have some fonts, either upload them to static/fonts or point to system fonts.
    FONT_FAMILIES = {
        "default": FONT_PATH,
        "inter": os.getenv("FONT_INTER_PATH", os.path.join(STATIC_FOLDER, "fonts", "Inter-Regular.ttf")),
        "roboto": os.getenv("FONT_ROBOTO_PATH", os.path.join(STATIC_FOLDER, "fonts", "Roboto.ttf")),
        "open_sans": os.getenv("FONT_OPEN_SANS_PATH", os.path.join(STATIC_FOLDER, "fonts", "OpenSans-Regular.ttf")),
        "noto_sans": os.getenv("FONT_NOTO_SANS_PATH", os.path.join(STATIC_FOLDER, "fonts", "NotoSans-Regular.ttf")),
        "times": os.getenv("FONT_TIMES_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
        "arial": os.getenv("FONT_ARIAL_PATH", ""),  # optional
    }

    # ----------------------------
    # Debug toggle
    # ----------------------------
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"

    # ----------------------------
    # Image processing limits
    # ----------------------------
    # Maximum dimension (width or height) for template images
    # Images larger than this will be resized proportionally to prevent memory issues
    MAX_TEMPLATE_DIMENSION = int(os.getenv("MAX_TEMPLATE_DIMENSION", "2000"))


# Create folders if they don't exist so PIL/save operations won't fail at runtime.
_required_dirs = [
    Config.STATIC_FOLDER,
    Config.TEMPLATE_FOLDER,
    Config.GENERATED_FOLDER,
    Config.PREVIEW_FOLDER,
    Config.TEMP_UPLOAD_FOLDER,
    os.path.join(Config.STATIC_FOLDER, "fonts"),
]
for _d in _required_dirs:
    try:
        os.makedirs(_d, exist_ok=True)
    except Exception:
        # don't crash import if filesystem permission prevents creation;
        # app will still attempt to write and log errors.
        pass

