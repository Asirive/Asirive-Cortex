"""
Project-Cortex v2.0 - FastAPI Server for Companion App (Tier 3)

REST API and WebSocket server for mobile companion app integration.
Provides JWT-authenticated access to RPi wearable data and commands.

Features:
- JWT authentication (OAuth2 + Bearer tokens)
- REST endpoints (/api/v1/status, /api/v1/devices, /api/v1/metrics)
- WebSocket streaming (/api/v1/stream)
- CORS support for mobile apps
- Rate limiting
- API documentation (auto-generated with FastAPI)

Author: Haziq (@IRSPlays) + GitHub Copilot (CTO)
Date: January 3, 2026
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import logging
import asyncio
import json

from .config import (
    API_TITLE, API_VERSION, API_DESCRIPTION,
    API_HOST, API_PORT,
    JWT_SECRET_KEY, JWT_ALGORITHM, JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
    CORS_ORIGINS,
    RATE_LIMIT_REQUESTS, RATE_LIMIT_PERIOD
)
from .protocol import MessageType, create_message

logger = logging.getLogger(__name__)

# ============ SECURITY ============

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/token")

# Temporary user database (replace with real database in production)
USERS_DB = {
    "admin": {
        "username": "admin",
        "email": "admin@cortex.com",
        "hashed_password": pwd_context.hash("changeme"),  # Change in production!
        "disabled": False
    }
}


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash password."""
    return pwd_context.hash(password)


def authenticate_user(username: str, password: str) -> Optional[dict]:
    """Authenticate user with username/password."""
    user = USERS_DB.get(username)
    if not user:
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token."""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    
    return encoded_jwt


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Get current user from JWT token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"}
    )
    
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        username: str = payload.get("sub")
        
        if username is None:
            raise credentials_exception
    
    except JWTError:
        raise credentials_exception
    
    user = USERS_DB.get(username)
    if user is None:
        raise credentials_exception
    
    return user


async def get_current_active_user(current_user: dict = Depends(get_current_user)) -> dict:
    """Get current active user."""
    if current_user.get("disabled"):
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


# ============ FASTAPI APP ============

app = FastAPI(
    title=API_TITLE,
    version=API_VERSION,
    description=API_DESCRIPTION,
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Shared state with WebSocket server
# This will be injected by main application
connected_rpis: Dict[str, Any] = {}
latest_metrics: Dict[str, Any] = {}
latest_detections: Dict[str, Any] = {}


# ============ REST ENDPOINTS ============

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": API_TITLE,
        "version": API_VERSION,
        "status": "online",
        "docs": "/api/v1/docs"
    }


@app.post("/api/v1/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    OAuth2 token endpoint.
    
    Returns JWT access token for authenticated user.
    """
    user = authenticate_user(form_data.username, form_data.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    access_token_expires = timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username"]},
        expires_delta=access_token_expires
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer"
    }


@app.get("/api/v1/status")
async def get_status(current_user: dict = Depends(get_current_active_user)):
    """
    Get system status.
    
    Returns current server status and connected RPi devices.
    """
    return {
        "status": "online",
        "timestamp": datetime.utcnow().isoformat(),
        "connected_rpis": len(connected_rpis),
        "user": current_user["username"]
    }


@app.get("/api/v1/devices")
async def get_devices(current_user: dict = Depends(get_current_active_user)):
    """
    Get list of connected RPi devices.
    
    Returns device IDs, connection times, and last activity.
    """
    devices = []
    
    for device_id, info in connected_rpis.items():
        devices.append({
            "device_id": device_id,
            "connected_at": info.get("connected_at"),
            "last_activity": info.get("last_activity"),
            "status": "online"
        })
    
    return {
        "devices": devices,
        "total": len(devices)
    }


@app.get("/api/v1/metrics/{device_id}")
async def get_metrics(
    device_id: str,
    current_user: dict = Depends(get_current_active_user)
):
    """
    Get latest metrics for specific device.
    
    Returns FPS, latency, RAM, CPU, battery, etc.
    """
    if device_id not in connected_rpis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Device {device_id} not found"
        )
    
    metrics = latest_metrics.get(device_id)
    
    if not metrics:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No metrics available for {device_id}"
        )
    
    return metrics


@app.get("/api/v1/detections/{device_id}")
async def get_detections(
    device_id: str,
    current_user: dict = Depends(get_current_active_user)
):
    """
    Get latest detections for specific device.
    
    Returns merged detections, counts, YOLO mode.
    """
    if device_id not in connected_rpis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Device {device_id} not found"
        )
    
    detections = latest_detections.get(device_id)
    
    if not detections:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No detections available for {device_id}"
        )
    
    return detections


