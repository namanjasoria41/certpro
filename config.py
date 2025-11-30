import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///certificates.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    TEMPLATE_FOLDER = os.path.join('static', 'templates')
    GENERATED_FOLDER = os.path.join('static', 'generated')
    
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size