package server

import (
	"errors"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/asirive/cortex/gateway/internal/lta"
)

// Live bus arrivals for the box, on the device (mTLS) listener only: a claimed, unrevoked device asks
// GET /device/bus-arrivals?stop=59009[&service=858] and gets
//
//	{"stop":"59009","stale":false,"age_s":4,"services":[{"service":"858","minutes":[2,11,20],"monitored":[true,false,false]}]}
//
// The LTA key stays here (lta.Client). A device may ask arrivalsPerMin times a minute: enough for a
// person checking buses, too few to scrape every stop through us.
const arrivalsPerMin = 30

type rateWindow struct {
	mu   sync.Mutex
	hits map[string][]time.Time
}

func (rw *rateWindow) allow(id string, now time.Time, perMin int) bool {
	rw.mu.Lock()
	defer rw.mu.Unlock()
	if rw.hits == nil {
		rw.hits = map[string][]time.Time{}
	}
	keep := rw.hits[id][:0]
	for _, t := range rw.hits[id] {
		if now.Sub(t) < time.Minute {
			keep = append(keep, t)
		}
	}
	if len(keep) >= perMin {
		rw.hits[id] = keep
		return false
	}
	rw.hits[id] = append(keep, now)
	return true
}

func (s *Server) busArrivals(w http.ResponseWriter, r *http.Request) {
	id := ""
	if r.TLS != nil && len(r.TLS.PeerCertificates) > 0 {
		id = r.TLS.PeerCertificates[0].Subject.CommonName
	}
	if err := s.checkCert(r, id); err != nil {
		writeErr(w, http.StatusUnauthorized, "unauthorized", "Certificate not accepted.")
		return
	}
	now := time.Now()
	if !s.arrivalsRate.allow(id, now, arrivalsPerMin) {
		writeErr(w, http.StatusTooManyRequests, "rate_limited", "Too many arrival requests; try again in a minute.")
		return
	}
	stop := r.URL.Query().Get("stop")
	want := strings.ToUpper(strings.TrimSpace(r.URL.Query().Get("service")))
	if want != "" && !lta.ValidService(want) {
		writeErr(w, http.StatusBadRequest, "bad_service", "Bad bus service number.")
		return
	}
	svcs, stale, fetched, err := s.Arrivals.Arrivals(r.Context(), stop)
	switch {
	case errors.Is(err, lta.ErrNoKey):
		writeErr(w, http.StatusServiceUnavailable, "arrivals_unavailable", "Live arrivals are not set up on this gateway.")
		return
	case errors.Is(err, lta.ErrBadStop):
		writeErr(w, http.StatusBadRequest, "bad_stop", "Bus stop codes are 5 digits.")
		return
	case err != nil:
		writeErr(w, http.StatusBadGateway, "arrivals_failed", "LTA did not answer.")
		return
	}
	out := make([]map[string]any, 0, len(svcs))
	for _, sv := range svcs {
		if want != "" && strings.ToUpper(sv.No) != want {
			continue
		}
		mon := make([]bool, 0, len(sv.Bus))
		for _, b := range sv.Bus {
			mon = append(mon, b.Monitored)
		}
		out = append(out, map[string]any{"service": sv.No, "minutes": lta.Minutes(sv, now), "monitored": mon})
	}
	writeJSON(w, map[string]any{"stop": stop, "stale": stale, "age_s": int(now.Sub(fetched).Seconds()), "services": out})
}
