package server

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/asirive/cortex/gateway/internal/fleet"
	pb "github.com/asirive/cortex/gateway/internal/gen/cortex/v1"
	"github.com/gorilla/websocket"
	"google.golang.org/protobuf/proto"
)

func post(t *testing.T, url, token string, body any) (int, map[string]any) {
	b, _ := json.Marshal(body)
	req, _ := http.NewRequest("POST", url, bytes.NewReader(b))
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	var out map[string]any
	json.NewDecoder(res.Body).Decode(&out)
	return res.StatusCode, out
}

func dial(t *testing.T, ts *httptest.Server, id, tok string) (*websocket.Conn, *http.Response, error) {
	h := http.Header{"Authorization": {"Bearer " + tok}, "X-Device-Id": {id}}
	return websocket.DefaultDialer.Dial("ws"+strings.TrimPrefix(ts.URL, "http")+"/ws/device", h)
}

func hello(ws *websocket.Conn, id string, tier pb.Tier) {
	pl, _ := proto.Marshal(&pb.Hello{Tier: tier, Ring: pb.Ring_RING_ALPHA, BenchDevice: true, HeartbeatIntervalS: 5})
	b, _ := proto.Marshal(&pb.Envelope{Header: &pb.Header{SchemaVersion: 1, DeviceId: id, Seq: 1, TsMs: time.Now().UnixMilli()},
		Type: pb.PayloadType_PAYLOAD_TYPE_HELLO, Payload: pl})
	ws.WriteMessage(websocket.BinaryMessage, b)
}

func TestRegisterClaimConnectRevoke(t *testing.T) {
	s := New(fleet.New(), "optoken")
	ts := httptest.NewServer(s.Handler())
	defer ts.Close()

	if code, _ := post(t, ts.URL+"/api/registrations", "wrong", map[string]any{"tier": "BETA", "label": "x"}); code != 401 {
		t.Fatalf("registration without operator token: %d", code)
	}
	for name, body := range map[string]map[string]any{
		"blank label":    {"tier": "BETA", "label": "   "},
		"bench on beta":  {"tier": "BETA", "label": "x", "bench": true},
		"bad tier":       {"tier": "GOLD", "label": "x"},
		"label too long": {"tier": "BETA", "label": strings.Repeat("a", 81)},
	} {
		if code, _ := post(t, ts.URL+"/api/registrations", "optoken", body); code != 400 {
			t.Fatalf("%s accepted: %d", name, code)
		}
	}
	if code, _ := post(t, ts.URL+"/api/registrations", "optoken", map[string]any{"tier": "BETA", "label": strings.Repeat("é", 80)}); code != 200 {
		t.Fatalf("80 multibyte characters must be allowed: %d", code)
	}
	_, reg := post(t, ts.URL+"/api/registrations", "optoken", map[string]any{"tier": "BETA", "label": "Sam's glasses"})
	id := reg["registration"].(map[string]any)["id"].(string)
	claim := reg["claim_code"].(string)

	if _, _, err := dial(t, ts, id, "guess"); err == nil {
		t.Fatal("unclaimed device connected")
	}
	code, c := post(t, ts.URL+"/v1/claim", "", map[string]any{"claim_code": claim, "account_id": "u1"})
	if code != 200 {
		t.Fatalf("claim failed: %d %v", code, c)
	}
	tok := c["device_token"].(string)

	// device lies about its tier in Hello; registry must win
	ws, _, err := dial(t, ts, id, tok)
	if err != nil {
		t.Fatalf("claimed device rejected: %v", err)
	}
	hello(ws, id, pb.Tier_TIER_ALPHA)
	time.Sleep(300 * time.Millisecond)
	d, _, _, _ := s.Fleet.Get(id)
	if d.Tier != "BETA" || d.Bench {
		t.Fatalf("device self-declared its tier: %+v", d)
	}
	if code, out := post(t, ts.URL+"/api/devices/"+id+"/command", "optoken", map[string]any{"name": "rm -rf /"}); code != 400 {
		t.Fatalf("unknown command accepted: %d %v", code, out)
	}
	if code, out := post(t, ts.URL+"/api/devices/"+id+"/command", "optoken", map[string]any{"name": "reboot"}); code != 409 {
		t.Fatalf("beta device accepted a debug command: %d %v", code, out)
	}

	if code, _ := post(t, ts.URL+"/api/registrations/"+id+"/revoke", "optoken", map[string]any{}); code != 200 {
		t.Fatalf("revoke failed: %d", code)
	}
	if code, _ := post(t, ts.URL+"/api/registrations/"+id+"/revoke", "optoken", map[string]any{}); code != 409 {
		t.Fatalf("second revoke must conflict: %d", code)
	}
	if code, _ := post(t, ts.URL+"/api/registrations/NOPE-1/revoke", "optoken", map[string]any{}); code != 404 {
		t.Fatalf("revoke of unknown device: %d", code)
	}
	time.Sleep(200 * time.Millisecond)
	if _, _, err := dial(t, ts, id, tok); err == nil {
		t.Fatal("revoked device reconnected")
	}
	if code, _ := post(t, ts.URL+"/v1/claim", "", map[string]any{"claim_code": claim}); code == 200 {
		t.Fatal("claim code reusable")
	}
}