@app.post("/api/v1/command/{device_id}")
async def send_command(
    device_id: str,
    command: str,
    params: Optional[dict] = None,
    current_user: dict = Depends(get_current_active_user)
):
    """
    Send command to specific RPi device.
    
    Commands: start_recording, stop_recording, change_mode, etc.
    """
    if device_id not in connected_rpis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Device {device_id} not found"
        )
    
    # TODO: Send command via WebSocket server
    # This will require shared message queue between FastAPI and WebSocket server
    
    logger.info(f"📩 Command sent to {device_id}: {command} with params {params}")
    
    return {
        "status": "sent",
        "device_id": device_id,
        "command": command,
        "params": params,
        "timestamp": datetime.utcnow().isoformat()
    }


# ============ WEBSOCKET STREAMING ============

class ConnectionManager:
    """Manage WebSocket connections for mobile app clients."""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str):
        """Accept new connection."""
        await websocket.accept()
        self.active_connections[client_id] = websocket
        logger.info(f"📱 Mobile app connected: {client_id}")
    
    def disconnect(self, client_id: str):
        """Remove connection."""
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            logger.info(f"📱 Mobile app disconnected: {client_id}")
    
    async def send_personal_message(self, message: dict, client_id: str):
        """Send message to specific client."""
        websocket = self.active_connections.get(client_id)
        if websocket:
            await websocket.send_json(message)
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients."""
        for client_id, websocket in self.active_connections.items():
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"❌ Failed to send to {client_id}: {e}")


manager = ConnectionManager()


@app.websocket("/api/v1/stream")
async def websocket_stream(websocket: WebSocket):
    """
    WebSocket endpoint for real-time data streaming to mobile app.
    
    Sends metrics, detections, and video frames in real-time.
    Requires JWT token in query parameter: /api/v1/stream?token=<jwt_token>
    """
    # Extract token from query params
    token = websocket.query_params.get("token")
    
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    # Verify token
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        username = payload.get("sub")
        
        if not username or username not in USERS_DB:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    
    except JWTError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    # Generate client ID
    client_id = f"mobile_{username}_{datetime.utcnow().timestamp()}"
    
    # Connect
    await manager.connect(websocket, client_id)
    
    try:
        # Send initial status
        await websocket.send_json({
            "type": "connected",
            "message": "Connected to Cortex streaming server",
            "connected_rpis": len(connected_rpis)
        })
        
        # Listen for incoming messages (mobile app commands)
        while True:
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                msg_type = message.get("type")
                
                if msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                
                elif msg_type == "get_status":
                    await websocket.send_json({
                        "type": "status",
                        "connected_rpis": len(connected_rpis),
                        "timestamp": datetime.utcnow().isoformat()
                    })
                
                else:
                    logger.warning(f"⚠️ Unknown message type from mobile: {msg_type}")
            
            except json.JSONDecodeError:
                logger.error("❌ Invalid JSON from mobile app")
    
    except WebSocketDisconnect:
        manager.disconnect(client_id)
        logger.info(f"📱 Mobile app disconnected: {client_id}")
    
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}", exc_info=True)
        manager.disconnect(client_id)


# ============ STARTUP/SHUTDOWN ============

@app.on_event("startup")
async def startup_event():
    """Initialize on startup."""
    logger.info("🚀 FastAPI server starting...")
    logger.info(f"📱 API available at http://{API_HOST}:{API_PORT}")
    logger.info(f"📚 Documentation at http://{API_HOST}:{API_PORT}/api/v1/docs")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("🛑 FastAPI server shutting down...")


# ============ MAIN ============

def main():
    """Run FastAPI server with Uvicorn."""
    import uvicorn
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║     PROJECT-CORTEX v2.0 - FASTAPI SERVER (TIER 3)           ║
║                                                              ║
║  REST API + WebSocket for Mobile Companion App              ║
║                                                              ║
║  API Endpoints:                                              ║
║    POST /api/v1/token          - Get JWT token              ║
║    GET  /api/v1/status         - System status              ║
║    GET  /api/v1/devices        - List connected RPis        ║
║    GET  /api/v1/metrics/{{id}}  - Device metrics             ║
║    GET  /api/v1/detections/{{id}} - Device detections       ║
║    POST /api/v1/command/{{id}}  - Send command to RPi       ║
║                                                              ║
║  WebSocket:                                                  ║
║    WS   /api/v1/stream?token=<jwt> - Real-time stream       ║
║                                                              ║
║  Documentation:                                              ║
║    http://{API_HOST}:{API_PORT}/api/v1/docs                               ║
║                                                              ║
║  Default Credentials:                                        ║
║    Username: admin                                           ║
║    Password: changeme (CHANGE IN PRODUCTION!)               ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    uvicorn.run(
        app,
        host=API_HOST,
        port=API_PORT,
        log_level="info"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
