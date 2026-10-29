package ota

import (
	"crypto/ed25519"
	"crypto/rand"
	"fmt"
	"testing"
	"time"

	pb "github.com/asirive/cortex/gateway/internal/gen/cortex/v1"
)

func mf(id string, counter uint64, max pb.Ring) *pb.Manifest {
	return &pb.Manifest{ReleaseId: id, VersionCounter: counter, MaxRing: max,
		Artifacts: []*pb.Artifact{{Version: "4.0.1", Url: "https://x/y", SizeBytes: 3}}}
}

func TestSignVerify(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	m := mf("r1", 5, pb.Ring_RING_BETA)
	if err := Sign(m, priv); err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	if err := Verify(m, pub, pb.Ring_RING_ALPHA, 4, now); err != nil {
		t.Fatalf("valid manifest rejected: %v", err)
	}
	if err := Verify(m, pub, pb.Ring_RING_ALPHA, 6, now); err != ErrRollback {
		t.Fatalf("want rollback refusal, got %v", err)
	}
	if err := Verify(m, pub, pb.Ring_RING_STABLE, 0, now); err != ErrRingNotAllowed {
		t.Fatalf("beta build must not reach stable, got %v", err)
	}
	m.Artifacts[0].Version = "evil" // tamper after signing
	if err := Verify(m, pub, pb.Ring_RING_ALPHA, 0, now); err != ErrBadSignature {
		t.Fatalf("tamper not detected: %v", err)
	}
	otherPub, _, _ := ed25519.GenerateKey(rand.Reader)
	m2 := mf("r2", 1, pb.Ring_RING_STABLE)
	Sign(m2, priv)
	if err := Verify(m2, otherPub, pb.Ring_RING_ALPHA, 0, now); err != ErrBadSignature {
		t.Fatalf("wrong key accepted: %v", err)
	}
}

func TestRolloutGatesAndHalt(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	e := NewEngine(pub)
	m := mf("r1", 2, pb.Ring_RING_STABLE)
	Sign(m, priv)
	if err := e.Register(m, nil, time.Unix(0, 0)); err != nil {
		t.Fatal(err)
	}
	// stable devices get nothing while the release is still in the alpha stage
	for i := 0; i < 50; i++ {
		if e.Offer(fmt.Sprintf("S%d", i), pb.Ring_RING_STABLE, 1) != nil {
			t.Fatal("stable device offered during alpha stage")
		}
	}
	if e.Offer("A1", pb.Ring_RING_ALPHA, 1) == nil {
		t.Fatal("alpha device not offered")
	}
	e.Report("r1", "A1", Committed)
	// before the soak ends nothing advances
	e.Evaluate(time.Unix(0, 0).Add(10 * time.Minute))
	if e.List()[0].Stage != 0 {
		t.Fatal("advanced before soak")
	}
	e.Evaluate(time.Unix(0, 0).Add(31 * time.Minute))
	if e.List()[0].Stage != 1 {
		t.Fatalf("did not advance after clean soak: %+v", e.List()[0])
	}
	// a device already on the new version is never re-offered
	if e.Offer("A1", pb.Ring_RING_ALPHA, 2) != nil {
		t.Fatal("re-offered a current device")
	}
	// beta slice fails -> halt, and nothing further is offered
	offered := 0
	for i := 0; i < 200; i++ {
		id := fmt.Sprintf("B%d", i)
		if e.Offer(id, pb.Ring_RING_BETA, 1) != nil {
			offered++
			e.Report("r1", id, RolledBack)
		}
	}
	if offered == 0 {
		t.Fatal("no beta devices in the 20% slice")
	}
	e.Evaluate(time.Unix(0, 0).Add(10 * time.Hour))
	if e.List()[0].State != "HALTED" {
		t.Fatalf("rollbacks did not halt the release: %+v", e.List()[0])
	}
	if e.Offer("B1", pb.Ring_RING_BETA, 1) != nil || e.Offer("S1", pb.Ring_RING_STABLE, 1) != nil {
		t.Fatal("halted release still offered")
	}
}

func TestUnsignedReleaseRejected(t *testing.T) {
	pub, _, _ := ed25519.GenerateKey(rand.Reader)
	e := NewEngine(pub)
	if err := e.Register(mf("x", 1, pb.Ring_RING_ALPHA), nil, time.Now()); err == nil {
		t.Fatal("unsigned manifest registered")
	}
}
