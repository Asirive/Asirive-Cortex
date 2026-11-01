package server

import (
	"context"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/asirive/cortex/gateway/internal/fleet"
)

// Runs only when CORTEX_TEST_PG is set to a DSN for a scratch database.
func TestPostgresStateAndLeadership(t *testing.T) {
	dsn := os.Getenv("CORTEX_TEST_PG")
	if dsn == "" {
		t.Skip("CORTEX_TEST_PG not set")
	}
	ctx := context.Background()
	a, err := OpenPG(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	a.db.Exec(`DELETE FROM cortex_state`)
	b, _ := OpenPG(ctx, dsn)
	if ok, _ := a.TryLead(ctx); !ok {
		t.Fatal("first gateway could not lead")
	}
	if ok, _ := b.TryLead(ctx); ok {
		t.Fatal("two gateways lead at once")
	}
	if b.Write([]byte("{}")) == nil {
		t.Fatal("standby was allowed to write state")
	}

	s := New(fleet.New(), "boot")
	ts := httptest.NewServer(s.Handler())
	_, reg := post(t, ts.URL+"/api/registrations", "boot", map[string]any{"tier": "BETA", "label": "pg"})
	tok := login(t, s, "pg@example.com")
	_, c := post(t, ts.URL+"/v1/claim", tok, map[string]any{"claim_code": reg["claim_code"]})
	ts.Close()
	if err := s.SaveTo(a); err != nil {
		t.Fatal(err)
	}

	// leader dies: standby takes over and sees everything
	b.db.Exec(`SELECT pg_terminate_backend(pid) FROM pg_locks WHERE locktype = 'advisory' AND granted`) // kill the leader's session like a crash
	time.Sleep(300 * time.Millisecond)
	if a.StillLeader(ctx) {
		t.Fatal("dead leader still thinks it leads")
	}
	var ok bool
	for i := 0; i < 20 && !ok; i++ {
		ok, _ = b.TryLead(ctx)
		time.Sleep(100 * time.Millisecond)
	}
	if !ok {
		t.Fatal("standby never took over")
	}
	s2 := New(fleet.New(), "boot")
	if err := s2.LoadFrom(b); err != nil {
		t.Fatal(err)
	}
	ts2 := httptest.NewServer(s2.Handler())
	defer ts2.Close()
	ws, _, err := dial(t, ts2, c["device_id"].(string), c["device_token"].(string))
	if err != nil {
		t.Fatalf("device locked out after failover: %v", err)
	}
	ws.Close()
	if code, _ := get(t, ts2.URL+"/v1/me", tok); code != 200 {
		t.Fatalf("app session lost after failover: %d", code)
	}
}
