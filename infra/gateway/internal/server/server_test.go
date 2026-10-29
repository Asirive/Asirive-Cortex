package server

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
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

	if code, _ := post(t, ts.URL+"/api/registrations", "wrong", map[string]any{"tier": "BETA"}); code != 401 {
		t.Fatalf("registration without operator token: %d", code)
	}
	_, reg := post(t, ts.URL+"/api/registrations", "optoken", map[string]any{"tier": "BETA", "label": "Sam's glasses", "bench": true})
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
	if code, out := post(t, ts.URL+"/api/devices/"+id+"/command", "optoken", map[string]any{"name": "reboot"}); code != 409 {
		t.Fatalf("beta device accepted a debug command: %d %v", code, out)
	}

	post(t, ts.URL+"/api/registrations/"+id+"/revoke", "optoken", map[string]any{})
	time.Sleep(200 * time.Millisecond)
	if _, _, err := dial(t, ts, id, tok); err == nil {
		t.Fatal("revoked device reconnected")
	}
	if code, _ := post(t, ts.URL+"/v1/claim", "", map[string]any{"claim_code": claim}); code == 200 {
		t.Fatal("claim code reusable")
	}
}
