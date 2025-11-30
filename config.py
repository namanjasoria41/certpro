import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-this'

    # Use Neon when DATABASE_URL is set, otherwise fallback to local sqlite
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') 

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    TEMPLATE_FOLDER = os.path.join('static', 'templates')
    GENERATED_FOLDER = os.path.join('static', 'generated')

