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

	"github.com/asirive/cortex/gateway/internal/fleet"
	"github.com/asirive/cortex/gateway/internal/gemini"
	"github.com/asirive/cortex/gateway/internal/pki"
)

func TestSecondOpinionOnTheDeviceListener(t *testing.T) {
	var upstream atomic.Int32
	gm := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upstream.Add(1)
		if r.Header.Get("x-goog-api-key") != "srv-gemini" {
			w.WriteHeader(403)
			return
		}
		json.NewEncoder(w).Encode(map[string]any{"candidates": []any{map[string]any{"content": map[string]any{
			"parts": []any{map[string]any{"text": "It is bus 858, right in front of you."}}}}}})
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
	good := map[string]any{"question": "which bus is this", "image_jpeg": img}

	if code, _ := ask(c, dev.URL, good); code != 503 { // no key: says so, never calls out
		t.Fatalf("no key: %d", code)
	}
	if upstream.Load() != 0 {
		t.Fatal("called Gemini without a key")
	}
	s.Gemini = gemini.New("srv-gemini")
	s.Gemini.Base = gm.URL

	code, m := ask(c, dev.URL, good)
	if code != 200 || m["answer"] != "It is bus 858, right in front of you." {
		t.Fatalf("answer: %d %v", code, m)
	}
	if code, _ := ask(c, dev.URL, map[string]any{"question": "what time is it"}); code != 200 { // no image is fine
		t.Fatalf("no image: %d", code)
	}
	for _, bad := range []any{map[string]any{"question": ""}, map[string]any{"question": "q", "image_jpeg": "@@@"},
		map[string]any{"question": "q", "image_jpeg": base64.StdEncoding.EncodeToString([]byte("PNG..."))},
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
	s.Gemini.Base = "http://127.0.0.1:1"
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
