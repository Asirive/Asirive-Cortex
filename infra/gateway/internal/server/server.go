// Package server is the fleet gateway: device WebSocket endpoint, dashboard API,
// tier enforcement. Auth here is a shared operator token plus per-device tokens;
// mTLS + the E2E sealed envelope are the production path (see infra/AGENTS.md).
package server

import (
	"bytes"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"log"
	"net"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"time"
	"unicode/utf8"

	"github.com/asirive/cortex/gateway/internal/fleet"
	pb "github.com/asirive/cortex/gateway/internal/gen/cortex/v1"
	"github.com/asirive/cortex/gateway/internal/ota"
	"github.com/asirive/cortex/gateway/internal/registry"
	"github.com/asirive/cortex/gateway/web"
	"github.com/gorilla/websocket"
	qrcode "github.com/skip2/go-qrcode"
	"google.golang.org/protobuf/proto"
)

const (
	schemaVersion  = 1
	maxClockSkewMs = 5 * 60 * 1000
	minHB, maxHB   = 2, 60 // heartbeat interval is clamped; a device cannot talk itself out of offline detection
	defaultHB      = 5
)

// allowedCommands is the whole alpha debug vocabulary. Anything else is refused.
var allowedCommands = map[string]bool{"dump_state": true, "restart_service": true, "set_log_level": true, "reboot": true}

type Server struct {
	Fleet    *fleet.Store
	DevToken string // operator token (and, with AllowSharedDeviceToken, the simulator's device token)
	OTA      *ota.Engine
	Reg      *registry.Registry
	// AllowSharedDeviceToken lets devices connect with the shared dev token (simulator only).
	AllowSharedDeviceToken bool
	up                     websocket.Upgrader

	mu     sync.Mutex
	conns  map[string]*devConn
	audit  []AuditLine
	authFl map[string][]time.Time
	cmdSeq atomic.Uint64
}

type AuditLine struct {
	TsMs   int64  `json:"ts_ms"`
	Actor  string `json:"actor"`
	Action string `json:"action"`
	Target string `json:"target"`
	Result string `json:"result"`
	Detail string `json:"detail,omitempty"`
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
	s := &Server{Fleet: f, DevToken: token, Reg: registry.New(), conns: map[string]*devConn{}, authFl: map[string][]time.Time{}}
	// devices are not browsers: refuse any browser-originated WebSocket (cross-site hijack)
	s.up = websocket.Upgrader{CheckOrigin: func(r *http.Request) bool { return r.Header.Get("Origin") == "" }}
	return s
}

// WireOTA connects the rollout engine so automatic halts and advances reach the audit log.
func (s *Server) WireOTA(e *ota.Engine) {
	s.OTA = e
	e.OnEvent = func(id, what string) {
		s.record("system", "release:"+strings.SplitN(what, ":", 2)[0], id, "auto", what)
	}
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/ws/device", s.deviceWS)
	mux.HandleFunc("GET /api/summary", s.auth(s.summary))
	mux.HandleFunc("GET /api/devices", s.auth(s.devices))
	mux.HandleFunc("GET /api/devices/{id}", s.auth(s.device))
	mux.HandleFunc("POST /api/devices/{id}/command", s.auth(s.command))
	mux.HandleFunc("GET /api/audit", s.auth(s.auditLog))
	mux.HandleFunc("GET /api/feedback", s.auth(s.feedback))
	mux.HandleFunc("POST /api/registrations", s.auth(s.register))
	mux.HandleFunc("GET /api/registrations", s.auth(s.registrations))
	mux.HandleFunc("POST /api/registrations/{id}/revoke", s.auth(s.revoke))
	mux.HandleFunc("POST /v1/claim", s.claim)
	mux.HandleFunc("GET /api/releases", s.auth(s.releases))
	mux.HandleFunc("POST /api/releases", s.auth(s.registerRelease))
	mux.HandleFunc("POST /api/releases/{id}/halt", s.auth(s.haltRelease))
	mux.HandleFunc("POST /api/releases/{id}/resume", s.auth(s.resumeRelease))
	sub, _ := fs.Sub(web.FS, ".")
	mux.Handle("/", http.FileServer(http.FS(sub)))
	return secure(mux)
}

