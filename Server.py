import socketio
import eventlet
from flask import Flask, jsonify # Import jsonify for health check
import os
import logging
from logging.handlers import RotatingFileHandler
import sys
import signal # Import signal for graceful shutdown
import time # Import time for health check timestamp

# --- Configuration ---
# Load configuration from environment variables.
# These are CRITICAL for a production deployment and should be managed securely.
SERVER_HOST = os.environ.get('SERVER_HOST', '0.0.0.0') # Host to bind to (0.0.0.0 for all interfaces is standard in production)
SERVER_PORT = int(os.environ.get('SERVER_PORT', 5000)) # Port to listen on

# Production: **ESSENTIAL SECURITY MEASURE**
# Restrict this to your frontend's actual origin(s) and your agent dashboard's origin!
# Using '*' in production is HIGHLY DANGEROUS and exposes your server to potential attacks like CSRF and data leakage.
# Example: ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', 'https://your-client-app.com,https://your-agent-dashboard.com').split(',')
ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', '*').split(',') # !!! DANGEROUS IN PRODUCTION - CHANGE THIS !!!

# --- Logging Setup ---
# Configure logging comprehensively for production monitoring and debugging.
LOG_FILE = os.environ.get('LOG_FILE', 'logs/middleman.log') # Log file name, default to a 'logs' subdirectory
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper() # Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

# Ensure the log directory exists if a file is specified
log_dir = os.path.dirname(LOG_FILE)
if log_dir and not os.path.exists(log_dir):
    try:
        os.makedirs(log_dir, exist_ok=True) # Use exist_ok=True to avoid error if dir already exists
        print(f"Created log directory: {log_dir}", file=sys.stderr)
    except OSError as e:
        print(f"Error creating log directory {log_dir}: {e}", file=sys.stderr)
        # Fallback to current directory if directory creation fails
        LOG_FILE = 'middleman.log'
        print(f"Logging to {LOG_FILE} in the current directory due to directory creation failure.", file=sys.stderr)


# Create logger instance
logger = logging.getLogger(__name__)
# Set the overall logging level for the logger
try:
    logger.setLevel(LOG_LEVEL)
except ValueError:
    logger.warning(f"Invalid LOG_LEVEL '{LOG_LEVEL}'. Defaulting to INFO.")
    logger.setLevel(logging.INFO)
    LOG_LEVEL = 'INFO' # Update LOG_LEVEL variable


# Create handlers
# Console handler for immediate feedback (useful in development/debugging, less so in daemonized production)
console_handler = logging.StreamHandler(sys.stdout) # Log to stdout
try:
    console_handler.setLevel(LOG_LEVEL)
except ValueError:
     console_handler.setLevel(logging.INFO) # Fallback


# File handler for persistent logs
# Rotates logs after 1MB, keeps 5 backup files
file_handler = None # Initialize file_handler to None
try:
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1024*1024, backupCount=5)
    file_handler.setLevel(LOG_LEVEL)
except ValueError:
     if file_handler: file_handler.setLevel(logging.INFO) # Fallback
except Exception as e:
    print(f"Error setting up file logging to {LOG_FILE}: {e}", file=sys.stderr)
    file_handler = None # Disable file logging if setup fails


# Create formatters and add them to handlers
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
if file_handler:
    file_handler.setFormatter(formatter)

# Add handlers to the logger
# In production, you might remove the console_handler if logs are only needed in files or a centralized system
logger.addHandler(console_handler)
if file_handler:
    logger.addHandler(file_handler)

# Suppress verbose logging from underlying libraries unless in DEBUG mode
if LOG_LEVEL != 'DEBUG':
    logging.getLogger('engineio').setLevel(logging.WARNING)
    logging.getLogger('socketio').setLevel(logging.WARNING)
    logging.getLogger('eventlet').setLevel(logging.WARNING)
    logging.getLogger('eventlet.wsgi').setLevel(logging.WARNING)


logger.info("Logging configured.")
logger.info(f"LOG_LEVEL set to {LOG_LEVEL}")
if file_handler:
    logger.info(f"Logging to file: {LOG_FILE}")
else:
     logger.warning("File logging is not active.")


