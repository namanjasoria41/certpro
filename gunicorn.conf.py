# Gunicorn configuration file
import multiprocessing
import os

# Server socket
bind = "0.0.0.0:10000"

# Worker processes - Optimized for Render free tier
# Reduced from cpu_count * 2 + 1 to avoid memory issues
workers = int(os.getenv("WEB_CONCURRENCY", 4))  # Default to 4 workers
worker_class = "sync"
worker_connections = 1000
timeout = 300  # Increased timeout for large image uploads
keepalive = 5  # Keep connections alive

# Preload app for faster worker spawning
preload_app = True

# Request limits - IMPORTANT: Allow large base64-encoded images
limit_request_line = 0  # No limit on request line
limit_request_field_size = 0  # No limit on header field size
limit_request_fields = 100

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
