# WebSocket System Architecture & Data Flow

This document explains the real-time communication system between the Raspberry Pi 5 (Client) and the Laptop Dashboard (Server).

## 1. High-Level Architecture

The system uses a **star topology** where the Laptop acts as the central Server and one or more RPi5 units act as Clients.

```mermaid
graph LR
    RPi5[RPi5 Client] <-->|WebSocket (JSON)| SharedProtocol[Shared Protocol]
    SharedProtocol <-->|WebSocket (JSON)| Laptop[Laptop Server]
    
    subgraph "RPi5 Side"
        Camera[Camera Handler] -->|Frames| RPi5
        YOLO[YOLOv8] -->|Detections| RPi5
        Metrics[System Monitor] -->|Stats| RPi5
    end

    subgraph "Laptop Side"
        Laptop -->|Signals| GUI[PyQt6 Dashboard]
        Laptop -->|API| FastAPI[REST API]
    end
```

## 2. Shared Library (`shared/`)
The glue that holds everything together. Both Client and Server import from here to ensure they speak the same language.

### `shared/api/protocol.py`
Defines **what** data looks like.
- **`BaseMessage`**: The envelope for all messages. Contains `type`, `timestamp`, `message_id`, and `data`.
- **`MessageType` (Enum)**: Valid message types (e.g., `VIDEO_FRAME`, `PING`, `COMMAND`).
- **`create_...` helper functions**: Factories to create valid messages (e.g., `create_ping`, `create_video_frame`).

### `shared/api/base_client.py` (`AsyncWebSocketClient`)
The "brain" of the client connectivity.
- **`_connect_impl`**: Abstract method to connect (implemented by subclass).
- **`_heartbeat_loop`**: Background task that sends `PING` every 30s.
- **`_handle_pong`**: Validates `PONG` responses. **Crucial:** It checks if the returned `ping_id` matches what it sent.
- **`_reconnect`**: Handles connection loss with exponential backoff (wait 5s, then 10s, etc.).

---

## 3. RPi5 Client (`rpi5/`)
The "sender" of data.

### `rpi5/fastapi_client.py` (`RPi5Client`)
Inherits from `AsyncWebSocketClient`.
- **`__init__`**: Sets up connection config (IP, Port).
- **`send_video_frame`**:
    1. Compresses image to JPEG (base64).
    2. Wraps it in `VIDEO_FRAME` message.
    3. Sends it asynchronously to the laptop.
    4. **Rate Limiting**: logic inside ensures we don't flood the network (max 15 FPS).
- **`send_metrics`**: Sends CPU/RAM/Temp stats.
- **`_handle_command`**: Listens for commands from Laptop (e.g., "STOP_VIDEO_STREAMING") and toggles internal flags.

---

## 4. Laptop Server (`laptop/`)
The "receiver" and "displayer".

### `laptop/server/websocket_server.py` (`CortexWebSocketServer`)
The legacy WebSocket server (the one currently running via `python -m laptop all`).
- **`start`**: Opens the listening port (8765).
- **`handle_client`**: The main loop for *each* connected RPi5.
    - **Message Parsing**: Converts JSON string -> `BaseMessage`.
    - **PING Handling**: 
        1. Sees `MessageType.PING`.
        2. Extracts the `ping_id`.
        3. Sends back a `PONG` with the *same* `ping_id`.
    - **Data Handling**: Forwards other messages (Video, Metrics) to the GUI via callbacks.

### `laptop/cli/start_dashboard.py`
The launch script.
- Validates command line args (`--fastapi`, `--host`).
- Initializes `DashboardApplication`.
- Connects the Server's "on_message" signals to the GUI's update slots.

---

## 5. The Heartbeat (Ping/Pong) Flow
This ensures the connection is alive. If this fails, the RPi5 disconnects.

1.  **RPi5**: Generates unique `ping_id` (e.g., `rpi5_12345`).
2.  **RPi5**: Sends `PING` message: `{ "type": "PING", "data": { "device_id": "rpi5", "ping_id": "rpi5_12345" } }`.
3.  **Laptop**: Receives `PING`. Reads `ping_id`.
4.  **Laptop**: Sends `PONG` message: `{ "type": "PONG", "data": { ..., "ping_id": "rpi5_12345" } }`.
5.  **RPi5**: Receives `PONG`. Checks if `data["ping_id"] == "rpi5_12345"`.
    -   **Match**: Connection is Healthy ✅.
    -   **Mismatch/No Reply**: Connection is Dead ❌. Triggers `_reconnect`.
