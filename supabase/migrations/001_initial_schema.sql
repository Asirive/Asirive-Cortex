-- =====================================================
-- ProjectCortex v2.0 - Supabase Database Schema
-- 3-Tier Hybrid Architecture with Cloud Storage
-- =====================================================
-- Author: Haziq (@IRSPlays) + AI Implementer (Claude)
-- Date: January 8, 2026
-- Status: Initial Schema (Free Tier Compatible)
-- =====================================================

-- =====================================================
-- TABLE: detections (Core AI output from Layer 0 + Layer 1)
-- Stores all object detections from both Guardian and Learner
-- =====================================================
CREATE TABLE IF NOT EXISTS detections (
    id BIGSERIAL PRIMARY KEY,
    device_id UUID DEFAULT gen_random_uuid(),

    -- Detection metadata
    layer TEXT NOT NULL,  -- 'guardian' or 'learner'
    class_name TEXT NOT NULL,
    confidence NUMERIC(3, 2) NOT NULL,  -- 0.00 to 1.00

    -- Bounding box (normalized [0-1])
    bbox_x1 NUMERIC(3, 2),
    bbox_y1 NUMERIC(3, 2),
    bbox_x2 NUMERIC(3, 2),
    bbox_y2 NUMERIC(3, 2),
    bbox_area NUMERIC(5, 2),

    -- Mode-specific fields
    detection_mode TEXT,  -- 'prompt_free', 'text_prompts', 'visual_prompts'
    source TEXT,  -- 'gemini', 'maps', 'memory', 'base'

    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    CONSTRAINT valid_confidence CHECK (confidence BETWEEN 0 AND 1),
    CONSTRAINT valid_bbox_area CHECK (bbox_area BETWEEN 0 AND 1)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_detections_device_time ON detections(device_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_detections_class ON detections(class_name);
CREATE INDEX IF NOT EXISTS idx_detections_layer ON detections(layer);
CREATE INDEX IF NOT EXISTS idx_detections_created_at ON detections(created_at DESC);

-- Enable Realtime (for dashboard live updates)
ALTER PUBLICATION supabase_realtime ADD TABLE detections;

-- =====================================================
-- TABLE: queries (User voice commands + AI responses)
-- Stores all user interactions and routing decisions
-- =====================================================
CREATE TABLE IF NOT EXISTS queries (
    id BIGSERIAL PRIMARY KEY,
    device_id UUID DEFAULT gen_random_uuid(),

    -- Query metadata
    user_query TEXT NOT NULL,
    transcribed_text TEXT NOT NULL,  -- Whisper output

    -- Routing decision
    routed_layer TEXT NOT NULL,  -- 'layer1', 'layer2', 'layer3'
    routing_confidence NUMERIC(3, 2),
    detection_mode TEXT,  -- 'PROMPT_FREE', 'TEXT_PROMPTS', 'VISUAL_PROMPTS'

    -- Response (AI output)
    ai_response TEXT,
    response_latency_ms INTEGER,  -- End-to-end latency
    tier_used TEXT,  -- 'local', 'gemini_live', 'gemini_tts', 'glm4v'

    created_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT valid_routing_confidence CHECK (routing_confidence BETWEEN 0 AND 1)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_queries_device_time ON queries(device_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_queries_layer ON queries(routed_layer);
CREATE INDEX IF NOT EXISTS idx_queries_created_at ON queries(created_at DESC);

-- =====================================================
-- TABLE: memories (Layer 4 persistent object storage)
-- Stores visual prompts, user memories, SLAM coordinates
-- =====================================================
CREATE TABLE IF NOT EXISTS memories (
    id BIGSERIAL PRIMARY KEY,
    device_id UUID DEFAULT gen_random_uuid(),

    -- Memory metadata
    memory_type TEXT NOT NULL,  -- 'visual_prompt', 'location', 'user_note'
    object_name TEXT NOT NULL,

    -- Visual prompt data
    reference_image_url TEXT,  -- Supabase Storage URL
    visual_embedding_path TEXT,  -- Storage path for .npz file
    bbox_data JSONB,  -- [[x1,y1,x2,y2], ...]

    -- SLAM coordinates
    slam_x NUMERIC(10, 3),
    slam_y NUMERIC(10, 3),
    slam_z NUMERIC(10, 3),

    -- User metadata
    tags TEXT[],
    user_notes TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_memories_device ON memories(device_id);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_object ON memories(object_name);
CREATE INDEX IF NOT EXISTS idx_memories_last_seen ON memories(last_seen_at DESC);

-- =====================================================
-- TABLE: adaptive_prompts (Layer 1 learned vocabulary)
-- Stores dynamically learned object classes from Gemini/Maps/Memory
-- =====================================================
CREATE TABLE IF NOT EXISTS adaptive_prompts (
    id BIGSERIAL PRIMARY KEY,
    device_id UUID DEFAULT gen_random_uuid(),

    class_name TEXT NOT NULL,
    source TEXT NOT NULL,  -- 'gemini', 'maps', 'memory', 'base'
    is_base BOOLEAN DEFAULT FALSE,  -- Base vocabulary (never delete)

    -- Usage tracking (for auto-pruning)
    use_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(device_id, class_name)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_prompts_device ON adaptive_prompts(device_id);
CREATE INDEX IF NOT EXISTS idx_prompts_source ON adaptive_prompts(source);
CREATE INDEX IF NOT EXISTS idx_prompts_usage ON adaptive_prompts(use_count DESC);

-- =====================================================
-- FUNCTION: prune_old_prompts()
-- Auto-delete unused prompts (>24h old, used <3 times)
-- =====================================================
CREATE OR REPLACE FUNCTION prune_old_prompts()
RETURNS void AS $$
BEGIN
    DELETE FROM adaptive_prompts
    WHERE is_base = FALSE
    AND EXTRACT(EPOCH FROM (NOW() - created_at)) / 3600 > 24  -- Older than 24h
    AND use_count < 3;  -- Used less than 3 times
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- TABLE: system_logs (Monitoring & debugging)
-- Stores system logs with performance metrics
-- =====================================================
CREATE TABLE IF NOT EXISTS system_logs (
    id BIGSERIAL PRIMARY KEY,
    device_id UUID DEFAULT gen_random_uuid(),

    level TEXT NOT NULL,  -- 'DEBUG', 'INFO', 'WARNING', 'ERROR'
    component TEXT NOT NULL,  -- 'layer0', 'layer1', 'layer2', 'layer3', 'layer4'
    message TEXT NOT NULL,

    -- Performance metrics
    latency_ms INTEGER,
    cpu_percent NUMERIC(5, 2),
    memory_mb INTEGER,

    error_trace TEXT,
    additional_data JSONB,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_logs_device_time ON system_logs(device_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_logs_level ON system_logs(level);
CREATE INDEX IF NOT EXISTS idx_logs_component ON system_logs(component);

-- Enable Realtime (for ERROR-level monitoring)
ALTER PUBLICATION supabase_realtime ADD TABLE system_logs;

-- =====================================================
-- TABLE: device_status (Real-time device monitoring)
-- Tracks device heartbeat, metrics, and state
-- =====================================================
CREATE TABLE IF NOT EXISTS device_status (
    device_id UUID PRIMARY KEY,
    device_name TEXT NOT NULL,

    -- Status
    is_online BOOLEAN DEFAULT FALSE,
    last_heartbeat TIMESTAMPTZ DEFAULT NOW(),

    -- Metrics
    battery_percent INTEGER,
    cpu_percent NUMERIC(5, 2),
    memory_mb INTEGER,
    temperature NUMERIC(5, 2),

    -- Active features
    active_layers TEXT[],
    current_mode TEXT,

    -- Location
    latitude NUMERIC(10, 6),
    longitude NUMERIC(10, 6),

    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index
CREATE INDEX IF NOT EXISTS idx_status_online ON device_status(is_online);
CREATE INDEX IF NOT EXISTS idx_status_heartbeat ON device_status(last_heartbeat DESC);

-- Enable Realtime (for live dashboard)
ALTER PUBLICATION supabase_realtime ADD TABLE device_status;

-- =====================================================
-- TABLE: device_commands (Remote command queue)
-- Stores commands sent from dashboard to RPi
-- =====================================================
CREATE TABLE IF NOT EXISTS device_commands (
    id BIGSERIAL PRIMARY KEY,
    device_id UUID NOT NULL,

    command TEXT NOT NULL,  -- 'switch_mode', 'reboot', 'sync_prompts', etc.
    params JSONB,  -- Command parameters

    status TEXT DEFAULT 'pending',  -- 'pending', 'executed', 'failed'

    created_at TIMESTAMPTZ DEFAULT NOW(),
    executed_at TIMESTAMPTZ
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_commands_device_status ON device_commands(device_id, status);
CREATE INDEX IF NOT EXISTS idx_commands_created ON device_commands(created_at DESC);

-- Enable Realtime (for RPi to listen for commands)
ALTER PUBLICATION supabase_realtime ADD TABLE device_commands;

-- =====================================================
-- HELPER FUNCTION: update_device_heartbeat()
-- Updates device_status with latest metrics
-- =====================================================
CREATE OR REPLACE FUNCTION update_device_heartbeat(
    p_device_id UUID,
    p_device_name TEXT,
    p_battery INTEGER,
    p_cpu NUMERIC,
    p_memory INTEGER,
    p_temp NUMERIC,
    p_active_layers TEXT[],
    p_current_mode TEXT,
    p_lat NUMERIC,
    p_lon NUMERIC
)
RETURNS void AS $$
BEGIN
    INSERT INTO device_status (
        device_id, device_name, battery_percent, cpu_percent,
        memory_mb, temperature, active_layers, current_mode,
        latitude, longitude, is_online, last_heartbeat
    )
    VALUES (
        p_device_id, p_device_name, p_battery, p_cpu,
        p_memory, p_temp, p_active_layers, p_current_mode,
        p_lat, p_lon, TRUE, NOW()
    )
    ON CONFLICT (device_id) DO UPDATE SET
        device_name = EXCLUDED.device_name,
        battery_percent = EXCLUDED.battery_percent,
        cpu_percent = EXCLUDED.cpu_percent,
        memory_mb = EXCLUDED.memory_mb,
        temperature = EXCLUDED.temperature,
        active_layers = EXCLUDED.active_layers,
        current_mode = EXCLUDED.current_mode,
        latitude = EXCLUDED.latitude,
        longitude = EXCLUDED.longitude,
        is_online = TRUE,
        last_heartbeat = NOW(),
        updated_at = NOW();
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- ROW LEVEL SECURITY (RLS) POLICIES
-- Ensures devices can only access their own data
-- =====================================================

-- Enable RLS on all tables
ALTER TABLE detections ENABLE ROW LEVEL SECURITY;
ALTER TABLE queries ENABLE ROW LEVEL SECURITY;
ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE adaptive_prompts ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE device_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE device_commands ENABLE ROW LEVEL SECURITY;

-- Policy: Devices can read/write their own data
CREATE POLICY "device_isolation_detections"
ON detections FOR ALL
USING (device_id = current_setting('app.device_id', true)::UUID);

CREATE POLICY "device_isolation_queries"
ON queries FOR ALL
USING (device_id = current_setting('app.device_id', true)::UUID);

CREATE POLICY "device_isolation_memories"
ON memories FOR ALL
USING (device_id = current_setting('app.device_id', true)::UUID);

CREATE POLICY "device_isolation_prompts"
ON adaptive_prompts FOR ALL
USING (device_id = current_setting('app.device_id', true)::UUID);

CREATE POLICY "device_isolation_logs"
ON system_logs FOR ALL
USING (device_id = current_setting('app.device_id', true)::UUID);

CREATE POLICY "device_isolation_status"
ON device_status FOR ALL
USING (device_id = current_setting('app.device_id', true)::UUID);

CREATE POLICY "device_isolation_commands"
ON device_commands FOR ALL
USING (device_id = current_setting('app.device_id', true)::UUID);

-- =====================================================
-- SAMPLE DATA (Optional - for testing)
-- =====================================================

-- Insert sample device status
INSERT INTO device_status (
    device_id, device_name, is_online, battery_percent,
    cpu_percent, memory_mb, current_mode
) VALUES (
    gen_random_uuid(), 'RPi5-Cortex-001', TRUE, 85, 45.2, 2048, 'TEXT_PROMPTS'
);

-- =====================================================
-- VIEWS (For convenient querying)
-- =====================================================

-- View: Detection statistics by class
CREATE OR REPLACE VIEW detection_stats AS
SELECT
    class_name,
    layer,
    source,
    COUNT(*) as detection_count,
    AVG(confidence) as avg_confidence,
    MAX(created_at) as last_detected
FROM detections
GROUP BY class_name, layer, source
ORDER BY detection_count DESC;

-- View: Recent system errors (last 24h)
CREATE OR REPLACE VIEW recent_errors AS
SELECT *
FROM system_logs
WHERE level = 'ERROR'
AND created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC;

-- =====================================================
-- END OF SCHEMA
-- =====================================================

-- Verification queries:
-- SELECT COUNT(*) FROM detections;  -- Should be 0 initially
-- SELECT COUNT(*) FROM device_status;  -- Should be 1 (sample data)
-- SELECT * FROM detection_stats;  -- Empty view initially
-- SELECT * FROM recent_errors;  -- Empty view initially
