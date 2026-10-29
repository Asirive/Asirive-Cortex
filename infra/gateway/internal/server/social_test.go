package server

import (
	"crypto/ed25519"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha1"
	"encoding/base64"
	"encoding/json"
	"github.com/asirive/cortex/gateway/internal/push"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/asirive/cortex/gateway/internal/fleet"
	pb "github.com/asirive/cortex/gateway/internal/gen/cortex/v1"
	"github.com/asirive/cortex/gateway/internal/ota"
	"github.com/asirive/cortex/gateway/internal/social"
)

func TestCompanionGrantsLocationAndCalls(t *testing.T) {
	s := New(fleet.New(), "boot")
	ts := httptest.NewServer(s.Handler())
	defer ts.Close()
	u := ts.URL + "/v1"
	owner, comp, stranger := login(t, s, "owner@example.com"), login(t, s, "mum@example.com"), login(t, s, "x@example.com")
	_, me := get(t, u+"/me", owner)
	ownerID := between(string(me), `"id":"`, `"`)
	_, cme := get(t, u+"/me", comp)
	compID := between(string(cme), `"id":"`, `"`)

	_, inv := post(t, u+"/companions", owner, map[string]any{"label": "Mum"})
	code := inv["invite_code"].(string)
	linkID := inv["link"].(map[string]any)["id"].(string)
	if c, _ := post(t, u+"/companions/accept", owner, map[string]any{"code": code}); c != 400 {
		t.Fatalf("owner accepted own invite: %d", c)
	}
	if c, _ := post(t, u+"/companions/accept", comp, map[string]any{"code": "AAAA-AAAA"}); c != 422 {
		t.Fatalf("bad code: %d", c)
	}
	if c, _ := post(t, u+"/companions/accept", comp, map[string]any{"code": code}); c != 200 {
		t.Fatalf("accept: %d", c)
	}
	if c, _ := post(t, u+"/companions/accept", stranger, map[string]any{"code": code}); c != 422 {
		t.Fatal("invite code reusable")
	}

	// location is shared only after the owner grants it, and only with that companion
	if c, _ := put(t, u+"/me/location", owner, map[string]any{"lat": 3.1, "lon": 101.6, "accuracy_m": 8}); c != 200 {
		t.Fatalf("put location: %d", c)
	}
	if c, _ := put(t, u+"/me/location", owner, map[string]any{"lat": 99, "lon": 0}); c != 400 {
		t.Fatalf("bad latitude accepted: %d", c)
	}
	if c, _ := get(t, u+"/companion/users/"+ownerID+"/location", comp); c != 404 {
		t.Fatalf("location readable without a grant: %d", c)
	}
	if c, _ := put(t, u+"/companions/"+linkID+"/grants", owner, map[string]any{"location": true, "call": true}); c != 200 {
		t.Fatal("grant failed")
	}
	if c, _ := put(t, u+"/companions/"+linkID+"/grants", comp, map[string]any{"location": true}); c != 404 {
		t.Fatalf("companion changed its own grants: %d", c)
	}
	if c, b := get(t, u+"/companion/users/"+ownerID+"/location", comp); c != 200 || !strings.Contains(string(b), "3.1") {
		t.Fatalf("granted location: %d %s", c, b)
	}
	if c, _ := get(t, u+"/companion/users/"+ownerID+"/location", stranger); c != 404 {
		t.Fatal("stranger read location")
	}

	// call signalling
	if c, _ := post(t, u+"/calls", stranger, map[string]any{"to": ownerID, "offer": "sdp"}); c != 403 {
		t.Fatalf("stranger called: %d", c)
	}
	c, call := post(t, u+"/calls", comp, map[string]any{"to": ownerID, "offer": "v=0 offer"})
	if c != 200 {
		t.Fatalf("call: %d %v", c, call)
	}
	cid := call["call_id"].(string)
	if c, b := get(t, u+"/calls/inbox", owner); c != 200 || !strings.Contains(string(b), "v=0 offer") {
		t.Fatalf("inbox: %s", b)
	}
	if c, _ := get(t, u+"/calls/"+cid, stranger); c != 404 {
		t.Fatal("stranger read a call")
	}
	post(t, u+"/calls/"+cid+"/ice", comp, map[string]any{"candidate": "cand-from-caller"})
	if c, _ := post(t, u+"/calls/"+cid+"/answer", owner, map[string]any{"answer": "v=0 answer"}); c != 200 {
		t.Fatal("answer failed")
	}
	if _, b := get(t, u+"/calls/"+cid, comp); !strings.Contains(string(b), "v=0 answer") {
		t.Fatalf("caller doesn't see answer: %s", b)
	}
	if _, b := get(t, u+"/calls/"+cid, owner); !strings.Contains(string(b), "cand-from-caller") {
		t.Fatalf("callee doesn't see ICE: %s", b)
	}
	// revoking the link ends the call and stops everything
	if c, _ := del2(t, u+"/companions/"+linkID, comp); c != 200 {
		t.Fatal("companion could not leave")
	}
	if _, b := get(t, u+"/calls/"+cid, owner); !strings.Contains(string(b), `"state":"ended"`) {
		t.Fatalf("call survived revoke: %s", b)
	}
	if c, _ := get(t, u+"/companion/users/"+ownerID+"/location", comp); c != 404 {
		t.Fatal("location readable after revoke")
	}
	_ = compID

	// deleting the owner wipes location and links
	if c := del(t, u+"/me", owner, map[string]any{"password": "correct horse battery"}); c != 200 {
		t.Fatalf("delete: %d", c)
	}
	if _, err := s.Social.CompanionLocation(compID, ownerID, time.Now()); err == nil {
		t.Fatal("location outlived the account")
	}
}