# --- Flask and SocketIO Setup ---
app = Flask(__name__)
# Create a Socket.IO server instance
# Enable SocketIO/EngineIO logging, directing it to our configured logger
sio = socketio.Server(cors_allowed_origins=ALLOWED_ORIGINS, logger=logger, engineio_logger=logger)
app.wsgi_app = socketio.WSGIApp(sio, app.wsgi_app)

# --- Session Management (Conceptual for Production) ---
# In a production system, you would need a robust mechanism to:
# 1. Authenticate and Authorize agents connecting via 'agent_connect'.
# 2. Maintain a mapping of client SIDs to agent SIDs for direct routing.
# 3. Handle agent availability, client queuing, and agent assignment.
# 4. Persist session data if the server restarts or scales (e.g., using Redis).
# This simple set and map are NOT sufficient for production and will lose state on server restart.
client_agent_map = {} # client_sid -> agent_sid
agent_sids = set() # Set of connected agent SIDs

# --- Health Check Endpoint ---
@app.route('/health', methods=['GET'])
def health_check():
    """Provides a simple health check endpoint."""
    # In a more advanced check, you might verify connections to databases, message queues, etc.
    status = "ok"
    message = "Server is running."
    # You could add checks here, e.g.:
    # if not is_database_connected():
    #     status = "degraded"
    #     message = "Server is running, but database connection failed."
    logger.debug("Health check requested.")
    return jsonify({
        "status": status,
        "message": message,
        "timestamp": int(time.time()),
        "connected_clients": len(sio.manager.rooms.get('/', {})), # Count clients in the default room
        "connected_agents": len(agent_sids)
    })


# --- SocketIO Event Handlers ---

@sio.event
def connect(sid, environ):
    """Handles new client connections."""
    # In a production system, you might check headers or query params here
    # to distinguish between client and agent connections initially,
    # or rely solely on the 'agent_connect' event for agents.
    # Basic logging of connection details
    logger.info(f"Client connected: {sid} - Transport: {sio.manager.get_transport(sid)}")
    # In a real system, you'd initiate the process of assigning this client to an agent.


@sio.event
def disconnect(sid):
    """Handles client disconnections."""
    logger.info(f"Client disconnected: {sid}")
    # Remove from agent SIDs if it was an agent
    if sid in agent_sids:
        agent_sids.remove(sid)
        logger.info(f"Agent disconnected: {sid}. Remaining agents: {agent_sids}")
        # In a real system, notify clients assigned to this agent that the agent disconnected.
        # Find clients assigned to this agent and potentially re-queue them or notify them.
        clients_to_notify = [client for client, agent in client_agent_map.items() if agent == sid]
        for client_sid in clients_to_notify:
             try:
                 sio.emit('system_message_to_client', {'user': 'System', 'text': 'Your agent has disconnected. Please wait or refresh.'}, room=client_sid)
                 del client_agent_map[client_sid] # Remove mapping
             except Exception as e:
                 logger.error(f"Error notifying client {client_sid} about agent disconnect: {e}")

    else:
        # Clean up mapping if it was a client
        if sid in client_agent_map:
            assigned_agent_sid = client_agent_map.pop(sid)
            logger.info(f"Client {sid} removed from map. Was assigned to agent {assigned_agent_sid}.")
            # In a real system, notify the assigned agent that the client disconnected.
            try:
                 sio.emit('system_message_to_agent', {'client_sid': sid, 'text': f'Client {sid} has disconnected.'}, room=assigned_agent_sid)
            except Exception as e:
                 logger.error(f"Error notifying agent {assigned_agent_sid} about client {sid} disconnect: {e}")