// secure adds response headers. The console is a single page with inline script and Google Fonts.
func secure(h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hd := w.Header()
		hd.Set("X-Content-Type-Options", "nosniff")
		hd.Set("X-Frame-Options", "DENY")
		hd.Set("Referrer-Policy", "no-referrer")
		hd.Set("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
		if strings.HasPrefix(r.URL.Path, "/api/") || strings.HasPrefix(r.URL.Path, "/v1/") {
			hd.Set("Cache-Control", "no-store")
		}
		h.ServeHTTP(w, r)
	})
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(v)
}

// writeErr sends a JSON error the console and the app can show verbatim.
func writeErr(w http.ResponseWriter, code int, errCode, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(map[string]string{"error": msg, "error_code": errCode})
}

func clientIP(r *http.Request) string {
	if h, _, err := net.SplitHostPort(r.RemoteAddr); err == nil {
		return h
	}
	return r.RemoteAddr
}

func (s *Server) tooManyFails(ip string, now time.Time) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	f := s.authFl[ip][:0:0]
	for _, t := range s.authFl[ip] {
		if now.Sub(t) < time.Minute {
			f = append(f, t)
		}
	}
	s.authFl[ip] = f
	return len(f) >= 10
}

func (s *Server) auth(h http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		ip, now := clientIP(r), time.Now()
		if s.tooManyFails(ip, now) {
			writeErr(w, http.StatusTooManyRequests, "rate_limited", "Too many wrong tokens. Wait a minute and try again.")
			return
		}
		tok := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
		if subtle.ConstantTimeCompare([]byte(tok), []byte(s.DevToken)) != 1 {
			s.mu.Lock()
			s.authFl[ip] = append(s.authFl[ip], now)
			s.mu.Unlock()
			writeErr(w, http.StatusUnauthorized, "unauthorized", "Token rejected")
			return
		}
		h(w, r)
	}
}