func TestLocationExpiresAfter30Days(t *testing.T) {
	st := social.New()
	t0 := time.Now().Add(-31 * 24 * time.Hour)
	st.PutLocation("o", social.Point{Lat: 1, Lon: 1}, t0)
	st.Sweep(time.Now())
	st.Invite("o", "x", time.Now()) // unrelated data stays
	l, c, _ := st.Invite("o", "Mum", time.Now())
	st.Accept("m", c, time.Now())
	st.SetGrants("o", l.ID, true, false)
	if _, err := st.CompanionLocation("m", "o", time.Now()); err == nil {
		t.Fatal("31-day-old location still readable")
	}
}

func TestFeedbackAndUpdatePathFromApp(t *testing.T) {
	s := New(fleet.New(), "boot")
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	s.WireOTA(ota.NewEngine(pub))
	ts := httptest.NewServer(s.Handler())
	defer ts.Close()
	u := ts.URL + "/v1"
	tok := login(t, s, "fb@example.com")
	if c, _ := post(t, u+"/feedback", tok, map[string]any{"text": "hi"}); c != 400 {
		t.Fatalf("feedback with no device: %d", c)
	}
	_, reg := post(t, ts.URL+"/api/registrations", "boot", map[string]any{"tier": "STABLE", "label": "g"})
	_, cl := post(t, u+"/claim", tok, map[string]any{"claim_code": reg["claim_code"]})
	id := cl["device_id"].(string)
	if c, _ := post(t, u+"/feedback", tok, map[string]any{"text": "the beep is too quiet"}); c != 200 {
		t.Fatal("feedback rejected")
	}
	if _, b := get(t, ts.URL+"/api/feedback", "boot"); !strings.Contains(string(b), "too quiet") {
		t.Fatalf("operator can't see feedback: %s", b)
	}

	m := &pb.Manifest{ReleaseId: "r9", VersionCounter: 9, MaxRing: pb.Ring_RING_STABLE, Artifacts: []*pb.Artifact{{Version: "4.1.0", Url: "https://x/y", SizeBytes: 3}}}
	ota.Sign(m, priv)
	s.OTA.Register(m, []ota.Stage{{Ring: pb.Ring_RING_STABLE, Percent: 100, Soak: time.Minute, MinHealthyPc: 0.9}}, time.Now())
	if c, b := get(t, u+"/me/devices/"+id+"/update?counter=1", tok); c != 200 || !strings.Contains(string(b), "r9") {
		t.Fatalf("update offer: %d %s", c, b)
	}
	if c, _ := get(t, u+"/me/devices/"+id+"/update?counter=9", tok); c != 204 {
		t.Fatalf("offered an update already installed: %d", c)
	}
	other := login(t, s, "o2@example.com")
	if c, _ := get(t, u+"/me/devices/"+id+"/update?counter=1", other); c != 404 {
		t.Fatalf("another account probed my device: %d", c)
	}
	if c, _ := post(t, u+"/me/devices/"+id+"/update", tok, map[string]any{"release_id": "r9", "outcome": "rolled_back"}); c != 200 {
		t.Fatal("report failed")
	}
	if c, _ := get(t, u+"/me/devices/"+id+"/update?counter=1", tok); c != 204 {
		t.Fatalf("rolled-back device re-offered: %d", c)
	}
	// deleting the account removes its feedback
	del(t, u+"/me", tok, map[string]any{"password": "correct horse battery"})
	if _, b := get(t, ts.URL+"/api/feedback", "boot"); strings.Contains(string(b), "too quiet") {
		t.Fatal("feedback outlived the account")
	}
}

