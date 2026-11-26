package server

import (
	"bytes"
	"crypto/tls"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/gorilla/websocket"

	"github.com/asirive/cortex/gateway/internal/fleet"
	"github.com/asirive/cortex/gateway/internal/gemini"
	"github.com/asirive/cortex/gateway/internal/pki"
)

func TestSecondOpinionOnTheDeviceListener(t *testing.T) {
	var upstream atomic.Int32
	var frames atomic.Int32
	up := websocket.Upgrader{}
	gm := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upstream.Add(1)
		if r.Header.Get("x-goog-api-key") != "srv-gemini" {
			w.WriteHeader(403)
			return
		}
		conn, err := up.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		var setup, turn map[string]any
		conn.ReadJSON(&setup)
		conn.WriteJSON(map[string]any{"setupComplete": map[string]any{}})
		conn.ReadJSON(&turn)
		n := int32(0)
		for _, p := range turn["clientContent"].(map[string]any)["turns"].([]any)[0].(map[string]any)["parts"].([]any) {
			if _, ok := p.(map[string]any)["inlineData"]; ok {
				n++
			}
		}
		frames.Store(n)
		conn.WriteJSON(map[string]any{"serverContent": map[string]any{"outputTranscription": map[string]any{"text": "It is bus 858, right in front of you."}}})
		conn.WriteJSON(map[string]any{"serverContent": map[string]any{"turnComplete": true, "interactionStatus": "IDLE"}})
		conn.ReadMessage()
	}))
	defer gm.Close()

	ca, _ := pki.LoadOrCreate(t.TempDir(), time.Now())
	s := New(fleet.New(), "boot")
	s.CA, s.RequireMTLS = ca, true
	api := httptest.NewServer(s.Handler())
	defer api.Close()
	sc, roots := serverCert(t)
	dev := httptest.NewUnstartedServer(s.DeviceHandler())
	dev.TLS = s.DeviceTLS(sc)
	dev.StartTLS()
	defer dev.Close()
	acct := login(t, s, "gemini@example.com")
	a := claimDevice(t, s, api.URL, acct)
	c := &http.Client{Transport: &http.Transport{TLSClientConfig: a.tlsCfg(roots)}}

	img := base64.StdEncoding.EncodeToString(append([]byte{0xFF, 0xD8, 0xFF, 0xE0}, make([]byte, 64)...))
	ask := func(cl *http.Client, base string, body any) (int, map[string]any) {
		b, _ := json.Marshal(body)
		res, err := cl.Post(base+"/device/second-opinion", "application/json", bytes.NewReader(b))
		if err != nil {
			return 0, nil
		}
		defer res.Body.Close()
		var m map[string]any
		json.NewDecoder(res.Body).Decode(&m)
		return res.StatusCode, m
	}
	good := map[string]any{"question": "which bus is this", "frames_jpeg": []string{img, img, img}}

	if code, _ := ask(c, dev.URL, good); code != 503 { // no key: says so, never calls out
		t.Fatalf("no key: %d", code)
	}
	if upstream.Load() != 0 {
		t.Fatal("called Gemini without a key")
	}
	s.Gemini = gemini.New("srv-gemini")
	s.Gemini.Base = "ws" + strings.TrimPrefix(gm.URL, "http")

	code, m := ask(c, dev.URL, good)
	if code != 200 || m["answer"] != "It is bus 858, right in front of you." {
		t.Fatalf("answer: %d %v", code, m)
	}
	if frames.Load() != 3 {
		t.Fatalf("frames passed on: %d", frames.Load())
	}
	if code, _ := ask(c, dev.URL, map[string]any{"question": "what time is it"}); code != 200 { // camera off: no frames is fine
		t.Fatalf("no image: %d", code)
	}
	for _, bad := range []any{map[string]any{"question": ""}, map[string]any{"question": "q", "frames_jpeg": []string{"@@@"}},
		map[string]any{"question": "q", "frames_jpeg": []string{base64.StdEncoding.EncodeToString([]byte("PNG..."))}},
		map[string]any{"question": "q", "frames_jpeg": []string{img, img, img, img, img, img, img}},
		map[string]any{"question": strings.Repeat("x", gemini.MaxQuestion+1)}} {
		if code, _ := ask(c, dev.URL, bad); code != 400 {
			t.Fatalf("%v: %d", bad, code)
		}
	}
	// no client certificate: refused; the public listener does not serve it
	if code, _ := ask(&http.Client{Transport: &http.Transport{TLSClientConfig: &tls.Config{RootCAs: roots}}}, dev.URL, good); code != 0 {
		t.Fatalf("served without a certificate: %d", code)
	}
	if code, _ := ask(http.DefaultClient, api.URL, good); code == 200 {
		t.Fatal("second opinion on the public listener")
	}
	// cost cap per minute
	limited := false
	for i := 0; i < opinionPerMin+1; i++ {
		if code, _ := ask(c, dev.URL, good); code == 429 {
			limited = true
			break
		}
	}
	if !limited {
		t.Fatal("no rate limit")
	}
	// Gemini down: 502, the box says it is not sure
	s.opinionRate = rateWindow{}
	s.Gemini.Base = "ws://127.0.0.1:1"
	if code, _ := ask(c, dev.URL, good); code != 502 {
		t.Fatalf("upstream down: %d", code)
	}
	// a revoked device is cut off
	post(t, api.URL+"/api/registrations/"+a.id+"/revoke", "boot", nil)
	c.CloseIdleConnections()
	if code, _ := ask(c, dev.URL, good); code == 200 {
		t.Fatal("revoked device still gets answers")
	}
}