func clampHB(v uint32) uint32 {
	if v == 0 {
		return defaultHB
	}
	if v < minHB {
		return minHB
	}
	if v > maxHB {
		return maxHB
	}
	return v
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
	ws.SetReadLimit(1 << 20)

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
	iv := clampHB(hello.HeartbeatIntervalS)
	hello.HeartbeatIntervalS = iv
	now := time.Now()

	s.mu.Lock()
	old := s.conns[c.id]
	s.conns[c.id] = c
	s.mu.Unlock()
	if old != nil {
		old.ws.Close() // one live connection per device; the new one wins
	}
	s.Fleet.Connect(c.id, &hello, now)
	defer func() {
		s.mu.Lock()
		current := s.conns[c.id] == c
		if current {
			delete(s.conns, c.id)
		}
		s.mu.Unlock()
		if current { // a replaced connection must not mark the live one offline
			s.Fleet.Disconnect(c.id, time.Now())
		}
	}()
	s.send(c, pb.PayloadType_PAYLOAD_TYPE_HELLO_ACK, &pb.HelloAck{
		Accepted: true, HeartbeatIntervalS: iv, LastSeenSeq: c.lastSeq, ServerTsMs: now.UnixMilli()})
	s.offer(c)
	for {
		ws.SetReadDeadline(time.Now().Add(time.Duration(iv) * 4 * time.Second))
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

func trimEnum(s, prefix string) string { return strings.TrimPrefix(s, prefix) }

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
			if len(entries) > 200 {
				entries = entries[:200]
			}
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
			attrs := m.Attrs
			if c.tier != pb.Tier_TIER_ALPHA { // the full event feed (with attributes) is alpha-only
				attrs = nil
			}
			s.Fleet.AddEvent(c.id, fleet.Event{TsMs: m.TsMs, Kind: m.Kind, Summary: clip(m.Summary, 200), Attrs: attrs})
		}
	case pb.PayloadType_PAYLOAD_TYPE_FEEDBACK:
		var m pb.Feedback
		if proto.Unmarshal(env.Payload, &m) == nil {
			f := fleet.Feedback{TsMs: now.UnixMilli(), DeviceID: c.id, Tier: trimEnum(c.tier.String(), "TIER_"), Text: clip(m.Text, 2000), App: clip(m.AppVersion, 40)}
			for i, e := range m.LogExcerpt {
				if i >= 50 {
					break
				}
				f.Log = append(f.Log, fleet.LogLine{TsMs: e.TsMs, Level: trimEnum(e.Level.String(), "LOG_LEVEL_"), Service: clip(e.Service, 40), Message: clip(e.Message, 300)})
			}
			s.Fleet.AddFeedback(f)
			s.Fleet.AddEvent(c.id, fleet.Event{TsMs: now.UnixMilli(), Kind: "feedback", Summary: "feedback received"})
		}
	case pb.PayloadType_PAYLOAD_TYPE_OTA_PROGRESS:
		var m pb.OtaProgress
		if proto.Unmarshal(env.Payload, &m) == nil {
			s.Fleet.SetOta(c.id, &fleet.Ota{ReleaseID: m.ReleaseId, Stage: trimEnum(m.Stage.String(), "OTA_STAGE_"), Percent: m.Percent})
		}
	case pb.PayloadType_PAYLOAD_TYPE_OTA_RESULT:
		var m pb.OtaResult
		if proto.Unmarshal(env.Payload, &m) == nil {
			s.Fleet.SetOta(c.id, &fleet.Ota{ReleaseID: m.ReleaseId, Stage: "DONE", Percent: 100, Outcome: trimEnum(m.Outcome.String(), "OTA_OUTCOME_")})
			s.Fleet.SetVersion(c.id, m.RunningVersion, m.Outcome == pb.OtaOutcome_OTA_OUTCOME_COMMITTED)
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
			s.Fleet.AddEvent(c.id, fleet.Event{TsMs: now.UnixMilli(), Kind: "debug_result", Summary: clip(m.Output, 500),
				Attrs: map[string]string{"command_id": m.CommandId}})
		}
	case pb.PayloadType_PAYLOAD_TYPE_CAMERA_FRAME, pb.PayloadType_PAYLOAD_TYPE_DATASET_CHUNK:
		// Relay / dataset pipeline plug in here. Camera frames are never persisted.
	default:
		// Unknown or unhandled types are surfaced, not silently dropped.
		s.Fleet.AddEvent(c.id, fleet.Event{TsMs: now.UnixMilli(), Kind: "unhandled", Summary: "message type not handled by gateway: " + env.Type.String()})
	}
}

func clip(s string, n int) string {
	if len(s) <= n {
		return s
	}
	for n > 0 && !utf8.RuneStart(s[n]) {
		n--
	}
	return s[:n]
}

func (s *Server) send(c *devConn, t pb.PayloadType, m proto.Message) error {
	pl, _ := proto.Marshal(m)
	c.wmu.Lock()
	defer c.wmu.Unlock()
	c.seq++
	env := &pb.Envelope{Header: &pb.Header{SchemaVersion: schemaVersion, DeviceId: c.id, Seq: c.seq,
		TsMs: time.Now().UnixMilli()}, Type: t, Payload: pl}
	b, _ := proto.Marshal(env)
	return c.ws.WriteMessage(websocket.BinaryMessage, b)
}

// ---- dashboard API ----

