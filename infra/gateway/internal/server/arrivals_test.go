package server

import (
	"crypto/tls"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	"github.com/asirive/cortex/gateway/internal/fleet"
	"github.com/asirive/cortex/gateway/internal/lta"
	"github.com/asirive/cortex/gateway/internal/pki"
)

func TestBusArrivalsOnTheDeviceListener(t *testing.T) {
	var upstream atomic.Int32
	dm := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upstream.Add(1)
		if r.Header.Get("AccountKey") != "srv-key" {
			w.WriteHeader(401)
			return
		}
		at := time.Now().Add(3*time.Minute + 30*time.Second).Format(time.RFC3339)
		json.NewEncoder(w).Encode(map[string]any{"Services": []map[string]any{
			{"ServiceNo": "858", "NextBus": map[string]any{"EstimatedArrival": at, "Monitored": 1}},
			{"ServiceNo": "969", "NextBus": map[string]any{"EstimatedArrival": at, "Monitored": 0}},
		}})
	}))
	defer dm.Close()

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
	acct := login(t, s, "lta@example.com")
	a := claimDevice(t, s, api.URL, acct)
	c := &http.Client{Transport: &http.Transport{TLSClientConfig: a.tlsCfg(roots)}}

	get := func(cl *http.Client, base, q string) (int, map[string]any) {
		res, err := cl.Get(base + "/device/bus-arrivals" + q)
		if err != nil {
			return 0, nil
		}
		defer res.Body.Close()
		var m map[string]any
		json.NewDecoder(res.Body).Decode(&m)
		return res.StatusCode, m
	}

	// no key configured: says so, never calls out
	if code, _ := get(c, dev.URL, "?stop=59009"); code != 503 {
		t.Fatalf("no key: %d", code)
	}
	s.Arrivals = lta.New("srv-key")
	s.Arrivals.Base = dm.URL

	code, m := get(c, dev.URL, "?stop=59009&service=858")
	if code != 200 {
		t.Fatalf("arrivals: %d %v", code, m)
	}
	svcs := m["services"].([]any)
	if len(svcs) != 1 || svcs[0].(map[string]any)["service"] != "858" || m["stale"] != false {
		t.Fatalf("%v", m)
	}
	if mins := svcs[0].(map[string]any)["minutes"].([]any); len(mins) != 1 || mins[0].(float64) != 3 {
		t.Fatalf("minutes %v", mins)
	}
	if code, m := get(c, dev.URL, "?stop=59009"); code != 200 || len(m["services"].([]any)) != 2 {
		t.Fatalf("all services: %d %v", code, m)
	}
	if upstream.Load() != 1 {
		t.Fatalf("upstream %d, want 1 (cached)", upstream.Load())
	}
	for _, q := range []string{"?stop=5900", "?stop=59009;rm", "", "?stop=59009&service=<x>"} {
		if code, _ := get(c, dev.URL, q); code != 400 {
			t.Fatalf("%q: %d", q, code)
		}
	}
	// no client certificate: refused at the handshake; the public listener does not serve it
	if code, _ := get(&http.Client{Transport: &http.Transport{TLSClientConfig: &tls.Config{RootCAs: roots}}}, dev.URL, "?stop=59009"); code != 0 {
		t.Fatalf("served without a certificate: %d", code)
	}
	if code, _ := get(http.DefaultClient, api.URL, "?stop=59009"); code == 200 {
		t.Fatal("arrivals on the public listener")
	}
	// a device can't scrape every stop through us
	limited := false
	for i := 0; i < arrivalsPerMin+1; i++ {
		if code, _ := get(c, dev.URL, "?stop=59009"); code == 429 {
			limited = true
			break
		}
	}
	if !limited {
		t.Fatal("no rate limit")
	}
	// a revoked device is cut off
	post(t, api.URL+"/api/registrations/"+a.id+"/revoke", "boot", nil)
	c.CloseIdleConnections()
	if code, _ := get(c, dev.URL, "?stop=59009"); code == 200 {
		t.Fatal("revoked device still gets arrivals")
	}
}

func TestRateWindowSlides(t *testing.T) {
	var rw rateWindow
	t0 := time.Unix(1000, 0)
	for i := 0; i < 3; i++ {
		if !rw.allow("d", t0, 3) {
			t.Fatal("refused early")
		}
	}
	if rw.allow("d", t0.Add(30*time.Second), 3) || !rw.allow("e", t0, 3) {
		t.Fatal("window per device")
	}
	if !rw.allow("d", t0.Add(61*time.Second), 3) {
		t.Fatal("window did not slide")
	}
}