func TestReconnectDoesNotMarkOffline(t *testing.T) {
	s := New(fleet.New(), "optoken")
	s.AllowSharedDeviceToken = true
	ts := httptest.NewServer(s.Handler())
	defer ts.Close()
	a, _, err := dial(t, ts, "ALPHA-X", "optoken")
	if err != nil {
		t.Fatal(err)
	}
	hello(a, "ALPHA-X", pb.Tier_TIER_ALPHA)
	time.Sleep(200 * time.Millisecond)
	b, _, _ := dial(t, ts, "ALPHA-X", "optoken")
	hello(b, "ALPHA-X", pb.Tier_TIER_ALPHA)
	time.Sleep(300 * time.Millisecond)
	a.Close() // the replaced connection dies; the live one must stay online
	time.Sleep(300 * time.Millisecond)
	if d, _, _, _ := s.Fleet.Get("ALPHA-X"); !d.Online {
		t.Fatal("replaced connection marked the live device offline")
	}
}

func TestHeartbeatIntervalClamped(t *testing.T) {
	if clampHB(3600) != 60 || clampHB(0) != 5 || clampHB(1) != 2 || clampHB(1<<31) != 60 {
		t.Fatal("heartbeat interval not clamped")
	}
}

func TestOperatorTokenGuessingIsLimited(t *testing.T) {
	s := New(fleet.New(), "optoken")
	ts := httptest.NewServer(s.Handler())
	defer ts.Close()
	var last int
	for i := 0; i < 12; i++ {
		last, _ = post(t, ts.URL+"/api/registrations", "guess", map[string]any{"tier": "BETA", "label": "x"})
	}
	if last != 429 {
		t.Fatalf("token guessing not rate limited: %d", last)
	}
}

func TestStateSurvivesRestart(t *testing.T) {
	path := t.TempDir() + "/state.json"
	s := New(fleet.New(), "optoken")
	ts := httptest.NewServer(s.Handler())
	_, reg := post(t, ts.URL+"/api/registrations", "optoken", map[string]any{"tier": "ALPHA", "label": "bench 1", "bench": true})
	id := reg["registration"].(map[string]any)["id"].(string)
	_, c := post(t, ts.URL+"/v1/claim", "", map[string]any{"claim_code": reg["claim_code"], "account_id": "u1"})
	tok := c["device_token"].(string)
	_, pend := post(t, ts.URL+"/api/registrations", "optoken", map[string]any{"tier": "BETA", "label": "unclaimed"})
	if err := s.SaveState(path); err != nil {
		t.Fatal(err)
	}
	ts.Close()

	s2 := New(fleet.New(), "optoken") // gateway restarted
	if err := s2.LoadState(path); err != nil {
		t.Fatal(err)
	}
	ts2 := httptest.NewServer(s2.Handler())
	defer ts2.Close()
	ws, _, err := dial(t, ts2, id, tok)
	if err != nil {
		t.Fatalf("claimed device locked out after restart: %v", err)
	}
	ws.Close()
	if _, _, err := dial(t, ts2, id, "wrong"); err == nil {
		t.Fatal("wrong token accepted after restart")
	}
	if code, _ := post(t, ts2.URL+"/v1/claim", "", map[string]any{"claim_code": pend["claim_code"], "account_id": "u2"}); code != 200 {
		t.Fatalf("pending claim code lost across restart: %d", code)
	}
	if code, _ := post(t, ts2.URL+"/v1/claim", "", map[string]any{"claim_code": reg["claim_code"], "account_id": "u3"}); code == 200 {
		t.Fatal("used claim code reusable after restart")
	}
	if err := os.WriteFile(path, []byte("{broken"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := New(fleet.New(), "x").LoadState(path); err == nil {
		t.Fatal("corrupt state file loaded silently")
	}
}