@sio.event
def client_message(sid, data):
    """
    Handles incoming messages from the client (browser frontend).
    Forwards the message to the relevant agent(s).
    Includes basic input validation.

    Args:
        sid (str): The session ID of the client.
        data (dict): The message data, expected to contain a 'text' key.
    """
    user_message = data.get('text') # Get text, don't strip yet
    logger.info(f"Raw message from client {sid}: {data}") # Log raw data for debugging

    if not isinstance(user_message, str) or not user_message.strip():
        logger.warning(f"Received invalid or empty client message from {sid}: {data}")
        # Optionally send an error back to the client
        try:
            sio.emit('system_message_to_client', {'user': 'System', 'text': 'Invalid message format.'}, room=sid)
        except Exception as e:
            logger.error(f"Error sending validation error to client {sid}: {e}")
        return

    cleaned_message = user_message.strip()
    logger.info(f"Cleaned message from client {sid}: {cleaned_message}")

    # --- Forward message to Agent(s) ---
    # In a production system, you would look up the agent assigned to this client_sid
    # using the client_agent_map and send only to that agent.
    # For this example, we still broadcast to all connected agents.
    if agent_sids:
        message_to_agent = {'client_sid': sid, 'text': cleaned_message, 'user': 'Client'}
        for agent_sid in list(agent_sids): # Iterate over a copy in case set changes during iteration
             try:
                 sio.emit('message_to_agent', message_to_agent, room=agent_sid)
                 logger.debug(f"Forwarded message from client {sid} to agent {agent_sid}")
             except Exception as e:
                 logger.error(f"Error forwarding message to agent {agent_sid}: {e}")
    else:
        # Handle case where no agents are available
        logger.warning(f"No agents connected to receive message from client {sid}")
        # Send a message back to the client indicating they are waiting.
        try:
            sio.emit('message_to_client', {'user': 'System', 'text': 'Please wait, connecting you to an agent...'}, room=sid)
        except Exception as e:
            logger.error(f"Error sending waiting message to client {sid}: {e}")


@sio.event
def agent_message(sid, data):
    """
    Handles incoming messages from the agent dashboard.
    Forwards the message to the relevant client(s).
    Includes basic input validation.

    Args:
        sid (str): The session ID of the agent.
        data (dict): The message data, expected to contain 'client_sid' and 'text' keys.
    """
    client_sid = data.get('client_sid')
    agent_text = data.get('text') # Get text, don't strip yet
    logger.info(f"Raw message from agent {sid}: {data}") # Log raw data

    if not isinstance(client_sid, str) or not client_sid.strip() or \
       not isinstance(agent_text, str) or not agent_text.strip():
        logger.warning(f"Received invalid or incomplete agent message from {sid}: {data}")
        # Optionally notify the agent about the invalid message
        try:
            sio.emit('system_message_to_agent', {'system_message': 'Invalid message format or missing client ID.'}, room=sid)
        except Exception as e:
            logger.error(f"Error notifying agent {sid} about invalid message: {e}")
        return

    cleaned_client_sid = client_sid.strip()
    cleaned_agent_text = agent_text.strip()
    logger.info(f"Cleaned message from agent {sid} for client {cleaned_client_sid}: {cleaned_agent_text}")


    # --- Forward message to Client ---
    # In a production system, you'd verify that agent_sid is authorized to message client_sid.
    # Ensure the target client is still connected
    # Check if the client SID is in the default room (connected)
    if cleaned_client_sid in sio.manager.rooms.get('/', {}): # Safely access rooms
         try:
             message_to_client = {'user': 'Agent', 'text': cleaned_agent_text, 'agent_sid': sid} # Include agent SID
             sio.emit('message_to_client', message_to_client, room=cleaned_client_sid)
             logger.debug(f"Forwarded message from agent {sid} to client {cleaned_client_sid}")
         except Exception as e:
             logger.error(f"Error forwarding message to client {cleaned_client_sid}: {e}")
    else:
        logger.warning(f"Target client {cleaned_client_sid} not found or disconnected. Cannot forward message from agent {sid}.")
        # Notify the agent that the client is gone
        try:
            sio.emit('system_message_to_agent', {'client_sid': cleaned_client_sid, 'text': f'Client {cleaned_client_sid} is no longer connected.'}, room=sid)
        except Exception as e:
            logger.error(f"Error notifying agent {sid} about disconnected client: {e}")


