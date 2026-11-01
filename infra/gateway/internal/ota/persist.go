package ota

import (
	"encoding/json"
	"time"

	pb "github.com/asirive/cortex/gateway/internal/gen/cortex/v1"
	"google.golang.org/protobuf/encoding/protojson"
)

type stageRec struct {
	Ring         int32
	Percent      uint32
	SoakNs       int64
	MinHealthyPc float64
}

type releaseRec struct {
	Manifest json.RawMessage
	Plan     []stageRec
	State    State
	Stage    int
	Started  time.Time
	HaltWhy  string
	Note     string
	Outcomes map[string]Outcome
	Offered  map[string]bool
	Excluded map[string]bool
}

// Snapshot serialises every release and its per-device progress.
func (e *Engine) Snapshot() ([]byte, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	var out []releaseRec
	for _, r := range e.releases {
		m, err := protojson.Marshal(r.Manifest)
		if err != nil {
			return nil, err
		}
		rec := releaseRec{Manifest: m, State: r.State, Stage: r.Stage, Started: r.Started, HaltWhy: r.HaltWhy, Note: r.Note,
			Outcomes: r.outcomes, Offered: r.offered, Excluded: r.excluded}
		for _, s := range r.Plan {
			rec.Plan = append(rec.Plan, stageRec{int32(s.Ring), s.Percent, int64(s.Soak), s.MinHealthyPc})
		}
		out = append(out, rec)
	}
	return json.Marshal(out)
}

// Restore loads releases from a Snapshot. Manifests are re-verified against the
// public key, so a tampered state file cannot introduce an unsigned release.
func (e *Engine) Restore(data []byte) error {
	var recs []releaseRec
	if err := json.Unmarshal(data, &recs); err != nil {
		return err
	}
	rels := map[string]*Release{}
	for _, rec := range recs {
		m := &pb.Manifest{}
		if err := protojson.Unmarshal(rec.Manifest, m); err != nil {
			return err
		}
		if err := Verify(m, e.pub, pb.Ring_RING_ALPHA, 0, time.Now().Add(24*time.Hour*365)); err != nil {
			return err
		}
		r := &Release{Manifest: m, State: rec.State, Stage: rec.Stage, Started: rec.Started, HaltWhy: rec.HaltWhy, Note: rec.Note,
			outcomes: rec.Outcomes, offered: rec.Offered, excluded: rec.Excluded}
		if r.outcomes == nil {
			r.outcomes = map[string]Outcome{}
		}
		if r.offered == nil {
			r.offered = map[string]bool{}
		}
		if r.excluded == nil {
			r.excluded = map[string]bool{}
		}
		for _, s := range rec.Plan {
			r.Plan = append(r.Plan, Stage{pb.Ring(s.Ring), s.Percent, time.Duration(s.SoakNs), s.MinHealthyPc})
		}
		rels[m.ReleaseId] = r
	}
	e.mu.Lock()
	e.releases = rels
	e.mu.Unlock()
	return nil
}