// attention explains why a device needs the operator, or "" if it does not.
func attention(d fleet.Device) string {
	if d.RegState == string(registry.Pending) || d.RegState == string(registry.Revoked) {
		return ""
	}
	if d.Ota != nil && (d.Ota.Outcome == "ROLLED_BACK" || d.Ota.Outcome == "REJECTED") {
		return "Update " + strings.ToLower(strings.ReplaceAll(d.Ota.Outcome, "_", " "))
	}
	if d.Safety == "FAULT" || d.Safety == "DEGRADED" { // last known state counts even after the device drops
		return "Safety " + strings.ToLower(d.Safety) + " (last known)"
	}
	if !d.Online && d.LastSeenMs > 0 {
		return "Offline"
	}
	if d.Online && d.Battery < 15 && !d.Charging {
		return "Low battery"
	}
	return ""
}

func (s *Server) merged() []fleet.Device {
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
	for i := range list {
		list[i].Attention = attention(list[i])
	}
	return list
}

func (s *Server) summary(w http.ResponseWriter, r *http.Request) {
	type tc struct {
		Total  int `json:"total"`
		Online int `json:"online"`
	}
	tiers := map[string]*tc{}
	total, online, att := 0, 0, 0
	for _, d := range s.merged() {
		if d.RegState == string(registry.Pending) || d.RegState == string(registry.Revoked) {
			continue // not part of the live fleet
		}
		t := tiers[d.Tier]
		if t == nil {
			t = &tc{}
			tiers[d.Tier] = t
		}
		t.Total++
		total++
		if d.Online {
			t.Online++
			online++
		}
		if d.Attention != "" {
			att++
		}
	}
	writeJSON(w, map[string]any{"total": total, "online": online, "needs_attention": att, "tiers": tiers})
}

func (s *Server) devices(w http.ResponseWriter, r *http.Request) { writeJSON(w, s.merged()) }

func (s *Server) device(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	var dev fleet.Device
	var logs []fleet.LogLine
	var events []fleet.Event
	found := false
	for _, d := range s.merged() {
		if d.ID == id {
			dev, found = d, true
		}
	}
	if !found {
		writeErr(w, http.StatusNotFound, "not_found", "No such device")
		return
	}
	if _, l, e, ok := s.Fleet.Get(id); ok {
		logs, events = l, e // beta/stable logs are already trimmed to WARN+ on ingest
	}
	writeJSON(w, map[string]any{"device": dev, "logs": logs, "events": events})
}

func (s *Server) command(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	var req struct {
		Name string            `json:"name"`
		Args map[string]string `json:"args"`
	}
	if json.NewDecoder(io.LimitReader(r.Body, 1<<14)).Decode(&req) != nil || !allowedCommands[req.Name] {
		writeErr(w, http.StatusBadRequest, "bad_command", "Unknown command. Allowed: dump_state, restart_service, set_log_level, reboot.")
		return
	}
	if len(req.Args) > 8 {
		writeErr(w, http.StatusBadRequest, "bad_args", "Too many arguments")
		return
	}
	for k, v := range req.Args {
		if len(k) > 32 || len(v) > 64 {
			writeErr(w, http.StatusBadRequest, "bad_args", "Argument too long")
			return
		}
	}
	argTxt, _ := json.Marshal(req.Args)
	s.mu.Lock()
	c := s.conns[id]
	s.mu.Unlock()
	switch {
	case c == nil:
		s.record("dev-admin", "command:"+req.Name, id, "refused", "device offline "+string(argTxt))
		writeErr(w, http.StatusConflict, "device_offline", id+" is offline, so the command was not sent.")
	case c.tier != pb.Tier_TIER_ALPHA || !c.bench:
		s.record("dev-admin", "command:"+req.Name, id, "refused", "not an alpha bench device "+string(argTxt))
		writeErr(w, http.StatusConflict, "not_bench", id+" is not an alpha bench device, so debug commands are refused.")
	default:
		cid := fmt.Sprintf("c%d-%d", time.Now().Unix(), s.cmdSeq.Add(1))
		if err := s.send(c, pb.PayloadType_PAYLOAD_TYPE_DEBUG_COMMAND, &pb.DebugCommand{CommandId: cid, Name: req.Name, Args: req.Args}); err != nil {
			s.record("dev-admin", "command:"+req.Name, id, "send failed", string(argTxt))
			writeErr(w, http.StatusBadGateway, "send_failed", "Could not reach the device.")
			return
		}
		s.record("dev-admin", "command:"+req.Name, id, "sent", cid+" "+string(argTxt))
		writeJSON(w, map[string]string{"result": "sent", "command_id": cid})
	}
}

