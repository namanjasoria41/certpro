# Gunicorn configuration file
import multiprocessing

# Server socket
bind = "0.0.0.0:10000"

# Worker processes
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
worker_connections = 1000
timeout = 120

# Request limits - IMPORTANT: Allow large base64-encoded images
limit_request_line = 0  # No limit on request line
limit_request_field_size = 0  # No limit on header field size
limit_request_fields = 100

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