func TestSecondOpinionDailyCap(t *testing.T) {
	var rw rateWindow
	t0 := time.Unix(1000, 0)
	for i := 0; i < opinionPerDay; i++ {
		if !rw.allowWithin("d", t0.Add(time.Duration(i)*time.Minute), opinionPerDay, 24*time.Hour) {
			t.Fatalf("refused at %d", i)
		}
	}
	if rw.allowWithin("d", t0.Add(23*time.Hour), opinionPerDay, 24*time.Hour) {
		t.Fatal("over the daily cap")
	}
	if !rw.allowWithin("d", t0.Add(25*time.Hour), opinionPerDay, 24*time.Hour) {
		t.Fatal("daily window did not slide")
	}
}

// With Accept: application/x-ndjson the box gets each sentence the moment Gemini finishes it, so it can start
// speaking while the rest is still being made: {"sentence": ...} lines, then {"done": true, "answer": ...}.
func TestSecondOpinionStreamsSentences(t *testing.T) {
	release := make(chan struct{})
	up := websocket.Upgrader{}
	fail := false
	gm := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := up.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		var m map[string]any
		conn.ReadJSON(&m)
		conn.WriteJSON(map[string]any{"setupComplete": map[string]any{}})
		conn.ReadJSON(&m)
		tr := func(s string) map[string]any {
			return map[string]any{"serverContent": map[string]any{"outputTranscription": map[string]any{"text": s}}}
		}
		conn.WriteJSON(tr("It is bus 858. "))
		conn.WriteJSON(tr("It is"))
		<-release // Gemini is still talking until the test has the first sentence
		if fail {
			return // connection drops mid-answer
		}
		conn.WriteJSON(tr(" stopping now."))
		conn.WriteJSON(map[string]any{"serverContent": map[string]any{"turnComplete": true, "interactionStatus": "IDLE"}})
		conn.ReadMessage()
	}))
	defer gm.Close()

	ca, _ := pki.LoadOrCreate(t.TempDir(), time.Now())
	s := New(fleet.New(), "boot")
	s.CA, s.RequireMTLS = ca, true
	s.Gemini = gemini.New("k")
	s.Gemini.Base = "ws" + strings.TrimPrefix(gm.URL, "http")
	api := httptest.NewServer(s.Handler())
	defer api.Close()
	sc, roots := serverCert(t)
	dev := httptest.NewUnstartedServer(s.DeviceHandler())
	dev.TLS = s.DeviceTLS(sc)
	dev.StartTLS()
	defer dev.Close()
	a := claimDevice(t, s, api.URL, login(t, s, "stream@example.com"))
	c := &http.Client{Transport: &http.Transport{TLSClientConfig: a.tlsCfg(roots)}}

	open := func() (*http.Response, *json.Decoder) {
		req, _ := http.NewRequest("POST", dev.URL+"/device/second-opinion", strings.NewReader(`{"question":"which bus"}`))
		req.Header.Set("Accept", "application/x-ndjson")
		res, err := c.Do(req)
		if err != nil || res.StatusCode != 200 || res.Header.Get("Content-Type") != "application/x-ndjson" {
			t.Fatalf("open: %v %v", err, res)
		}
		return res, json.NewDecoder(res.Body)
	}
	next := func(d *json.Decoder) map[string]any {
		var m map[string]any
		if err := d.Decode(&m); err != nil {
			t.Fatalf("read: %v", err)
		}
		return m
	}

	res, d := open()
	got := make(chan map[string]any)
	go func() { got <- next(d) }()
	select {
	case m := <-got:
		if m["sentence"] != "It is bus 858." {
			t.Fatalf("first line %v", m)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("first sentence held back until the answer was complete")
	}
	release <- struct{}{}
	if m := next(d); m["done"] != true || m["answer"] != "It is bus 858. It is stopping now." || m["rest"] != "It is stopping now." {
		t.Fatalf("last line %v", m)
	}
	res.Body.Close()

	// dropped mid-answer: what was said stays said, then an error line (the box says it lost the answer)
	fail = true
	res, d = open()
	defer res.Body.Close()
	if m := next(d); m["sentence"] != "It is bus 858." {
		t.Fatalf("first line %v", m)
	}
	release <- struct{}{}
	if m := next(d); m["error"] != "opinion_failed" || m["done"] != nil {
		t.Fatalf("error line %v", m)
	}
}
