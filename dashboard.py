import os
import logging
from logging.handlers import RotatingFileHandler
import sys
import time
from flask import Flask, render_template, jsonify # Import render_template to serve HTML

# --- Configuration ---
# Load configuration from environment variables.
# These are essential for a production deployment and should be managed securely.
DASHBOARD_HOST = os.environ.get('DASHBOARD_HOST', '127.0.0.1') # Host for the dashboard web server. Use 127.0.0.1 by default for local access only.
DASHBOARD_PORT = int(os.environ.get('DASHBOARD_PORT', 5001)) # Port for the dashboard web server

# Address of the running ChatRelay server
# The JavaScript frontend will connect to this address.
CHAT_RELAY_SERVER_ADDRESS = os.environ.get('CHAT_RELAY_SERVER_ADDRESS', 'http://localhost:5000')

# Placeholder for agent authentication data
# This token will be passed to the frontend JavaScript to be sent to the ChatRelay server.
# In production, this should be a secure token, API key, or credentials
# loaded securely and managed carefully.
AGENT_AUTH_TOKEN = os.environ.get('AGENT_AUTH_TOKEN', 'YOUR_SECURE_AGENT_TOKEN')
if AGENT_AUTH_TOKEN == 'YOUR_SECURE_AGENT_TOKEN':
    print("\n!!! WARNING: AGENT_AUTH_TOKEN is not set in environment variables. Authentication on the ChatRelay server may fail. !!!\n", file=sys.stderr)


# --- Logging Setup ---
# Configure logging for the dashboard web server.
LOG_FILE = os.environ.get('AGENT_DASHBOARD_LOG_FILE', 'logs/agent_dashboard_web.log') # Log file name
LOG_LEVEL = os.environ.get('AGENT_DASHBOARD_LOG_LEVEL', 'INFO').upper() # Logging level

# Ensure the log directory exists
log_dir = os.path.dirname(LOG_FILE)
if log_dir and not os.path.exists(log_dir):
    try:
        os.makedirs(log_dir, exist_ok=True)
        print(f"Created log directory: {log_dir}", file=sys.stderr)
    except OSError as e:
        print(f"Error creating log directory {log_dir}: {e}", file=sys.stderr)
        LOG_FILE = 'agent_dashboard_web.log'
        print(f"Logging to {LOG_FILE} in the current directory due to directory creation failure.", file=sys.stderr)

logger = logging.getLogger(__name__)
try:
    logger.setLevel(LOG_LEVEL)
except ValueError:
    logger.warning(f"Invalid AGENT_DASHBOARD_LOG_LEVEL '{LOG_LEVEL}'. Defaulting to INFO.")
    logger.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

console_handler = logging.StreamHandler(sys.stdout)
try:
    console_handler.setLevel(LOG_LEVEL)
except ValueError:
     console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

file_handler = None
try:
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1024*1024, backupCount=5)
    file_handler.setLevel(LOG_LEVEL)
except ValueError:
     if file_handler: file_handler.setLevel(logging.INFO)
except Exception as e:
    print(f"Error setting up file logging to {LOG_FILE}: {e}", file=sys.stderr)
    file_handler = None

if file_handler:
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

if file_handler:
    logger.info(f"Logging to file: {LOG_FILE}")
else:
     logger.warning("File logging is not active.")

# Suppress verbose logging from underlying libraries unless in DEBUG mode
# This Flask app doesn't use SocketIO server side, but might use other libraries
if LOG_LEVEL != 'DEBUG':
    logging.getLogger('werkzeug').setLevel(logging.WARNING) # Suppress Flask/Werkzeug request logs unless debugging


logger.info("Agent Dashboard Web Server Logging configured.")
logger.info(f"AGENT_DASHBOARD_LOG_LEVEL set to {LOG_LEVEL}")


# --- Flask App Setup ---
app = Flask(__name__)

# --- Routes ---
@app.route('/')
def index():
    """Serves the main dashboard HTML page."""
    logger.info("Serving dashboard HTML page.")
    # Pass configuration variables to the template
    return render_template('dashboard.html',
                           chat_relay_server_address=CHAT_RELAY_SERVER_ADDRESS,
                           agent_auth_token=AGENT_AUTH_TOKEN)

# --- Health Check Endpoint ---
@app.route('/health', methods=['GET'])
def health_check():
    """Provides a simple health check endpoint for the dashboard server."""
    status = "ok"
    message = "Agent Dashboard Web Server is running."
    logger.debug("Dashboard health check requested.")
    return jsonify({
        "status": status,
        "message": message,
        "timestamp": int(time.time())
    })


# --- Running the Server ---
if __name__ == '__main__':
    # --- Production Deployment Recommendation ---
    # For production, use a production-ready WSGI server like Gunicorn or uWSGI.
    # This Flask app does NOT use eventlet directly for serving, so standard Gunicorn/uWSGI workers are fine.
    # Example command using Gunicorn:
    # gunicorn -w 4 agent_dashboard_web:app -b 127.0.0.1:5001 --log-level info --timeout 30
    # (Replace 'agent_dashboard_web' with the name of your Python file)
    #
    # Ensure your process manager (like systemd) keeps the Gunicorn process running.
    # A reverse proxy (like Nginx or Caddy) is also recommended in front of Gunicorn
    # for SSL termination and potentially serving static assets.

    logger.info(f"Attempting to start Agent Dashboard Web Server on http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")
    print(f"Starting Agent Dashboard Web Server on http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")

    try:
        # Running app.run() directly is ONLY suitable for development/testing.
        # In production, use a WSGI server (Gunicorn, uWSGI).
        app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT, debug=False) # debug=False for production
    except OSError as e:
        logger.critical(f"Failed to bind to {DASHBOARD_HOST}:{DASHBOARD_PORT}. Address already in use or permission denied?", exc_info=True)
        print(f"Error: Failed to bind to {DASHBOARD_HOST}:{DASHBOARD_PORT}. Address already in use or permission denied? Details: {e}", file=sys.stderr)
        sys.exit(1) # Exit with an error code
    except Exception as e:
        logger.critical(f"Failed to start dashboard server: {e}", exc_info=True)
        print(f"Error: Failed to start dashboard server: {e}", file=sys.stderr)
        sys.exit(1) # Exit with an error code