func (s *Server) record(actor, action, target, result, detail string) {
	s.mu.Lock()
	s.audit = append(s.audit, AuditLine{time.Now().UnixMilli(), actor, action, target, result, detail})
	if len(s.audit) > 5000 {
		s.audit = s.audit[len(s.audit)-5000:]
	}
	s.mu.Unlock()
	log.Printf("audit %s %s %s: %s", actor, action, target, result)
}

func (s *Server) auditLog(w http.ResponseWriter, r *http.Request) {
	s.mu.Lock()
	defer s.mu.Unlock()
	writeJSON(w, s.audit)
}

func (s *Server) feedback(w http.ResponseWriter, r *http.Request) { writeJSON(w, s.Fleet.Feedback()) }

// ---- registration ----

func (s *Server) register(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Label string `json:"label"`
		Tier  string `json:"tier"`
		Bench bool   `json:"bench"`
	}
	if json.NewDecoder(io.LimitReader(r.Body, 1<<14)).Decode(&req) != nil {
		writeErr(w, http.StatusBadRequest, "bad_request", "Could not read the request")
		return
	}
	req.Label = strings.TrimSpace(req.Label)
	switch {
	case req.Tier != "ALPHA" && req.Tier != "BETA" && req.Tier != "STABLE":
		writeErr(w, http.StatusBadRequest, "bad_tier", "Tier must be ALPHA, BETA or STABLE")
	case req.Label == "":
		writeErr(w, http.StatusBadRequest, "label_required", "Give the device a label so you can find it later")
	case utf8.RuneCountInString(req.Label) > 80:
		writeErr(w, http.StatusBadRequest, "label_too_long", "Label is longer than 80 characters")
	case req.Bench && req.Tier != "ALPHA":
		writeErr(w, http.StatusBadRequest, "bench_alpha_only", "Only alpha devices can be bench devices")
	default:
		taken := func(id string) bool { _, _, _, ok := s.Fleet.Get(id); return ok }
		reg, code, err := s.Reg.Register(req.Label, req.Tier, req.Tier, req.Bench, time.Now(), taken)
		if err != nil {
			writeErr(w, http.StatusInternalServerError, "id_space", "Could not allocate a device id")
			return
		}
		s.record("dev-admin", "device:register", reg.ID, "pending", req.Label)
		uri := "asirive://claim?code=" + strings.ReplaceAll(code, "-", "")
		png, _ := qrcode.Encode(uri, qrcode.Medium, 256)
		writeJSON(w, map[string]any{"registration": reg, "claim_code": code, "claim_uri": uri, "claim_qr_png": base64.StdEncoding.EncodeToString(png)})
	}
}

func (s *Server) registrations(w http.ResponseWriter, r *http.Request) { writeJSON(w, s.Reg.List()) }

func (s *Server) revoke(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	switch err := s.Reg.Revoke(id); err {
	case nil:
	case registry.ErrAlreadyRevoked:
		writeErr(w, http.StatusConflict, "already_revoked", id+" is already revoked")
		return
	default:
		writeErr(w, http.StatusNotFound, "not_registered", id+" is not a registered device (simulated devices cannot be revoked)")
		return
	}
	s.mu.Lock()
	c := s.conns[id]
	s.mu.Unlock()
	if c != nil {
		c.ws.Close() // drop a live connection immediately
	}
	s.Fleet.AddEvent(id, fleet.Event{TsMs: time.Now().UnixMilli(), Kind: "revoked", Summary: "device revoked by operator"})
	s.record("dev-admin", "device:revoke", id, "revoked", "")
	writeJSON(w, map[string]string{"result": "revoked"})
}

