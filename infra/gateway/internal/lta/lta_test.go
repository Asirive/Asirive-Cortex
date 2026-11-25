package lta

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

var t0 = time.Date(2026, 11, 26, 9, 0, 0, 0, time.FixedZone("SGT", 8*3600))

type fake struct {
	srv   *httptest.Server
	calls atomic.Int32
	fail  atomic.Bool
	slow  chan struct{}
}

func newFake(t *testing.T) *fake {
	f := &fake{}
	f.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.calls.Add(1)
		if f.slow != nil {
			<-f.slow
		}
		if r.Header.Get("AccountKey") != "secret-key" {
			w.WriteHeader(401)
			return
		}
		if f.fail.Load() {
			w.WriteHeader(500)
			return
		}
		at := func(m int) string { return t0.Add(time.Duration(m) * time.Minute).Format(time.RFC3339) }
		json.NewEncoder(w).Encode(map[string]any{
			"BusStopCode": r.URL.Query().Get("BusStopCode"),
			"Services": []map[string]any{
				{"ServiceNo": "969", "NextBus": map[string]any{"EstimatedArrival": at(7), "Monitored": 1}, "NextBus2": map[string]any{"EstimatedArrival": ""}},
				{"ServiceNo": "858", "NextBus": map[string]any{"EstimatedArrival": at(2), "Monitored": 1, "Load": "SEA"},
					"NextBus2": map[string]any{"EstimatedArrival": at(11), "Monitored": 0}, "NextBus3": map[string]any{"EstimatedArrival": at(20)}},
				{"ServiceNo": "<script>", "NextBus": map[string]any{"EstimatedArrival": at(1)}},
			},
		})
	}))
	t.Cleanup(f.srv.Close)
	return f
}

func client(f *fake, now *time.Time) *Client {
	c := New("secret-key")
	c.Base = f.srv.URL
	c.Now = func() time.Time { return *now }
	return c
}

func TestParsesSortsAndDropsJunk(t *testing.T) {
	f := newFake(t)
	now := t0
	c := client(f, &now)
	svcs, stale, _, err := c.Arrivals(context.Background(), "59009")
	if err != nil || stale {
		t.Fatal(err, stale)
	}
	if len(svcs) != 2 || svcs[0].No != "858" || svcs[1].No != "969" {
		t.Fatalf("%+v", svcs)
	}
	if got := Minutes(svcs[0], now); len(got) != 3 || got[0] != 2 || got[1] != 11 || got[2] != 20 {
		t.Fatal(got)
	}
	if !svcs[0].Bus[0].Monitored || svcs[0].Bus[1].Monitored || svcs[0].Bus[0].Load != "SEA" {
		t.Fatalf("%+v", svcs[0].Bus)
	}
	if got := Minutes(svcs[1], now); len(got) != 1 || got[0] != 7 {
		t.Fatal(got)
	}
}

func TestCachedForTTLThenRefetched(t *testing.T) {
	f := newFake(t)
	now := t0
	c := client(f, &now)
	for i := 0; i < 5; i++ {
		c.Arrivals(context.Background(), "59009")
	}
	now = now.Add(TTL - time.Second)
	c.Arrivals(context.Background(), "59009")
	if f.calls.Load() != 1 {
		t.Fatalf("upstream calls %d, want 1", f.calls.Load())
	}
	now = now.Add(2 * time.Second)
	c.Arrivals(context.Background(), "59009")
	c.Arrivals(context.Background(), "59010") // another stop is its own entry
	if f.calls.Load() != 3 {
		t.Fatalf("upstream calls %d, want 3", f.calls.Load())
	}
}

func TestConcurrentAskersShareOneFetch(t *testing.T) {
	f := newFake(t)
	f.slow = make(chan struct{})
	now := t0
	c := client(f, &now)
	var wg sync.WaitGroup
	errs := make(chan error, 20)
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			s, _, _, err := c.Arrivals(context.Background(), "59009")
			if err == nil && len(s) != 2 {
				err = context.Canceled
			}
			errs <- err
		}()
	}
	time.Sleep(50 * time.Millisecond)
	close(f.slow)
	wg.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
	if f.calls.Load() != 1 {
		t.Fatalf("upstream calls %d, want 1", f.calls.Load())
	}
}

func TestStaleOnFailureThenError(t *testing.T) {
	f := newFake(t)
	now := t0
	c := client(f, &now)
	c.Arrivals(context.Background(), "59009")
	f.fail.Store(true)
	now = now.Add(TTL + time.Second)
	s, stale, fetched, err := c.Arrivals(context.Background(), "59009")
	if err != nil || !stale || len(s) != 2 || !fetched.Equal(t0) {
		t.Fatal(err, stale, len(s), fetched)
	}
	now = t0.Add(MaxStale + time.Second)
	if _, _, _, err := c.Arrivals(context.Background(), "59009"); err == nil {
		t.Fatal("served data older than MaxStale")
	}
	f.fail.Store(false) // recovers
	now = now.Add(time.Second)
	if _, stale, _, err := c.Arrivals(context.Background(), "59009"); err != nil || stale {
		t.Fatal(err, stale)
	}
}

func TestRefusalsAndKeyNeverInErrors(t *testing.T) {
	f := newFake(t)
	now := t0
	c := client(f, &now)
	for _, bad := range []string{"", "5900", "590091", "59a09", "59009&x=1", "../59"} {
		if _, _, _, err := c.Arrivals(context.Background(), bad); err != ErrBadStop {
			t.Fatalf("%q: %v", bad, err)
		}
	}
	if f.calls.Load() != 0 {
		t.Fatal("bad stops reached DataMall")
	}
	var nilc *Client
	if _, _, _, err := nilc.Arrivals(context.Background(), "59009"); err != ErrNoKey {
		t.Fatal(err)
	}
	if _, _, _, err := New("  ").Arrivals(context.Background(), "59009"); err != ErrNoKey {
		t.Fatal(err)
	}
	wrong := client(f, &now)
	wrong.Key = "wrong-key"
	_, _, _, err := wrong.Arrivals(context.Background(), "59009")
	if err == nil || strings.Contains(err.Error(), "wrong-key") || !strings.Contains(err.Error(), "401") {
		t.Fatal(err)
	}
	down := New("secret-key")
	down.Base = "http://127.0.0.1:1"
	_, _, _, err = down.Arrivals(context.Background(), "59009")
	if err == nil || strings.Contains(err.Error(), "secret-key") || strings.Contains(err.Error(), "127.0.0.1") {
		t.Fatal(err)
	}
}