@sio.event
def agent_connect(sid, data):
    """
    Handles an agent explicitly connecting and identifying themselves.
    In production, this event MUST include authentication credentials.
    """
    logger.info(f"Potential agent connection attempt: {sid} with data: {data}")
    # --- Production Authentication Placeholder ---
    # In a production system, you would VALIDATE the 'data' payload
    # (e.g., API key, token, username/password) against your user database.
    # This is CRITICAL for security.
    # Example validation (replace with your actual logic):
    # auth_token = data.get('auth_token')
    # if not is_valid_agent_token(auth_token): # Implement this function securely!
    #     logger.warning(f"Authentication failed for potential agent {sid}. Disconnecting.")
    #     sio.disconnect(sid)
    #     return
    # ---------------------------------------------

    logger.info(f"Agent connected and authenticated: {sid}") # Assume authenticated after validation
    agent_sids.add(sid)
    logger.info(f"Current connected agents: {agent_sids}")
    # In a real system, you'd send the agent a list of waiting clients or active conversations.
    # Example: sio.emit('active_clients', get_waiting_clients(), room=sid)


# --- Graceful Shutdown ---
def signal_handler(signum, frame):
    """Handles signals for graceful shutdown."""
    logger.info(f"Received signal {signum}. Initiating graceful shutdown.")
    print(f"\nReceived signal {signum}. Shutting down gracefully...")
    try:
        # Disconnect all clients and agents
        for sid in list(sio.manager.rooms.get('/', {})):
             try:
                 sio.emit('system_message_to_client', {'user': 'System', 'text': 'Server is shutting down.'}, room=sid)
                 sio.disconnect(sid)
                 logger.debug(f"Disconnected client {sid} during shutdown.")
             except Exception as e:
                 logger.error(f"Error disconnecting client {sid} during shutdown: {e}")

        # Give some time for disconnects to process (optional)
        eventlet.sleep(1)

        # Stop the eventlet server
        # This might require accessing the server object if not global
        # For the simple eventlet.wsgi.server case, stopping the hub is often sufficient
        eventlet.get_hub().interrupt()
        logger.info("Eventlet hub interrupted.")

    except Exception as e:
        logger.critical(f"Error during graceful shutdown: {e}", exc_info=True)
    finally:
        logger.info("Shutdown complete.")
        sys.exit(0) # Exit cleanly

# Register signal handlers for graceful shutdown
signal.signal(signal.SIGINT, signal_handler)  # Handle Ctrl+C
signal.signal(signal.SIGTERM, signal_handler) # Handle kill command

# --- Running the Server ---
if __name__ == '__main__':
    # --- Production Deployment Recommendation ---
    # For production, it is **ESSENTIAL** to use a production-ready WSGI server
    # like Gunicorn or uWSGI with eventlet workers. Running eventlet.wsgi.server
    # directly is ONLY suitable for development and testing.
    #
    # Example command using Gunicorn (recommended):
    # gunicorn -k eventlet -w 4 server:app -b 0.0.0.0:5000 --log-level info --timeout 30 --graceful-timeout 30
    # (Replace 'server' with the name of your Python file if it's different)
    # '--timeout' and '--graceful-timeout' help manage worker behavior during restarts/shutdowns.
    #
    # Ensure your process manager (like systemd, Docker Swarm, Kubernetes) keeps the Gunicorn process running.
    # Also consider using a reverse proxy (like Nginx, Caddy, HAProxy) in front of Gunicorn
    # for SSL/TLS termination, load balancing, static file serving, and additional security.

    logger.info(f"Attempting to start SocketIO middleman server on http://{SERVER_HOST}:{SERVER_PORT}")
    print(f"Starting SocketIO middleman server on http://{SERVER_HOST}:{SERVER_PORT}")

    try:
        # The eventlet.wsgi.server call is blocking and runs the server.
        # In production with Gunicorn, Gunicorn manages the workers and event loop.
        eventlet.wsgi.server(eventlet.listen((SERVER_HOST, SERVER_PORT)), app)
    except OSError as e:
        logger.critical(f"Failed to bind to {SERVER_HOST}:{SERVER_PORT}. Address already in use or permission denied?", exc_info=True)
        print(f"Error: Failed to bind to {SERVER_HOST}:{SERVER_PORT}. Address already in use or permission denied? Details: {e}", file=sys.stderr)
        sys.exit(1) # Exit with an error code indicating failure
    except Exception as e:
        logger.critical(f"Failed to start server: {e}", exc_info=True)
        print(f"Error: Failed to start server: {e}", file=sys.stderr)
        sys.exit(1) # Exit with an error code indicating failure