// claim is called by the phone app (not an operator). Public endpoint, rate limited per source.
// TODO: require an authenticated app account; account_id is self-asserted until accounts exist.
func (s *Server) claim(w http.ResponseWriter, r *http.Request) {
	var req struct {
		ClaimCode string `json:"claim_code"`
		PublicKey []byte `json:"device_public_key"`
		AccountID string `json:"account_id"`
	}
	if json.NewDecoder(io.LimitReader(r.Body, 1<<16)).Decode(&req) != nil || strings.TrimSpace(req.ClaimCode) == "" || strings.TrimSpace(req.AccountID) == "" {
		writeErr(w, http.StatusBadRequest, "bad_request", "claim_code and account_id are required")
		return
	}
	reg, tok, err := s.Reg.Claim(req.ClaimCode, req.PublicKey, req.AccountID, clientIP(r), time.Now())
	if err != nil {
		if err == registry.ErrRateLimit {
			writeErr(w, http.StatusTooManyRequests, "rate_limited", "Too many attempts. Wait a minute and try again.")
		} else {
			writeErr(w, http.StatusUnprocessableEntity, "invalid_or_expired", "This code is wrong, already used, or expired. Ask for a new one.")
		}
		return
	}
	s.record("app:"+req.AccountID, "device:claim", reg.ID, "claimed", "")
	writeJSON(w, map[string]any{"device_id": reg.ID, "device_token": tok, "tier": reg.Tier, "ring": reg.Ring})
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
		writeErr(w, http.StatusServiceUnavailable, "ota_disabled", "OTA is disabled: start the gateway with CORTEX_OTA_PUBKEY")
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	var m pb.Manifest
	if err != nil || len(bytes.TrimSpace(body)) == 0 || proto.Unmarshal(body, &m) != nil {
		writeErr(w, http.StatusBadRequest, "bad_manifest", "That file is not a manifest")
		return
	}
	switch err := s.OTA.Register(&m, nil, time.Now()); err {
	case nil:
		s.record("dev-admin", "release:register", m.ReleaseId, "registered", fmt.Sprintf("counter %d, max ring %s", m.VersionCounter, m.MaxRing))
		writeJSON(w, map[string]string{"result": "registered"})
	case ota.ErrDuplicate:
		s.record("dev-admin", "release:register", m.ReleaseId, "refused", "duplicate")
		writeErr(w, http.StatusConflict, "duplicate_release", "Release "+m.ReleaseId+" is already registered. Re-posting does not reset it; use Resume to restart a halted release.")
	default:
		s.record("dev-admin", "release:register", m.ReleaseId, "rejected", err.Error())
		writeErr(w, http.StatusUnprocessableEntity, "invalid_manifest", "Rejected: "+err.Error())
	}
}

func (s *Server) haltRelease(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if s.OTA == nil || !s.OTA.Halt(id, "halted by operator") {
		writeErr(w, http.StatusNotFound, "not_rolling", id+" is unknown or not rolling")
		return
	}
	s.record("dev-admin", "release:halt", id, "halted", "")
	writeJSON(w, map[string]string{"result": "halted"})
}

func (s *Server) resumeRelease(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if s.OTA == nil || !s.OTA.Resume(id, time.Now()) {
		writeErr(w, http.StatusNotFound, "not_halted", id+" is unknown or not halted")
		return
	}
	s.record("dev-admin", "release:resume", id, "resumed", "")
	writeJSON(w, map[string]string{"result": "resumed"})
}
