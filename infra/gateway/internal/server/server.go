// Package server is the fleet gateway: device WebSocket endpoint, dashboard API,
// tier enforcement. Auth here is a shared dev token; mTLS + the E2E sealed
// envelope are the production path (see infra/AGENTS.md).
package server

import (
	"crypto/subtle"
	"encoding/json"
	"io"
	"io/fs"
	"log"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/asirive/cortex/gateway/internal/fleet"
	pb "github.com/asirive/cortex/gateway/internal/gen/cortex/v1"
	"github.com/asirive/cortex/gateway/internal/ota"
	"github.com/asirive/cortex/gateway/web"
	"github.com/gorilla/websocket"
	"google.golang.org/protobuf/proto"
)

const (
	schemaVersion   = 1
	maxClockSkewMs  = 5 * 60 * 1000
	defaultHBSecond = 5
)

type Server struct {
	Fleet    *fleet.Store
	DevToken string // shared secret for device and dashboard in dev
	OTA      *ota.Engine
	up       websocket.Upgrader

	mu    sync.Mutex
	conns map[string]*devConn
	audit []AuditLine
}

type AuditLine struct {
	TsMs   int64  `json:"ts_ms"`
	Actor  string `json:"actor"`
	Action string `json:"action"`
	Target string `json:"target"`
	Result string `json:"result"`
}

type devConn struct {
	ws      *websocket.Conn
	wmu     sync.Mutex
	tier    pb.Tier
	bench   bool
	id      string
	lastSeq uint64
	ring    pb.Ring
	counter uint64
	offered string
	seq     uint64
}

func New(f *fleet.Store, token string) *Server {
	return &Server{Fleet: f, DevToken: token, conns: map[string]*devConn{},
		up: websocket.Upgrader{CheckOrigin: func(*http.Request) bool { return true }}}
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/ws/device", s.deviceWS)
	mux.HandleFunc("GET /api/summary", s.auth(s.summary))
	mux.HandleFunc("GET /api/devices", s.auth(s.devices))
	mux.HandleFunc("GET /api/devices/{id}", s.auth(s.device))
	mux.HandleFunc("POST /api/devices/{id}/command", s.auth(s.command))
	mux.HandleFunc("GET /api/audit", s.auth(s.auditLog))
	mux.HandleFunc("GET /api/releases", s.auth(s.releases))
	mux.HandleFunc("POST /api/releases", s.auth(s.registerRelease))
	mux.HandleFunc("POST /api/releases/{id}/halt", s.auth(s.haltRelease))
	sub, _ := fs.Sub(web.FS, ".")
	mux.Handle("/", http.FileServer(http.FS(sub)))
	return mux
}

func (s *Server) auth(h http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		tok := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
		if tok == "" {
			tok = r.URL.Query().Get("token")
		}
		if subtle.ConstantTimeCompare([]byte(tok), []byte(s.DevToken)) != 1 {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		h(w, r)
	}
}

