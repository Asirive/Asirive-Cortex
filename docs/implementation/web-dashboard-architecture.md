# 🌐 Web Dashboard Architecture & Implementation Plan
**Project-Cortex v2.0 - Layer 3 & 4 Debugging Interface**  
**Created:** December 23, 2025  
**Status:** 🔬 Architecture Design Phase

---

## 📋 EXECUTIVE SUMMARY

This document outlines the **complete architecture** for building a web-based debugging dashboard to visualize and monitor:
- **Layer 3 (The Guide)**: SLAM/VIO maps, camera trajectory, GPS overlay
- **Layer 4 (The Memory)**: Spatial objects database, map anchors, coordinate transformations

**Goal:** Enable real-time debugging of navigation and memory systems via a browser interface accessible from laptop or RPi 5.

---

## 🎯 REQUIREMENTS

### Functional Requirements:
1. **3D Map Visualization**: Display VIO trajectory + detected objects in 3D space
2. **GPS Overlay**: Show GPS coordinates on map (when available)
3. **Live Updates**: Stream sensor data in real-time (camera, IMU, GPS)
4. **Database Queries**: Browse spatial_objects table, filter by location/time
5. **EuRoC Dataset Viewer**: Load and replay recorded sessions
6. **Coordinate System Inspector**: Show VIO ↔ GPS transformations