func between(s, a, b string) string {
	i := strings.Index(s, a)
	if i < 0 {
		return ""
	}
	s = s[i+len(a):]
	return s[:strings.Index(s, b)]
}

func del2(t *testing.T, url, token string) (int, []byte) {
	return reqBody(t, "DELETE", url, token)
}

func reqBody(t *testing.T, method, url, token string) (int, []byte) {
	req, _ := http.NewRequest(method, url, nil)
	req.Header.Set("Authorization", "Bearer "+token)
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	b, _ := io.ReadAll(res.Body)
	return res.StatusCode, b
}

type rec struct {
	mu   sync.Mutex
	sent []string
	err  error
}

func (r *rec) Send(platform, token string, m push.Message) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.sent = append(r.sent, platform+":"+token+":"+m.Body+":"+m.Data["call_id"])
	return r.err
}
func (r *rec) wait(n int) []string {
	for i := 0; i < 100; i++ {
		r.mu.Lock()
		if len(r.sent) >= n {
			out := append([]string(nil), r.sent...)
			r.mu.Unlock()
			return out
		}
		r.mu.Unlock()
		time.Sleep(20 * time.Millisecond)
	}
	return nil
}

func TestCallPushAndTurn(t *testing.T) {
	s := New(fleet.New(), "boot")
	pr := &rec{}
	s.Pusher = pr
	s.TurnSecret, s.TurnURLs = "s3cret", []string{"turn:turn.example.com:3478?transport=udp"}
	ts := httptest.NewServer(s.Handler())
	defer ts.Close()
	u := ts.URL + "/v1"
	owner, comp := login(t, s, "o@example.com"), login(t, s, "c@example.com")
	ownerID := between(func() string { _, b := get(t, u+"/me", owner); return string(b) }(), `"id":"`, `"`)
	_, inv := post(t, u+"/companions", owner, map[string]any{"label": "Mum"})
	post(t, u+"/companions/accept", comp, map[string]any{"code": inv["invite_code"]})
	put(t, u+"/companions/"+inv["link"].(map[string]any)["id"].(string)+"/grants", owner, map[string]any{"call": true})

	if c, _ := put(t, u+"/me/push", owner, map[string]any{"platform": "windows", "token": "abcdefgh12"}); c != 400 {
		t.Fatalf("bad platform: %d", c)
	}
	put(t, u+"/me/push", owner, map[string]any{"platform": "ios", "token": "iosdevicetoken1"})
	_, call := post(t, u+"/calls", comp, map[string]any{"to": ownerID, "offer": "sdp"})
	got := pr.wait(1)
	if len(got) != 1 || !strings.HasPrefix(got[0], "ios:iosdevicetoken1:Incoming call:"+call["call_id"].(string)) {
		t.Fatalf("callee not woken with a generic message: %v", got)
	}
	if strings.Contains(got[0], "Mum") || strings.Contains(got[0], "@") {
		t.Fatal("push leaked a name or email")
	}
	// dead token is dropped
	pr.err = push.ErrUnregistered
	post(t, u+"/calls/"+call["call_id"].(string)+"/end", comp, nil)
	post(t, u+"/calls", comp, map[string]any{"to": ownerID, "offer": "sdp"})
	pr.wait(2)
	time.Sleep(100 * time.Millisecond)
	if len(s.Social.PushTokens(ownerID)) != 0 {
		t.Fatal("unregistered token kept")
	}

	// TURN credentials follow the coturn REST scheme
	c, b := get(t, u+"/calls/ice-servers", comp)
	if c != 200 {
		t.Fatalf("ice: %d %s", c, b)
	}
	var out struct {
		Ice []struct {
			Username   string `json:"username"`
			Credential string `json:"credential"`
		} `json:"ice_servers"`
	}
	json.Unmarshal(b, &out)
	mac := hmac.New(sha1.New, []byte("s3cret"))
	mac.Write([]byte(out.Ice[0].Username))
	if out.Ice[0].Credential != base64.StdEncoding.EncodeToString(mac.Sum(nil)) || !strings.Contains(out.Ice[0].Username, ":") {
		t.Fatalf("bad TURN credential: %s", b)
	}
	s.TurnSecret = ""
	if c, _ := get(t, u+"/calls/ice-servers", comp); c != 503 {
		t.Fatal("served TURN without a secret")
	}
}