func (s *Server) deviceWS(w http.ResponseWriter, r *http.Request) {
	tok := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
	if subtle.ConstantTimeCompare([]byte(tok), []byte(s.DevToken)) != 1 {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	ws, err := s.up.Upgrade(w, r, nil)
	if err != nil {
		return
	}
	defer ws.Close()
	ws.SetReadLimit(4 << 20)

	c := &devConn{ws: ws}
	var env pb.Envelope
	if !s.readEnv(c, &env) || env.Type != pb.PayloadType_PAYLOAD_TYPE_HELLO {
		return
	}
	var hello pb.Hello
	if proto.Unmarshal(env.Payload, &hello) != nil || env.Header.DeviceId == "" {
		return
	}
	c.id, c.tier, c.bench = env.Header.DeviceId, hello.Tier, hello.BenchDevice
	c.ring, c.counter = hello.Ring, hello.VersionCounter
	iv := hello.HeartbeatIntervalS
	if iv == 0 {
		iv = defaultHBSecond
	}
	hello.HeartbeatIntervalS = iv
	now := time.Now()
	s.Fleet.Connect(c.id, &hello, now)
	s.mu.Lock()
	s.conns[c.id] = c
	s.mu.Unlock()
	defer func() {
		s.mu.Lock()
		if s.conns[c.id] == c {
			delete(s.conns, c.id)
		}
		s.mu.Unlock()
		s.Fleet.Disconnect(c.id, time.Now())
	}()
	s.send(c, pb.PayloadType_PAYLOAD_TYPE_HELLO_ACK, &pb.HelloAck{
		Accepted: true, HeartbeatIntervalS: iv, LastSeenSeq: c.lastSeq, ServerTsMs: now.UnixMilli()})

	s.offer(c)
	for {
		ws.SetReadDeadline(time.Now().Add(time.Duration(iv*4) * time.Second))
		if !s.readEnv(c, &env) {
			return
		}
		s.dispatch(c, &env)
	}
}

func (s *Server) readEnv(c *devConn, env *pb.Envelope) bool {
	_, data, err := c.ws.ReadMessage()
	if err != nil {
		return false
	}
	*env = pb.Envelope{}
	if proto.Unmarshal(data, env) != nil || env.Header == nil {
		return false
	}
	h := env.Header
	if h.SchemaVersion != schemaVersion {
		return false
	}
	// replay protection: strictly increasing seq, clock within window
	if c.id != "" && (h.DeviceId != c.id || h.Seq <= c.lastSeq) {
		return false
	}
	if d := time.Now().UnixMilli() - h.TsMs; d > maxClockSkewMs || d < -maxClockSkewMs {
		return false
	}
	c.lastSeq = h.Seq
	return true
}

func isAlphaOnly(t pb.PayloadType) bool { return t >= pb.PayloadType_PAYLOAD_TYPE_DEBUG_COMMAND }

func (s *Server) dispatch(c *devConn, env *pb.Envelope) {
	now := time.Now()
	if isAlphaOnly(env.Type) && !(c.tier == pb.Tier_TIER_ALPHA && c.bench) {
		s.Fleet.AddEvent(c.id, fleet.Event{TsMs: now.UnixMilli(), Kind: "rejected",
			Summary: "alpha-only message from non-alpha device: " + env.Type.String()})
		return
	}
	switch env.Type {
	case pb.PayloadType_PAYLOAD_TYPE_HEARTBEAT:
		var m pb.Heartbeat
		if proto.Unmarshal(env.Payload, &m) == nil {
			s.Fleet.Heartbeat(c.id, &m, now)
			s.offer(c)
		}
	case pb.PayloadType_PAYLOAD_TYPE_LOG_BATCH:
		var m pb.LogBatch
		if proto.Unmarshal(env.Payload, &m) == nil {
			entries := m.Entries
			if c.tier != pb.Tier_TIER_ALPHA { // beta/stable: trimmed logs only
				kept := entries[:0]
				for _, e := range entries {
					if e.Level >= pb.LogLevel_LOG_LEVEL_WARN {
						kept = append(kept, e)
					}
				}
				entries = kept
			}
			s.Fleet.AddLogs(c.id, entries)
		}
	case pb.PayloadType_PAYLOAD_TYPE_EVENT:
		var m pb.Event
		if proto.Unmarshal(env.Payload, &m) == nil {
			s.Fleet.AddEvent(c.id, fleet.Event{TsMs: m.TsMs, Kind: m.Kind, Summary: m.Summary, Attrs: m.Attrs})
		}
	case pb.PayloadType_PAYLOAD_TYPE_OTA_PROGRESS:
		var m pb.OtaProgress
		if proto.Unmarshal(env.Payload, &m) == nil {
			s.Fleet.SetOta(c.id, &fleet.Ota{ReleaseID: m.ReleaseId, Stage: m.Stage.String(), Percent: m.Percent})
		}
	case pb.PayloadType_PAYLOAD_TYPE_OTA_RESULT:
		var m pb.OtaResult
		if proto.Unmarshal(env.Payload, &m) == nil {
			s.Fleet.SetOta(c.id, &fleet.Ota{ReleaseID: m.ReleaseId, Stage: "DONE", Percent: 100, Outcome: m.Outcome.String()})
			if s.OTA != nil {
				o := map[pb.OtaOutcome]ota.Outcome{pb.OtaOutcome_OTA_OUTCOME_COMMITTED: ota.Committed,
					pb.OtaOutcome_OTA_OUTCOME_ROLLED_BACK: ota.RolledBack, pb.OtaOutcome_OTA_OUTCOME_REJECTED: ota.Rejected}[m.Outcome]
				s.OTA.Report(m.ReleaseId, c.id, o)
				if o == ota.Committed {
					c.counter = s.OTA.Counter(m.ReleaseId)
				}
			}
		}
	case pb.PayloadType_PAYLOAD_TYPE_DEBUG_RESULT:
		var m pb.DebugResult
		if proto.Unmarshal(env.Payload, &m) == nil {
			s.Fleet.AddEvent(c.id, fleet.Event{TsMs: now.UnixMilli(), Kind: "debug_result", Summary: m.Output,
				Attrs: map[string]string{"command_id": m.CommandId}})
		}
	case pb.PayloadType_PAYLOAD_TYPE_CAMERA_FRAME, pb.PayloadType_PAYLOAD_TYPE_DATASET_CHUNK:
		// Relay / dataset pipeline plug in here. Camera frames are never persisted.
	}
}

func (s *Server) send(c *devConn, t pb.PayloadType, m proto.Message) error {
	pl, _ := proto.Marshal(m)
	c.seq++
	env := &pb.Envelope{Header: &pb.Header{SchemaVersion: schemaVersion, DeviceId: c.id, Seq: c.seq,
		TsMs: time.Now().UnixMilli()}, Type: t, Payload: pl}
	b, _ := proto.Marshal(env)
	c.wmu.Lock()
	defer c.wmu.Unlock()
	return c.ws.WriteMessage(websocket.BinaryMessage, b)
}

// ---- dashboard API ----

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(v)
}

