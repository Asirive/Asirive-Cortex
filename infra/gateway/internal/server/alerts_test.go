package server

import (
	"encoding/hex"
	"github.com/asirive/cortex/gateway/internal/cmdsign"
	pb "github.com/asirive/cortex/gateway/internal/gen/cortex/v1"
	"google.golang.org/protobuf/proto"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/asirive/cortex/gateway/internal/fleet"
)

func TestAlertsAfterGraceRepeatAndClear(t *testing.T) {
	s := New(fleet.New(), "boot")
	in := &inbox{}
	s.Mailer, s.AlertTo = in, []string{"ops@example.com"}
	ts := httptest.NewServer(s.Handler())
	defer ts.Close()
	_, reg := post(t, ts.URL+"/api/registrations", "boot", map[string]any{"tier": "BETA", "label": "Sam"})
	_, c := post(t, ts.URL+"/v1/claim", login(t, s, "a@example.com"), map[string]any{"claim_code": reg["claim_code"]})
	id, tok := c["device_id"].(string), c["device_token"].(string)
	ws, _, err := dial(t, ts, id, tok)
	if err != nil {
		t.Fatal(err)
	}
	hello(ws, id, 0)
	time.Sleep(150 * time.Millisecond)
	ws.Close() // goes offline
	time.Sleep(150 * time.Millisecond)
	s.Fleet.Sweep(time.Now())

	t0 := time.Now()
	s.alertTick(t0)
	time.Sleep(50 * time.Millisecond)
	if in.count() != 0 {
		t.Fatal("alerted before the grace period")
	}
	s.alertTick(t0.Add(4 * time.Minute))
	m := in.last(t)
	if !strings.Contains(m, "ops@example.com") || !strings.Contains(m, id) || !strings.Contains(m, "Offline") {
		t.Fatalf("alert content: %s", m)
	}
	s.alertTick(t0.Add(5 * time.Minute))
	time.Sleep(50 * time.Millisecond)
	if in.count() != 1 {
		t.Fatalf("repeat too soon: %d mails", in.count())
	}
	s.alertTick(t0.Add(7 * time.Hour))
	time.Sleep(50 * time.Millisecond)
	if in.count() != 2 {
		t.Fatalf("no repeat after 6h: %d", in.count())
	}
	post(t, ts.URL+"/api/registrations/"+id+"/revoke", "boot", nil) // leaves the live fleet
	s.alertTick(t0.Add(7*time.Hour + time.Minute))
	time.Sleep(50 * time.Millisecond)
	if in.count() != 3 || !strings.Contains(in.last(t), "recovered") && !strings.Contains(in.msgs[2], "No longer") {
		t.Fatalf("no all-clear: %v", in.msgs)
	}
}

func TestDebugCommandIsSignedAndBoundToDevice(t *testing.T) {
	s := New(fleet.New(), "boot")
	ts := httptest.NewServer(s.Handler())
	defer ts.Close()
	_, reg := post(t, ts.URL+"/api/registrations", "boot", map[string]any{"tier": "ALPHA", "label": "bench", "bench": true})
	_, c := post(t, ts.URL+"/v1/claim", login(t, s, "b@example.com"), map[string]any{"claim_code": reg["claim_code"]})
	id := c["device_id"].(string)
	pub, _ := hex.DecodeString(c["command_public_key"].(string))
	ws, _, err := dial(t, ts, id, c["device_token"].(string))
	if err != nil {
		t.Fatal(err)
	}
	defer ws.Close()
	hello(ws, id, pb.Tier_TIER_ALPHA)
	time.Sleep(200 * time.Millisecond)
	if code, b := post(t, ts.URL+"/api/devices/"+id+"/command", "boot", map[string]any{"name": "dump_state"}); code != 200 {
		t.Fatalf("command: %d %v", code, b)
	}
	ws.SetReadDeadline(time.Now().Add(3 * time.Second))
	for {
		_, raw, err := ws.ReadMessage()
		if err != nil {
			t.Fatal("no command received")
		}
		var env pb.Envelope
		if proto.Unmarshal(raw, &env) != nil || env.Type != pb.PayloadType_PAYLOAD_TYPE_DEBUG_COMMAND {
			continue
		}
		var dc pb.DebugCommand
		proto.Unmarshal(env.Payload, &dc)
		v := &cmdsign.Verifier{Pub: pub, DeviceID: id}
		if err := v.Verify(&dc, time.Now()); err != nil {
			t.Fatalf("device would reject the command: %v", err)
		}
		if dc.Issuer != "bootstrap" {
			t.Fatalf("issuer: %q", dc.Issuer)
		}
		return
	}
}
