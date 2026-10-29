// Package ota is the update control plane: manifest signing/verification and
// the staged rollout engine.
//
// Trust model: the signing key lives OFF the gateway (CI or an offline machine).
// The gateway holds only the public key, stores signed manifests, and decides
// WHO gets a release and WHEN. A compromised gateway can withhold or delay
// updates, but it cannot create new software, and the device's anti-rollback
// counter stops it replaying an old signed release.
package ota

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"fmt"
	"sort"
	"sync"
	"time"

	pb "github.com/asirive/cortex/gateway/internal/gen/cortex/v1"
	"google.golang.org/protobuf/proto"
)

var det = proto.MarshalOptions{Deterministic: true}

func signingBytes(m *pb.Manifest) ([]byte, error) {
	c := proto.Clone(m).(*pb.Manifest)
	c.ManifestSignature = nil
	return det.Marshal(c)
}

func Sign(m *pb.Manifest, priv ed25519.PrivateKey) error {
	b, err := signingBytes(m)
	if err != nil {
		return err
	}
	m.ManifestSignature = ed25519.Sign(priv, b)
	return nil
}

var (
	ErrBadSignature   = errors.New("manifest signature invalid")
	ErrRollback       = errors.New("version counter below device counter")
	ErrRingNotAllowed = errors.New("release not allowed for this ring")
	ErrTooEarly       = errors.New("release not yet valid")
	ErrDuplicate      = errors.New("release id already registered")
)

// Verify is what the DEVICE runs before downloading anything. It lives here so
// the gateway and the tests share the exact rules the device implements.
func Verify(m *pb.Manifest, pub ed25519.PublicKey, deviceRing pb.Ring, deviceCounter uint64, now time.Time) error {
	b, err := signingBytes(m)
	if err != nil || !ed25519.Verify(pub, b, m.ManifestSignature) {
		return ErrBadSignature
	}
	if m.VersionCounter < deviceCounter {
		return ErrRollback
	}
	if deviceRing > m.MaxRing { // rings are ordered ALPHA < BETA < STABLE
		return ErrRingNotAllowed
	}
	if m.NotBeforeMs > now.UnixMilli() {
		return ErrTooEarly
	}
	return nil
}

func VerifyArtifact(a *pb.Artifact, data []byte, pub ed25519.PublicKey) error {
	h := sha256.Sum256(data)
	if string(h[:]) != string(a.Sha256) || uint64(len(data)) != a.SizeBytes {
		return errors.New("artifact hash or size mismatch")
	}
	return nil
}

// ---- rollout ----

type Stage struct {
	Ring         pb.Ring
	Percent      uint32        // share of the ring's devices that get it in this stage
	Soak         time.Duration // how long to watch before advancing
	MinHealthyPc float64       // fraction of offered devices that must commit cleanly
}

// DefaultPlan: alpha team first, then a slice of beta, all beta, then stable in steps.
var DefaultPlan = []Stage{
	{pb.Ring_RING_ALPHA, 100, 30 * time.Minute, 1.0},
	{pb.Ring_RING_BETA, 20, 2 * time.Hour, 0.95},
	{pb.Ring_RING_BETA, 100, 24 * time.Hour, 0.95},
	{pb.Ring_RING_STABLE, 10, 24 * time.Hour, 0.98},
	{pb.Ring_RING_STABLE, 50, 24 * time.Hour, 0.98},
	{pb.Ring_RING_STABLE, 100, 0, 0.98},
}

type State int

const (
	Rolling State = iota
	Halted
	Complete
)

type Outcome int

const (
	Pending Outcome = iota
	Committed
	RolledBack
	Rejected
)

type Release struct {
	Manifest *pb.Manifest
	Plan     []Stage
	State    State
	Stage    int
	Started  time.Time // start of the current stage
	HaltWhy  string
	outcomes map[string]Outcome
	offered  map[string]bool
	excluded map[string]bool // rolled back or rejected: never re-offered
	Note     string
}

// StallLimit is how long past the soak a stage may wait for offered devices to
// report before the rollout halts instead of waiting forever.
const StallLimit = 2 * time.Hour