func (s *Server) summary(w http.ResponseWriter, r *http.Request) {
	type tierCount struct {
		Total  int `json:"total"`
		Online int `json:"online"`
	}
	out := map[string]*tierCount{}
	total, online, degraded := 0, 0, 0
	for _, d := range s.Fleet.List() {
		tc := out[d.Tier]
		if tc == nil {
			tc = &tierCount{}
			out[d.Tier] = tc
		}
		tc.Total++
		total++
		if d.Online {
			tc.Online++
			online++
		}
		if d.Safety != "OK" && d.Safety != "" {
			degraded++
		}
	}
	writeJSON(w, map[string]any{"total": total, "online": online, "safety_not_ok": degraded, "tiers": out})
}

func (s *Server) devices(w http.ResponseWriter, r *http.Request) { writeJSON(w, s.Fleet.List()) }

func (s *Server) device(w http.ResponseWriter, r *http.Request) {
	d, logs, events, ok := s.Fleet.Get(r.PathValue("id"))
	if !ok {
		http.NotFound(w, r)
		return
	}
	if d.Tier != "ALPHA" { // beta/stable detail never exposes the full log feed
		logs = nil
	}
	writeJSON(w, map[string]any{"device": d, "logs": logs, "events": events})
}

func (s *Server) command(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	var req struct {
		Name string            `json:"name"`
		Args map[string]string `json:"args"`
	}
	if json.NewDecoder(r.Body).Decode(&req) != nil || req.Name == "" {
		http.Error(w, "bad request", http.StatusBadRequest)
		return
	}
	s.mu.Lock()
	c := s.conns[id]
	s.mu.Unlock()
	res := "sent"
	switch {
	case c == nil:
		res = "device offline"
	case c.tier != pb.Tier_TIER_ALPHA || !c.bench:
		res = "refused: not an alpha bench device"
	default:
		cmd := &pb.DebugCommand{CommandId: time.Now().Format("150405.000"), Name: req.Name, Args: req.Args}
		if err := s.send(c, pb.PayloadType_PAYLOAD_TYPE_DEBUG_COMMAND, cmd); err != nil {
			res = "send failed"
		}
	}
	s.mu.Lock()
	s.audit = append(s.audit, AuditLine{time.Now().UnixMilli(), "dev-admin", "command:" + req.Name, id, res})
	s.mu.Unlock()
	log.Printf("command %s -> %s: %s", req.Name, id, res)
	if res != "sent" {
		w.WriteHeader(http.StatusConflict)
	}
	writeJSON(w, map[string]string{"result": res})
}

func (s *Server) auditLog(w http.ResponseWriter, r *http.Request) {
	s.mu.Lock()
	defer s.mu.Unlock()
	writeJSON(w, s.audit)
}

// ---- OTA ----

func (s *Server) offer(c *devConn) {
	if s.OTA == nil {
		return
	}
	if m := s.OTA.Offer(c.id, c.ring, c.counter); m != nil && m.ReleaseId != c.offered {
		c.offered = m.ReleaseId
		s.send(c, pb.PayloadType_PAYLOAD_TYPE_OTA_OFFER, &pb.OtaOffer{Manifest: m})
		s.Fleet.AddEvent(c.id, fleet.Event{TsMs: time.Now().UnixMilli(), Kind: "ota_offered", Summary: "offered release " + m.ReleaseId})
	}
}

func (s *Server) releases(w http.ResponseWriter, r *http.Request) {
	if s.OTA == nil {
		writeJSON(w, []any{})
		return
	}
	writeJSON(w, s.OTA.List())
}

// registerRelease takes a manifest signed OFFLINE (cortex-sign). The gateway only
// verifies it against the public key; it cannot produce a valid one.
func (s *Server) registerRelease(w http.ResponseWriter, r *http.Request) {
	if s.OTA == nil {
		http.Error(w, "ota disabled", http.StatusServiceUnavailable)
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	var m pb.Manifest
	if err != nil || proto.Unmarshal(body, &m) != nil {
		http.Error(w, "bad manifest", http.StatusBadRequest)
		return
	}
	res := "registered"
	if err := s.OTA.Register(&m, nil, time.Now()); err != nil {
		res = "rejected: " + err.Error()
		w.WriteHeader(http.StatusUnprocessableEntity)
	}
	s.mu.Lock()
	s.audit = append(s.audit, AuditLine{time.Now().UnixMilli(), "dev-admin", "release:register", m.ReleaseId, res})
	s.mu.Unlock()
	writeJSON(w, map[string]string{"result": res})
}

func (s *Server) haltRelease(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if s.OTA != nil {
		s.OTA.Halt(id, "halted by operator")
	}
	s.mu.Lock()
	s.audit = append(s.audit, AuditLine{time.Now().UnixMilli(), "dev-admin", "release:halt", id, "halted"})
	s.mu.Unlock()
	writeJSON(w, map[string]string{"result": "halted"})
}
