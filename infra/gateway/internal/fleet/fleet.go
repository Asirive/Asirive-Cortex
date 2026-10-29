// Package fleet holds in-memory fleet state. Postgres persistence replaces the
// maps behind the same API later (see infra/supabase/migrations/002_fleet.sql).
package fleet

import (
	"sort"
	"sync"
	"time"

	pb "github.com/asirive/cortex/gateway/internal/gen/cortex/v1"
)

const logCap = 500

type LogLine struct {
	TsMs    int64  `json:"ts_ms"`
	Level   string `json:"level"`
	Service string `json:"service"`
	Message string `json:"message"`
}

type Event struct {
	TsMs    int64             `json:"ts_ms"`
	Kind    string            `json:"kind"`
	Summary string            `json:"summary"`
	Attrs   map[string]string `json:"attrs,omitempty"`
}

type Device struct {
	ID           string  `json:"id"`
	Tier         string  `json:"tier"`
	Ring         string  `json:"ring"`
	Bench        bool    `json:"bench"`
	Hardware     string  `json:"hardware"`
	Firmware     string  `json:"firmware"`
	MCU          string  `json:"mcu"`
	Model        string  `json:"model"`
	Online       bool    `json:"online"`
	LastSeenMs   int64   `json:"last_seen_ms"`
	ConnectedMs  int64   `json:"connected_ms"`
	Battery      uint32  `json:"battery_pct"`
	Charging     bool    `json:"charging"`
	Safety       string  `json:"safety"`
	Brain        string  `json:"brain"`
	Link         string  `json:"link"`
	RTTMs        int32   `json:"link_rtt_ms"`
	UptimeS      uint32  `json:"uptime_s"`
	TempC        float32 `json:"soc_temp_c"`
	PowerW       float32 `json:"power_w"`
	MemMB        uint32  `json:"mem_used_mb"`
	Restarts     uint32  `json:"services_restarted"`
	SafetyP99Ms  uint32  `json:"safety_latency_p99_ms"`
	Ota          *Ota    `json:"ota,omitempty"`
	HBIntervalS  uint32  `json:"heartbeat_interval_s"`
	RegState     string  `json:"reg_state,omitempty"`
	Label        string  `json:"label,omitempty"`
	ClaimExpires int64   `json:"claim_expires_ms,omitempty"`

	logs   []LogLine
	events []Event
}

type Ota struct {
	ReleaseID string `json:"release_id"`
	Stage     string `json:"stage"`
	Percent   uint32 `json:"percent"`
	Outcome   string `json:"outcome,omitempty"`
}

type Store struct {
	mu      sync.RWMutex
	devices map[string]*Device
}

func New() *Store { return &Store{devices: map[string]*Device{}} }

func (s *Store) Connect(id string, h *pb.Hello, now time.Time) {
	s.mu.Lock()
	defer s.mu.Unlock()
	d, ok := s.devices[id]
	if !ok {
		d = &Device{ID: id}
		s.devices[id] = d
	}
	d.Tier = trim(h.Tier.String(), "TIER_")
	d.Ring = trim(h.Ring.String(), "RING_")
	d.Bench = h.BenchDevice
	d.Hardware, d.Firmware, d.MCU, d.Model = h.Hardware, h.FirmwareVersion, h.McuVersion, h.ModelVersion
	d.HBIntervalS = h.HeartbeatIntervalS
	d.Online = true
	d.ConnectedMs = now.UnixMilli()
	d.LastSeenMs = now.UnixMilli()
	s.addEvent(d, Event{TsMs: now.UnixMilli(), Kind: "connected", Summary: "device connected"})
}

func (s *Store) Disconnect(id string, now time.Time) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if d, ok := s.devices[id]; ok && d.Online {
		d.Online = false
		s.addEvent(d, Event{TsMs: now.UnixMilli(), Kind: "disconnected", Summary: "connection closed"})
	}
}

func (s *Store) Heartbeat(id string, hb *pb.Heartbeat, now time.Time) {
	s.mu.Lock()
	defer s.mu.Unlock()
	d := s.devices[id]
	if d == nil {
		return
	}
	d.Online = true
	d.LastSeenMs = now.UnixMilli()
	d.Battery, d.Charging = hb.BatteryPct, hb.Charging
	d.Safety = trim(hb.Safety.String(), "SAFETY_STATE_")
	d.Brain = trim(hb.Brain.String(), "BRAIN_MODE_")
	d.Link = trim(hb.Link.String(), "LINK_KIND_")
	d.RTTMs, d.UptimeS, d.TempC, d.PowerW = hb.LinkRttMs, hb.UptimeS, hb.SocTempC, hb.PowerW
	d.MemMB, d.Restarts, d.SafetyP99Ms = hb.MemUsedMb, hb.ServicesRestarted, hb.SafetyLatencyP99Ms
	if hb.FirmwareVersion != "" {
		d.Firmware = hb.FirmwareVersion
	}
}

func (s *Store) AddLogs(id string, entries []*pb.LogEntry) {
	s.mu.Lock()
	defer s.mu.Unlock()
	d := s.devices[id]
	if d == nil {
		return
	}
	for _, e := range entries {
		d.logs = append(d.logs, LogLine{TsMs: e.TsMs, Level: trim(e.Level.String(), "LOG_LEVEL_"), Service: e.Service, Message: e.Message})
	}
	if over := len(d.logs) - logCap; over > 0 {
		d.logs = d.logs[over:]
	}
}

func (s *Store) AddEvent(id string, e Event) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if d := s.devices[id]; d != nil {
		s.addEvent(d, e)
	}
}

func (s *Store) SetOta(id string, o *Ota) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if d := s.devices[id]; d != nil {
		d.Ota = o
	}
}

func (s *Store) addEvent(d *Device, e Event) {
	d.events = append(d.events, e)
	if over := len(d.events) - logCap; over > 0 {
		d.events = d.events[over:]
	}
}

// Sweep marks devices offline after 3 missed heartbeats.
func (s *Store) Sweep(now time.Time) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, d := range s.devices {
		iv := int64(d.HBIntervalS)
		if iv == 0 {
			iv = 5
		}
		if d.Online && now.UnixMilli()-d.LastSeenMs > 3*iv*1000 {
			d.Online = false
			s.addEvent(d, Event{TsMs: now.UnixMilli(), Kind: "heartbeat_lost", Summary: "3 heartbeats missed"})
		}
	}
}

func (s *Store) List() []Device {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]Device, 0, len(s.devices))
	for _, d := range s.devices {
		out = append(out, *d)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}

func (s *Store) Get(id string) (Device, []LogLine, []Event, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	d, ok := s.devices[id]
	if !ok {
		return Device{}, nil, nil, false
	}
	return *d, append([]LogLine(nil), d.logs...), append([]Event(nil), d.events...), true
}

func trim(s, prefix string) string {
	if len(s) > len(prefix) && s[:len(prefix)] == prefix {
		return s[len(prefix):]
	}
	return s
}