type Engine struct {
	mu       sync.Mutex
	releases map[string]*Release
	pub      ed25519.PublicKey
	// OnEvent is called (outside the lock) on automatic halt/advance/complete so the caller can audit them.
	OnEvent func(releaseID, what string)
}

func NewEngine(pub ed25519.PublicKey) *Engine {
	return &Engine{releases: map[string]*Release{}, pub: pub}
}

func (e *Engine) Register(m *pb.Manifest, plan []Stage, now time.Time) error {
	if err := Verify(m, e.pub, pb.Ring_RING_ALPHA, 0, now.Add(24*time.Hour*365)); err != nil {
		return err
	}
	if plan == nil {
		plan = DefaultPlan
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	if _, dup := e.releases[m.ReleaseId]; dup {
		return ErrDuplicate // never reset a release (and its halt) by re-posting it
	}
	e.releases[m.ReleaseId] = &Release{Manifest: m, Plan: plan, Started: now, outcomes: map[string]Outcome{}, offered: map[string]bool{}, excluded: map[string]bool{}}
	return nil
}

func inBucket(deviceID, releaseID string, percent uint32) bool {
	h := sha256.Sum256([]byte(deviceID + "|" + releaseID))
	return uint32(binary.BigEndian.Uint32(h[:4])%100) < percent
}

// Offer returns the manifest this device should be offered now, or nil.
func (e *Engine) Offer(deviceID string, ring pb.Ring, runningCounter uint64) *pb.Manifest {
	e.mu.Lock()
	defer e.mu.Unlock()
	var best *Release
	for _, r := range e.releases {
		if r.State != Rolling || r.Manifest.VersionCounter <= runningCounter || ring > r.Manifest.MaxRing || r.excluded[deviceID] || r.Manifest.NotBeforeMs > time.Now().UnixMilli() {
			continue
		}
		if !r.eligible(deviceID, ring) {
			continue
		}
		if best == nil || r.Manifest.VersionCounter > best.Manifest.VersionCounter {
			best = r
		}
	}
	if best == nil {
		return nil
	}
	best.offered[deviceID] = true
	return best.Manifest
}

// eligible: a device is in scope if its ring is already past, or is the current
// stage's ring and falls inside the stage's percentage.
func (r *Release) eligible(deviceID string, ring pb.Ring) bool {
	for i := 0; i <= r.Stage && i < len(r.Plan); i++ {
		s := r.Plan[i]
		if s.Ring == ring && inBucket(deviceID, r.Manifest.ReleaseId, s.Percent) {
			return true
		}
	}
	return false
}

func (e *Engine) Report(releaseID, deviceID string, o Outcome) {
	e.mu.Lock()
	defer e.mu.Unlock()
	if r := e.releases[releaseID]; r != nil {
		r.outcomes[deviceID] = o
		if o == RolledBack || o == Rejected {
			r.excluded[deviceID] = true
		}
	}
}

// Halt stops a rolling release. False if unknown or not rolling.
func (e *Engine) Halt(releaseID, why string) bool {
	e.mu.Lock()
	defer e.mu.Unlock()
	if r := e.releases[releaseID]; r != nil && r.State == Rolling {
		r.State, r.HaltWhy = Halted, why
		return true
	}
	return false
}

// Resume restarts a halted release at its current stage. Explicit operator action only.
func (e *Engine) Resume(releaseID string, now time.Time) bool {
	e.mu.Lock()
	defer e.mu.Unlock()
	if r := e.releases[releaseID]; r != nil && r.State == Halted {
		r.State, r.HaltWhy, r.Note, r.Started = Rolling, "", "", now
		return true
	}
	return false
}

// Evaluate advances or halts every rolling release. Call it on a timer.
//   - failures that drop the offered devices below the stage's healthy fraction halt the release
//   - a stage never advances before its soak ends, nor while no device has been tested in it
//   - a stage whose offered devices never report halts after StallLimit instead of waiting forever
func (e *Engine) Evaluate(now time.Time) {
	var events [][2]string
	e.mu.Lock()
	for _, r := range e.releases {
		if r.State != Rolling {
			continue
		}
		var ok, bad int
		for d := range r.offered {
			switch r.outcomes[d] {
			case Committed:
				ok++
			case RolledBack, Rejected:
				bad++
			}
		}
		total := len(r.offered)
		st := r.Plan[r.Stage]
		id := r.Manifest.ReleaseId
		if total > 0 && bad > 0 && float64(total-bad)/float64(total) < st.MinHealthyPc {
			r.State, r.HaltWhy = Halted, fmt.Sprintf("stage %d: %d of %d devices failed", r.Stage, bad, total)
			events = append(events, [2]string{id, "auto-halt: " + r.HaltWhy})
			continue
		}
		if now.Sub(r.Started) < st.Soak {
			continue
		}
		if total == 0 {
			r.Note = "waiting: no device has been offered this release in the current stage"
			continue
		}
		if float64(ok)/float64(total) < st.MinHealthyPc {
			if now.Sub(r.Started) > st.Soak+StallLimit {
				r.State, r.HaltWhy = Halted, fmt.Sprintf("stage %d stalled: %d of %d devices committed", r.Stage, ok, total)
				events = append(events, [2]string{id, "auto-halt: " + r.HaltWhy})
			} else {
				r.Note = fmt.Sprintf("waiting: %d of %d offered devices committed", ok, total)
			}
			continue
		}
		r.Note = ""
		if r.Stage+1 >= len(r.Plan) {
			r.State = Complete
			events = append(events, [2]string{id, "complete"})
			continue
		}
		r.Stage++
		r.Started = now
		events = append(events, [2]string{id, fmt.Sprintf("advance to stage %d (%s %d%%)", r.Stage, r.Plan[r.Stage].Ring, r.Plan[r.Stage].Percent)})
	}
	cb := e.OnEvent
	e.mu.Unlock()
	if cb != nil {
		for _, ev := range events {
			cb(ev[0], ev[1])
		}
	}
}

type Status struct {
	ReleaseID string `json:"release_id"`
	State     string `json:"state"`
	Stage     int    `json:"stage"`
	Stages    int    `json:"stages"`
	Ring      string `json:"ring"`
	Percent   uint32 `json:"percent"`
	Offered   int    `json:"offered"`
	Committed int    `json:"committed"`
	Failed    int    `json:"failed"`
	HaltWhy   string `json:"halt_why,omitempty"`
	Note      string `json:"note,omitempty"`
	Counter   uint64 `json:"counter"`
	MaxRing   string `json:"max_ring"`
	Version   string `json:"version,omitempty"`
	StartedMs int64  `json:"stage_started_ms"`
}

func (e *Engine) List() []Status {
	e.mu.Lock()
	defer e.mu.Unlock()
	out := []Status{}
	for _, r := range e.releases {
		s := Status{ReleaseID: r.Manifest.ReleaseId, Stage: r.Stage, Stages: len(r.Plan), HaltWhy: r.HaltWhy, Offered: len(r.offered), Note: r.Note, Counter: r.Manifest.VersionCounter, MaxRing: r.Manifest.MaxRing.String(), StartedMs: r.Started.UnixMilli()}
		if len(r.Manifest.Artifacts) > 0 {
			s.Version = r.Manifest.Artifacts[0].Version
		}
		s.State = [...]string{"ROLLING", "HALTED", "COMPLETE"}[r.State]
		cur := r.Plan[min(r.Stage, len(r.Plan)-1)]
		s.Ring, s.Percent = cur.Ring.String(), cur.Percent
		for _, o := range r.outcomes {
			if o == Committed {
				s.Committed++
			} else if o == RolledBack || o == Rejected {
				s.Failed++
			}
		}
		out = append(out, s)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Counter > out[j].Counter })
	return out
}

func (e *Engine) Counter(releaseID string) uint64 {
	e.mu.Lock()
	defer e.mu.Unlock()
	if r := e.releases[releaseID]; r != nil {
		return r.Manifest.VersionCounter
	}
	return 0
}
