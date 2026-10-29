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
	"github.com/asirive/cortex/gateway/internal/registry"
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
	Reg      *registry.Registry
	// AllowSharedDeviceToken lets devices connect with the shared dev token (simulator only).
	AllowSharedDeviceToken bool
	up                     websocket.Upgrader

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
	return &Server{Fleet: f, DevToken: token, Reg: registry.New(), conns: map[string]*devConn{},
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
	mux.HandleFunc("POST /api/registrations", s.auth(s.register))
	mux.HandleFunc("GET /api/registrations", s.auth(s.registrations))
	mux.HandleFunc("POST /api/registrations/{id}/revoke", s.auth(s.revoke))
	mux.HandleFunc("POST /v1/claim", s.claim)
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
	devID := r.Header.Get("X-Device-Id")
	var reg *registry.Registration
	if s.AllowSharedDeviceToken && subtle.ConstantTimeCompare([]byte(tok), []byte(s.DevToken)) == 1 {
		// legacy dev path: tier comes from Hello. Never enable in production.
	} else if rg, err := s.Reg.Authenticate(devID, tok); err == nil {
		reg = rg
	} else {
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
	if reg != nil { // identity comes from the registry, never from the device's own claim
		if env.Header.DeviceId != reg.ID {
			return
		}
		hello.Tier = map[string]pb.Tier{"ALPHA": pb.Tier_TIER_ALPHA, "BETA": pb.Tier_TIER_BETA, "STABLE": pb.Tier_TIER_STABLE}[reg.Tier]
		hello.Ring = map[string]pb.Ring{"ALPHA": pb.Ring_RING_ALPHA, "BETA": pb.Ring_RING_BETA, "STABLE": pb.Ring_RING_STABLE}[reg.Ring]
		hello.BenchDevice = reg.Bench
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

func (s *Server) devices(w http.ResponseWriter, r *http.Request) {
	list := s.Fleet.List()
	idx := map[string]int{}
	for i := range list {
		idx[list[i].ID] = i
	}
	for _, rg := range s.Reg.List() {
		i, seen := idx[rg.ID]
		if !seen { // registered but never connected: show it so operators can see it is waiting
			list = append(list, fleet.Device{ID: rg.ID, Tier: rg.Tier, Ring: rg.Ring, Bench: rg.Bench})
			i = len(list) - 1
		}
		list[i].RegState, list[i].Label = string(rg.State), rg.Label
		if rg.State == registry.Pending {
			list[i].ClaimExpires = rg.ExpiresAt.UnixMilli()
		}
		if rg.State == registry.Revoked {
			list[i].Online = false
		}
	}
	writeJSON(w, list)
}

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

// ---- registration ----

func (s *Server) record(actor, action, target, result string) {
	s.mu.Lock()
	s.audit = append(s.audit, AuditLine{time.Now().UnixMilli(), actor, action, target, result})
	s.mu.Unlock()
}

func (s *Server) register(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Label string `json:"label"`
		Tier  string `json:"tier"`
		Bench bool   `json:"bench"`
	}
	if json.NewDecoder(r.Body).Decode(&req) != nil || (req.Tier != "ALPHA" && req.Tier != "BETA" && req.Tier != "STABLE") {
		http.Error(w, "tier must be ALPHA, BETA or STABLE", http.StatusBadRequest)
		return
	}
	if len(req.Label) > 80 {
		http.Error(w, "label too long", http.StatusBadRequest)
		return
	}
	reg, code := s.Reg.Register(req.Label, req.Tier, req.Tier, req.Bench, time.Now())
	s.record("dev-admin", "device:register", reg.ID, "pending")
	writeJSON(w, map[string]any{"registration": reg, "claim_code": code})
}

func (s *Server) registrations(w http.ResponseWriter, r *http.Request) { writeJSON(w, s.Reg.List()) }

func (s *Server) revoke(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if err := s.Reg.Revoke(id); err != nil {
		http.NotFound(w, r)
		return
	}
	s.mu.Lock()
	c := s.conns[id]
	s.mu.Unlock()
	if c != nil {
		c.ws.Close() // drop a live connection immediately
	}
	s.Fleet.Disconnect(id, time.Now())
	s.record("dev-admin", "device:revoke", id, "revoked")
	writeJSON(w, map[string]string{"result": "revoked"})
}

// claim is called by the phone app (not an operator). Public endpoint, rate limited per source.
func (s *Server) claim(w http.ResponseWriter, r *http.Request) {
	var req struct {
		ClaimCode string `json:"claim_code"`
		PublicKey []byte `json:"device_public_key"`
		AccountID string `json:"account_id"`
	}
	if json.NewDecoder(io.LimitReader(r.Body, 1<<16)).Decode(&req) != nil || req.ClaimCode == "" {
		http.Error(w, "bad request", http.StatusBadRequest)
		return
	}
	src := r.RemoteAddr
	if i := strings.LastIndex(src, ":"); i > 0 {
		src = src[:i]
	}
	reg, tok, err := s.Reg.Claim(req.ClaimCode, req.PublicKey, req.AccountID, src, time.Now())
	if err != nil {
		code := http.StatusUnprocessableEntity
		if err == registry.ErrRateLimit {
			code = http.StatusTooManyRequests
		}
		http.Error(w, err.Error(), code)
		return
	}
	s.record("app:"+req.AccountID, "device:claim", reg.ID, "claimed")
	writeJSON(w, map[string]any{"device_id": reg.ID, "device_token": tok, "tier": reg.Tier, "ring": reg.Ring})
}