### Non-Functional Requirements:
1. **Lightweight**: Must run on RPi 5 alongside main Cortex process
2. **Accessible**: LAN access from laptop (http://raspberrypi.local:5000)
3. **Real-time**: <500ms latency for live sensor updates
4. **Responsive**: Mobile-friendly UI for debugging on-the-go

---

## 🔬 FRAMEWORK COMPARISON

### Option 1: **Dash by Plotly** (⭐ RECOMMENDED)
**What It Is:** Python framework for building data visualization dashboards with Plotly.js

**Pros:**
- ✅ **Native 3D Scatter Plots**: `dcc.Graph` with `Scatter3d` built-in
- ✅ **Live Updates**: `dcc.Interval` component for real-time streaming
- ✅ **Callback System**: Pythonic reactive programming (no JavaScript needed)
- ✅ **3,221 code snippets**: Massive documentation (Benchmark Score: 95.1)
- ✅ **Low-Code**: Build complex dashboards with ~100 lines of Python

**Cons:**
- ⚠️ **Higher Memory**: ~200MB runtime (but acceptable on RPi 5 4GB)
- ⚠️ **Learning Curve**: Callback patterns require understanding

**Use Case:** Best for data-heavy visualizations with minimal web dev knowledge.

**Code Example:**
```python
import dash
from dash import dcc, html, Input, Output
import plotly.graph_objects as go

app = dash.Dash(__name__)

app.layout = html.Div([
    dcc.Graph(id='live-slam-map'),
    dcc.Interval(id='interval', interval=1000, n_intervals=0)
])

@app.callback(
    Output('live-slam-map', 'extendData'),
    Input('interval', 'n_intervals')
)
def update_map(n):
    # Fetch latest SLAM data from database
    new_x, new_y, new_z = fetch_vio_position()
    return {'x': [[new_x]], 'y': [[new_y]], 'z': [[new_z]]}, [0], 100

if __name__ == '__main__':
    app.run_server(host='0.0.0.0', port=5000)
```

---

### Option 2: **Streamlit**
**What It Is:** Rapid prototyping framework for data apps.

**Pros:**
- ✅ **Fastest Development**: 10-minute dashboard prototypes
- ✅ **Session State**: Built-in state management (`st.session_state`)
- ✅ **No HTML/CSS**: Pure Python UI components
- ✅ **1,822 code snippets**: Excellent documentation (Benchmark Score: 81.6)

**Cons:**
- ❌ **No True Real-Time**: Page reruns on every interaction (not true WebSocket streaming)
- ❌ **Limited 3D**: Requires Plotly.js integration (not as smooth as Dash)
- ❌ **Single-User Focus**: Not designed for multi-client streaming

**Use Case:** Best for quick proof-of-concept dashboards, not production real-time systems.

**Verdict:** ❌ **Not suitable** for real-time SLAM visualization (page reloads kill continuity).

---

### Option 3: **Flask + Flask-SocketIO**
**What It Is:** Micro web framework + WebSocket library.

**Pros:**
- ✅ **Full Control**: Build custom REST API + WebSocket server
- ✅ **Lightweight**: <50MB runtime
- ✅ **True Real-Time**: WebSocket bidirectional streaming
- ✅ **821 Flask snippets + 91 Flask-SocketIO snippets**: Well-documented

**Cons:**
- ❌ **Manual Frontend**: Must write JavaScript for 3D visualization (Plotly.js/Three.js)
- ❌ **More Code**: 3x-5x more lines than Dash
- ❌ **Complexity**: Requires JavaScript knowledge

**Use Case:** Best for teams with frontend experience or need custom UI.

**Verdict:** ⚠️ **Overkill** for this project (we don't need custom UI, just debugging).

---

### Option 4: **FastAPI + WebSocket**
**What It Is:** Modern async web framework.

**Pros:**
- ✅ **Async Performance**: Better concurrency than Flask
- ✅ **Auto API Docs**: Swagger UI built-in
- ✅ **31,710 code snippets**: Massive ecosystem

**Cons:**
- ❌ **Manual Frontend**: Same as Flask (need JavaScript)
- ❌ **Async Complexity**: Harder to integrate with SQLAlchemy (sync)
- ❌ **Overkill**: We don't need async performance for debugging

**Verdict:** ❌ **Not recommended** (similar to Flask but adds async complexity).

---

## 🏆 FINAL DECISION: **Dash by Plotly**

### Why Dash Wins:
1. **3D Scatter Plots Out-of-the-Box**: No JavaScript needed
2. **Real-Time Streaming**: `dcc.Interval` + `extendData` for live updates
3. **Python-Only**: Entire stack in one language (no context switching)
4. **Proven for SLAM**: Used by robotics teams for VIO visualization
5. **Low Maintenance**: Less code to debug and maintain

### Deployment Strategy:
```
┌─────────────────────────────────────────────────┐
│ Raspberry Pi 5 (Project-Cortex)                 │
├─────────────────────────────────────────────────┤
│ • main.py (Port 8000) - Main Cortex process     │
│ • data_recorder.py - Records EuRoC datasets     │
│ • SQLite database (Layer 4 Memory)              │
│ • REST API (Port 8001) - Database queries       │
└─────────────────────────────────────────────────┘
                    ↓ HTTP (LAN)
┌─────────────────────────────────────────────────┐
│ LAPTOP SERVER                                    │
├─────────────────────────────────────────────────┤
│ • web_dashboard.py (Port 5000) - Dash server    │
│   (Optional: --disable-dashboard flag)          │
│ • slam_processor.py - VIO/SLAM post-processing  │
│ • Queries RPi SQLite via REST API               │
└─────────────────────────────────────────────────┘
                    ↓ Browser
┌─────────────────────────────────────────────────┐
│ Browser (http://laptop.local:5000)              │
├─────────────────────────────────────────────────┤
│ • 3D Scatter Plot (VIO trajectory from server)  │
│ • GPS Overlay (when outdoors)                   │
│ • Database Table (spatial_objects from RPi)     │
│ • YOLO Detections (Layer 1 from RPi)            │
│ • Whisper Transcripts (Layer 2 from RPi)        │
└─────────────────────────────────────────────────┘
```

---

## 🏗️ SYSTEM ARCHITECTURE

### Component Breakdown:

```
┌──────────────────────────────────────────────────────────────┐
│ WEB DASHBOARD (Dash Server - Port 5000)                     │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ FRONTEND (Dash Components)                          │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ • dcc.Graph (3D Scatter Plot)                       │   │
│  │   - VIO Trajectory (blue line)                      │   │
│  │   - Detected Objects (colored markers)              │   │
│  │   - GPS Points (red markers)                        │   │
│  │   - Camera Orientation (arrows)                     │   │
│  │                                                     │   │
│  │ • dcc.Interval (1 second updates)                   │   │
│  │ • dash_table.DataTable (spatial_objects)            │   │
│  │ • dcc.Dropdown (Select map_id)                      │   │
│  │ • dcc.Slider (Replay timeline for EuRoC datasets)   │   │
│  └─────────────────────────────────────────────────────┘   │
│                          ↓                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ BACKEND (Python Callbacks)                          │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ • update_3d_map() - Fetch latest VIO data          │   │
│  │ • update_object_table() - Query spatial_objects     │   │
│  │ • load_euroc_dataset() - Read EuRoC CSV files      │   │
│  │ • get_coordinate_transform() - VIO ↔ GPS           │   │
│  └─────────────────────────────────────────────────────┘   │
│                          ↓                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ DATABASE LAYER (SQLite + EuRoC)                     │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ • SQLite: spatial_objects, slam_maps, map_anchors   │   │
│  │ • EuRoC: cam0/data.csv, imu0/data.csv, gps0/data.csv│   │
│  │ • Live Sensor Feed: Redis/Queue (optional)          │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 📊 DASHBOARD FEATURES

### Page 1: **Live SLAM Map** (3D Visualization)
```python
# Features:
# - 3D Scatter Plot with camera trajectory
# - Detected objects as colored markers (size = confidence)
# - GPS overlay (red markers when outdoors)
# - Camera orientation arrows
# - Auto-updates every 1 second

Layout:
┌────────────────────────────────────────────────────┐
│ Project-Cortex - Live SLAM Map                     │
├────────────────────────────────────────────────────┤
│ Map: [home_2025-12-22 ▼] | Mode: [Live ▼]        │
├────────────────────────────────────────────────────┤
│                                                    │
│        3D Scatter Plot (Plotly.js)                 │
│                                                    │
│        • Blue line: VIO trajectory                 │
│        • Green markers: Detected objects           │
│        • Red markers: GPS points                   │
│                                                    │
│        [Rotate] [Zoom] [Pan]                       │
│                                                    │
├────────────────────────────────────────────────────┤
│ Stats:                                             │
│ • Keyframes: 142                                   │
│ • Objects: 27                                      │
│ • GPS Fix: Yes (HDOP: 1.2)                        │
│ • Last Update: 0.5s ago                            │
└────────────────────────────────────────────────────┘
```

### Page 2: **Spatial Objects Database**
```python
# Features:
# - Searchable table of spatial_objects
# - Filter by object_class, map_id, time range
# - Click row to highlight on map
# - Export to CSV

Layout:
┌────────────────────────────────────────────────────┐
│ Spatial Objects Database                           │
├────────────────────────────────────────────────────┤
│ Filter: [Class ▼] [Map ▼] [Date Range]           │
├────────────────────────────────────────────────────┤
│ ID | Name       | Class  | VIO (x,y,z) | GPS    │
│ 1  | my wallet  | wallet | 1.2,0.5,-2.0| -      │
│ 2  | Starbucks  | building| -          | 37.4,..│
│ 3  | front door | door   | 0.0,0.0,0.0| -      │
│ ... (27 objects)                                   │
├────────────────────────────────────────────────────┤
│ [Export CSV] [Delete Selected] [View on Map]      │
└────────────────────────────────────────────────────┘
```

### Page 3: **EuRoC Dataset Replay**
```python
# Features:
# - Load recorded EuRoC sessions
# - Scrub timeline with slider
# - Play/pause animation
# - View raw sensor data (CSV)

Layout:
┌────────────────────────────────────────────────────┐
│ EuRoC Dataset Replay                               │
├────────────────────────────────────────────────────┤
│ Dataset: [data_session_001 ▼] [Load]             │
├────────────────────────────────────────────────────┤
│ Timeline: [▶ Play] [⏸ Pause] [⏮ Reset]           │
│ ├─────────────────────────────────────────────────┤│
│ 0s                     150s                   300s │
│                         ↑                          │
│                    Current: 75s                    │
├────────────────────────────────────────────────────┤
│ Sensor Data (t=75s):                               │
│ • Camera: frame_0750.png                           │
│ • IMU: [0.1, 0.2, 9.8] m/s²                       │
│ • GPS: [37.4219, -122.0840] (HDOP: 1.5)          │
└────────────────────────────────────────────────────┘
```

### Page 4: **Coordinate System Inspector**
```python
# Features:
# - Show VIO ↔ GPS transformations
# - Visualize map anchors
# - Test coordinate conversions

Layout:
┌────────────────────────────────────────────────────┐
│ Coordinate System Inspector                        │
├────────────────────────────────────────────────────┤
│ VIO Position:                                      │
│ • x: 1.2m, y: 0.5m, z: -2.0m                      │
│ • Map: home_2025-12-22                             │
│ • Keyframe: 42                                     │
│                                                    │
│ GPS Position (from map anchor):                    │
│ • Lat: 37.4219°, Lon: -122.0840°, Alt: 15.0m      │
│ • Address: "1234 Main St, Mountain View, CA"      │
│ • Accuracy: 2.5m (HDOP: 1.2)                      │
│                                                    │
│ Transformation Matrix (VIO → GPS):                 │
│ [ 1.00  0.00  0.00  37.4219 ]                     │
│ [ 0.00  1.00  0.00 -122.0840]                     │
│ [ 0.00  0.00  1.00  15.0000 ]                     │
└────────────────────────────────────────────────────┘
```

---

## 🛠️ TECHNOLOGY STACK

### Backend:
- **Web Framework**: Dash 3.2.0 (Plotly)
- **Database**: SQLAlchemy 2.0 + SQLite
- **Real-Time**: `dcc.Interval` (polling) or Redis Pub/Sub (advanced)
- **EuRoC Loader**: `pandas` + `evo` library
- **Coordinate Math**: `numpy`, `pyproj` (WGS84 ↔ Cartesian)

### Frontend (Auto-Generated by Dash):
- **Plotting**: Plotly.js (3D Scatter, Mapbox)
- **Tables**: Dash DataTable
- **UI Components**: Dash Core Components (dcc), Dash HTML Components (html)

### Deployment:
- **Development**: `python web_dashboard.py` (localhost:5000)
- **Production**: Gunicorn (WSGI server) or systemd service

---

## 📦 INSTALLATION REQUIREMENTS

```bash
# Core dependencies
pip install dash==3.2.0
pip install dash-bootstrap-components  # Optional: Better styling
pip install plotly==5.18.0
pip install pandas numpy pyproj
pip install evo  # EuRoC dataset loading
pip install sqlalchemy

# Optional: Redis for pub/sub streaming (advanced)
pip install redis

# Optional: Better WSGI server for production
pip install gunicorn
```

**Total Size:** ~150MB installed, ~80MB runtime

---

## 🚀 DEVELOPMENT WORKFLOW

### Phase 1: Laptop Prototype (Week 1)
**Goal:** Build basic 3D map visualization with dummy data.

**Tasks:**
1. ✅ Install Dash: `pip install dash plotly`
2. ✅ Create `src/web_dashboard/app.py` with 3D scatter plot
3. ✅ Load dummy VIO trajectory (sine wave)
4. ✅ Test live updates with `dcc.Interval`
5. ✅ Add object markers (random positions)

**Success Criteria:**
- Browser shows rotating 3D plot
- Plot updates every 1 second with new data point
- No errors in console

---

### Phase 2: Database Integration (Week 1-2)
**Goal:** Connect dashboard to real SQLite database.

**Tasks:**
1. ✅ Create `src/web_dashboard/db_loader.py` (SQLAlchemy queries)
2. ✅ Load `spatial_objects` table into Dash DataTable
3. ✅ Query VIO positions by `map_id`
4. ✅ Add GPS overlay (separate trace)
5. ✅ Implement coordinate system conversion (VIO → GPS)

**Success Criteria:**
- Dashboard shows real objects from database
- Clicking table row highlights object on map
- GPS points render correctly

---

### Phase 3: EuRoC Dataset Viewer (Week 2)
**Goal:** Load and replay recorded sessions.

**Tasks:**
1. ✅ Integrate `evo` library for EuRoC loading
2. ✅ Add timeline slider (scrub through dataset)
3. ✅ Display sensor data at selected timestamp
4. ✅ Animate trajectory playback (play/pause buttons)

**Success Criteria:**
- Load `data_session_001` without errors
- Slider updates 3D plot in real-time
- Raw CSV data visible in table

---

### Phase 4: Laptop Server Deployment (Week 2-3)
**Goal:** Run dashboard on laptop server, query RPi via REST API.

**Tasks:**
1. ✅ Keep `src/web_dashboard/` on laptop only
2. ✅ Install dependencies on laptop: `pip install dash plotly pandas sqlalchemy requests`
3. ✅ Create RPi REST API endpoint: `src/api/database_api.py`
4. ✅ Test dashboard: `python src/web_dashboard/app.py`
5. ✅ Access from browser: http://localhost:5000
6. ✅ Add disable flag:
  ```python
  # src/web_dashboard/app.py
  if __name__ == '__main__':
      parser = argparse.ArgumentParser()
      parser.add_argument('--disable-dashboard', action='store_true')
      args = parser.parse_args()
      
      if not args.disable_dashboard:
          app.run_server(host='0.0.0.0', port=5000)
      else:
          print("Dashboard disabled via --disable-dashboard")
  ```
7. ✅ Test RPi REST API: `curl http://raspberrypi.local:8001/api/objects`

**Success Criteria:**
- ✅ Dashboard runs only on laptop
- ✅ Queries RPi database via REST API
- ✅ Can disable with `--disable-dashboard` flag

---

### Phase 5: Advanced Features (Week 3-4)
**Goal:** Polish UI and add power-user features.

**Tasks:**
1. ⏳ Add Redis Pub/Sub for true WebSocket streaming (optional)
2. ⏳ Implement coordinate system inspector
3. ⏳ Add CSV export for spatial_objects
4. ⏳ Mobile-responsive design (Dash Bootstrap Components)
5. ⏳ Add authentication (optional: basic auth)

**Success Criteria:**
- Dashboard looks professional (Bootstrap theme)
- All features tested and documented

---

## 📝 COMPLETE TODO LIST

### **TODO #1: Setup Dash Development Environment**
**Priority:** 🔴 HIGH (Blocks all other tasks)  
**Time Estimate:** 30 minutes

**Subtasks:**
- [ ] Create virtual environment: `python -m venv venv_dashboard`
- [ ] Activate: `venv_dashboard\Scripts\activate` (Windows)
- [ ] Install dependencies: `pip install dash plotly pandas sqlalchemy`
- [ ] Create folder structure:
  ```
  src/web_dashboard/
    ├── app.py (main Dash app)
    ├── db_loader.py (database queries)
    ├── euroc_loader.py (EuRoC dataset reader)
    ├── callbacks.py (Dash callback functions)
    └── layouts/ (page layouts)
        ├── slam_map.py
        ├── object_table.py
        └── euroc_replay.py
  ```
- [ ] Test installation: `python -c "import dash; print(dash.__version__)"`

**Success Criteria:**
- ✅ Dash 3.2.0 installed
- ✅ Folder structure created
- ✅ No import errors

---

### **TODO #2: Create Basic 3D Scatter Plot (Dummy Data)**
**Priority:** 🔴 HIGH  
**Time Estimate:** 1 hour

**Subtasks:**
- [ ] Create `src/web_dashboard/app.py`:
  ```python
  import dash
  from dash import dcc, html
  import plotly.graph_objects as go
  import numpy as np
  
  app = dash.Dash(__name__)
  
  # Dummy VIO trajectory (sine wave)
  t = np.linspace(0, 10, 100)
  x = np.sin(t)
  y = np.cos(t)
  z = t * 0.1
  
  fig = go.Figure(data=[
      go.Scatter3d(x=x, y=y, z=z, mode='lines+markers', name='VIO Path')
  ])
  
  app.layout = html.Div([
      html.H1("Project-Cortex - SLAM Map"),
      dcc.Graph(figure=fig)
  ])
  
  if __name__ == '__main__':
      app.run_server(debug=True, host='0.0.0.0', port=5000)
  ```
- [ ] Run: `python src/web_dashboard/app.py`
- [ ] Open browser: http://localhost:5000
- [ ] Verify 3D plot renders

**Success Criteria:**
- ✅ Dashboard loads in browser
- ✅ 3D spiral trajectory visible
- ✅ Can rotate/zoom plot

---

### **TODO #3: Add Live Updates with dcc.Interval**
**Priority:** 🔴 HIGH  
**Time Estimate:** 1 hour

**Subtasks:**
- [ ] Add `dcc.Interval` component:
  ```python
  app.layout = html.Div([
      html.H1("Project-Cortex - SLAM Map"),
      dcc.Graph(id='live-slam-map'),
      dcc.Interval(id='interval', interval=1000, n_intervals=0)
  ])
  ```
- [ ] Create callback to update plot:
  ```python
  from dash import Input, Output
  
  @app.callback(
      Output('live-slam-map', 'extendData'),
      Input('interval', 'n_intervals')
  )
  def update_map(n):
      # Simulate new VIO position
      new_x = np.sin(n * 0.1)
      new_y = np.cos(n * 0.1)
      new_z = n * 0.01
      return {'x': [[new_x]], 'y': [[new_y]], 'z': [[new_z]]}, [0], 100
  ```
- [ ] Test: Plot should update every 1 second

**Success Criteria:**
- ✅ Plot animates in real-time
- ✅ New points appear every second
- ✅ Old points fade (max 100 points)

---

### **TODO #4: Integrate SQLite Database (spatial_objects)**
**Priority:** 🟡 MEDIUM  
**Time Estimate:** 2 hours

**Subtasks:**
- [ ] Create `src/web_dashboard/db_loader.py`:
  ```python
  from sqlalchemy import create_engine, text
  import pandas as pd
  import json
  
  engine = create_engine('sqlite:///cortex_memory.db')
  
  def get_all_objects():
      query = "SELECT * FROM spatial_objects"
      df = pd.read_sql(query, engine)
      return df
  
  def get_vio_positions(map_id):
      query = text("""
          SELECT object_name, vio_position_json
          FROM spatial_objects
          WHERE vio_map_id = :map_id
      """)
      with engine.connect() as conn:
          result = conn.execute(query, {"map_id": map_id})
          positions = []
          for row in result:
              vio = json.loads(row.vio_position_json)
              positions.append({
                  'name': row.object_name,
                  'x': vio['x'],
                  'y': vio['y'],
                  'z': vio['z']
              })
          return positions
  ```
- [ ] Update callback to fetch real data:
  ```python
  @app.callback(
      Output('live-slam-map', 'figure'),
      Input('interval', 'n_intervals')
  )
  def update_map_real(n):
      positions = get_vio_positions('home_2025-12-22')
      x = [p['x'] for p in positions]
      y = [p['y'] for p in positions]
      z = [p['z'] for p in positions]
      
      fig = go.Figure(data=[
          go.Scatter3d(x=x, y=y, z=z, mode='markers', name='Objects')
      ])
      return fig
  ```
- [ ] Test with real database

**Success Criteria:**
- ✅ Dashboard loads objects from SQLite
- ✅ Object names appear as hover text
- ✅ No database connection errors

---

### **TODO #5: Add Spatial Objects DataTable**
**Priority:** 🟡 MEDIUM  
**Time Estimate:** 1.5 hours

**Subtasks:**
- [ ] Add Dash DataTable:
  ```python
  from dash import dash_table
  
  app.layout = html.Div([
      html.H1("Spatial Objects Database"),
      dash_table.DataTable(
          id='object-table',
          columns=[
              {'name': 'ID', 'id': 'id'},
              {'name': 'Name', 'id': 'object_name'},
              {'name': 'Class', 'id': 'object_class'},
              {'name': 'VIO (x,y,z)', 'id': 'vio_position_json'},
              {'name': 'GPS', 'id': 'gps_position_json'}
          ],
          data=[],
          page_size=20,
          filter_action='native',
          sort_action='native'
      )
  ])
  ```
- [ ] Callback to populate table:
  ```python
  @app.callback(
      Output('object-table', 'data'),
      Input('interval', 'n_intervals')
  )
  def update_table(n):
      df = get_all_objects()
      return df.to_dict('records')
  ```
- [ ] Add "View on Map" button (click row → highlight on 3D plot)

**Success Criteria:**
- ✅ Table shows all objects
- ✅ Searchable and sortable
- ✅ Clicking row highlights on map

---

### **TODO #6: Implement EuRoC Dataset Loader**
**Priority:** 🟢 LOW  
**Time Estimate:** 2 hours

**Subtasks:**
- [ ] Install evo library: `pip install evo`
- [ ] Create `src/web_dashboard/euroc_loader.py`:
  ```python
  import pandas as pd
  from pathlib import Path
  
  def load_euroc_session(session_path):
      cam_csv = Path(session_path) / 'cam0' / 'data.csv'
      imu_csv = Path(session_path) / 'imu0' / 'data.csv'
      gps_csv = Path(session_path) / 'gps0' / 'data.csv'
      
      cam_df = pd.read_csv(cam_csv, names=['timestamp_ns', 'filename'])
      imu_df = pd.read_csv(imu_csv, names=['timestamp_ns', 'wx', 'wy', 'wz', 'ax', 'ay', 'az'])
      gps_df = pd.read_csv(gps_csv, names=['timestamp_ns', 'lat', 'lon', 'alt', 'hdop'])
      
      return cam_df, imu_df, gps_df
  ```
- [ ] Add timeline slider:
  ```python
  dcc.Slider(
      id='timeline-slider',
      min=0,
      max=300,
      step=1,
      value=0,
      marks={i: f'{i}s' for i in range(0, 301, 60)}
  )
  ```
- [ ] Callback to update plot based on timestamp

**Success Criteria:**
- ✅ Load EuRoC dataset without errors
- ✅ Slider updates visualization
- ✅ Can scrub through entire session

---

### **TODO #7: Add GPS Overlay (Mapbox Layer)**
**Priority:** 🟢 LOW  
**Time Estimate:** 1.5 hours

**Subtasks:**
- [ ] Add second trace for GPS points:
  ```python
  fig = go.Figure(data=[
      go.Scatter3d(x=vio_x, y=vio_y, z=vio_z, mode='lines', name='VIO Path'),
      go.Scatter3d(x=gps_lon, y=gps_lat, z=gps_alt, mode='markers', 
                   marker=dict(size=8, color='red'), name='GPS')
  ])
  ```
- [ ] Add coordinate transformation (VIO → GPS using map anchors)
- [ ] Test with outdoor session

**Success Criteria:**
- ✅ GPS points render on map
- ✅ Coordinate transformation accurate
- ✅ GPS points align with VIO trajectory

---

### **TODO #8: Deploy to Raspberry Pi 5**
**Priority:** 🟡 MEDIUM  
**Time Estimate:** 2 hours

**Subtasks:**
- [ ] Copy `src/web_dashboard/` to RPi: `scp -r src/web_dashboard/ pi@raspberrypi.local:~/ProjectCortex/src/`
- [ ] Install dependencies on RPi: `pip install dash plotly pandas sqlalchemy`
- [ ] Test dashboard: `python src/web_dashboard/app.py`
- [ ] Access from laptop: http://raspberrypi.local:5000
- [ ] Create systemd service for auto-start:
  ```ini
  [Unit]
  Description=Project-Cortex Web Dashboard
  After=network.target
  
  [Service]
  ExecStart=/home/pi/ProjectCortex/venv/bin/python /home/pi/ProjectCortex/src/web_dashboard/app.py
  WorkingDirectory=/home/pi/ProjectCortex
  Restart=always
  User=pi
  
  [Install]
  WantedBy=multi-user.target
  ```
- [ ] Enable service: `sudo systemctl enable cortex-dashboard.service`

**Success Criteria:**
- ✅ Dashboard accessible from laptop
- ✅ Auto-starts on RPi boot
- ✅ <500ms latency

---

### **TODO #9: Add Bootstrap Styling (Optional)**
**Priority:** 🟢 LOW  
**Time Estimate:** 1 hour

**Subtasks:**
- [ ] Install: `pip install dash-bootstrap-components`
- [ ] Update app:
  ```python
  import dash_bootstrap_components as dbc
  
  app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
  
  app.layout = dbc.Container([
      dbc.Row([
          dbc.Col(html.H1("Project-Cortex - SLAM Map"), width=12)
      ]),
      dbc.Row([
          dbc.Col(dcc.Graph(id='live-slam-map'), width=8),
          dbc.Col(dash_table.DataTable(id='object-table'), width=4)
      ])
  ])
  ```

**Success Criteria:**
- ✅ Dashboard looks professional
- ✅ Mobile-responsive layout

---

### **TODO #10: Document Workflow Integration**
**Priority:** 🟡 MEDIUM  
**Time Estimate:** 1 hour

**Subtasks:**
- [ ] Update `docs/implementation/data-recorder-architecture.md`:
  - Add section: "Web Dashboard Integration"
  - Document REST API endpoints (if added)
  - Screenshot examples
- [ ] Update README.md:
  ```markdown
  ## Web Dashboard
  
  View live SLAM maps and spatial memory:
  
  ```bash
  python src/web_dashboard/app.py
  # Open: http://localhost:5000
  ```
  ```
- [ ] Create `docs/implementation/web-dashboard-user-guide.md`

**Success Criteria:**
- ✅ Documentation complete
- ✅ Screenshots added
- ✅ User can follow guide

---

## 📈 TIMELINE

| Week | Phase | Deliverable |
|------|-------|-------------|
| **Week 1, Days 1-2** | Setup + Basic Plot | Dashboard shows dummy 3D trajectory with live updates |
| **Week 1, Days 3-5** | Database Integration | Dashboard loads real objects from SQLite |
| **Week 2, Days 1-3** | EuRoC Viewer | Timeline slider to replay recorded sessions |
| **Week 2, Days 4-5** | RPi Deployment | Dashboard accessible from laptop via LAN |
| **Week 3** | Polish + Docs | Bootstrap styling, documentation complete |

**Total Estimated Time:** 2-3 weeks (part-time)

---

## 🔒 SECURITY CONSIDERATIONS

### Development (Laptop):
- ✅ No authentication needed (localhost only)

### Production (RPi on LAN):
- ⚠️ **Risk**: Anyone on LAN can access dashboard
- ✅ **Mitigation 1**: Basic HTTP Auth (username/password)
- ✅ **Mitigation 2**: Firewall rules (only allow laptop IP)
- ✅ **Mitigation 3**: VPN access only (WireGuard)

**Recommendation:** Start with no auth (development), add Basic Auth before deployment.

---

## 🎓 KEY LEARNINGS

1. **Dash is Perfect for Data Viz**: 3D plots + real-time updates in ~100 lines
2. **No JavaScript Required**: Entire stack in Python (huge win)
3. **SQLite JSON Columns**: Need custom distance functions (no spatial extensions)
4. **EuRoC Format**: Industry-standard, evo library makes loading trivial
5. **RPi 5 Performance**: 4GB RAM is sufficient for Dash + Cortex simultaneously

---

## 🚀 NEXT ACTIONS

**IMMEDIATE** (Start Now):
1. ✅ Install Dash: `pip install dash plotly`
2. ✅ Create dummy 3D plot (TODO #2)
3. ✅ Test live updates (TODO #3)

**THIS WEEK**:
1. ✅ Integrate SQLite database (TODO #4)
2. ✅ Add object table (TODO #5)
3. ✅ Test on laptop with real Cortex data

**NEXT WEEK**:
1. ⏳ Implement EuRoC viewer (TODO #6)
2. ⏳ Deploy to RPi 5 (TODO #8)
3. ⏳ Test LAN access from laptop

---

**End of Architecture Document**  
*Next Step: Execute TODO #1 - Setup Dash Environment* 🚀
