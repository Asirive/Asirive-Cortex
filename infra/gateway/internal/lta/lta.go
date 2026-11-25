// Package lta is the gateway's live bus-arrivals proxy: the box asks the gateway, the gateway asks LTA
// DataMall's BusArrival (v3) with the server's AccountKey. The key never leaves the server.
//
// One stop is fetched at most once per TTL (20 s) however many devices ask, and concurrent askers of the
// same stop share one upstream request. When DataMall fails, the last good answer is served, marked
// stale, for up to MaxStale; after that the error goes to the box, which falls back to headways.
package lta

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	DefaultBase = "https://datamall2.mytransport.sg/ltaodataservice/v3/BusArrival"
	TTL         = 20 * time.Second
	MaxStale    = 2 * time.Minute
	maxEntries  = 4096 // Singapore has ~5,200 stops; old entries are dropped beyond this
)

var (
	ErrNoKey   = errors.New("live arrivals not configured")
	ErrBadStop = errors.New("bad bus stop code")
	stopRe     = regexp.MustCompile(`^[0-9]{5}$`)
	serviceRe  = regexp.MustCompile(`^[0-9A-Za-z]{1,5}$`)
)

// Bus is one upcoming bus as DataMall reports it.
type Bus struct {
	At        time.Time
	Monitored bool // true = from the bus's GPS; false = from the schedule
	Load      string
	Feature   string
}

// Service is one bus service at the stop, its next buses in order.
type Service struct {
	No  string
	Bus []Bus
}

type entry struct {
	services []Service
	fetched  time.Time
	err      error
	done     chan struct{} // closed when the fetch in flight finishes
}

type Client struct {
	Key  string
	Base string
	HTTP *http.Client
	Now  func() time.Time

	mu    sync.Mutex
	cache map[string]*entry
}

func New(key string) *Client {
	return &Client{Key: strings.TrimSpace(key), Base: DefaultBase, HTTP: &http.Client{Timeout: 8 * time.Second},
		Now: time.Now, cache: map[string]*entry{}}
}

// Arrivals returns the services at a stop, whether the answer is stale, and when it was fetched.
func (c *Client) Arrivals(ctx context.Context, stop string) ([]Service, bool, time.Time, error) {
	if c == nil || c.Key == "" {
		return nil, false, time.Time{}, ErrNoKey
	}
	if !stopRe.MatchString(stop) {
		return nil, false, time.Time{}, ErrBadStop
	}
	now := c.Now()
	c.mu.Lock()
	e := c.cache[stop]
	if e != nil {
		select {
		case <-e.done: // finished: fresh enough?
			if e.err == nil && now.Sub(e.fetched) < TTL {
				c.mu.Unlock()
				return e.services, false, e.fetched, nil
			}
		default: // a fetch for this stop is running: wait for it
			c.mu.Unlock()
			select {
			case <-e.done:
			case <-ctx.Done():
				return nil, false, time.Time{}, ctx.Err()
			}
			return c.result(stop, e, now)
		}
	}
	prev := e
	ne := &entry{done: make(chan struct{})}
	c.cache[stop] = ne
	if len(c.cache) > maxEntries {
		c.evict(now)
	}
	c.mu.Unlock()

	svcs, err := c.fetch(ctx, stop)
	c.mu.Lock()
	if err != nil && prev != nil && prev.err == nil && now.Sub(prev.fetched) < MaxStale {
		ne.services, ne.fetched, ne.err = prev.services, prev.fetched, nil // keep the last good answer
		c.mu.Unlock()
		close(ne.done)
		return ne.services, true, ne.fetched, nil
	}
	ne.services, ne.fetched, ne.err = svcs, now, err
	c.mu.Unlock()
	close(ne.done)
	return c.result(stop, ne, now)
}

func (c *Client) result(stop string, e *entry, now time.Time) ([]Service, bool, time.Time, error) {
	if e.err != nil {
		return nil, false, time.Time{}, e.err
	}
	return e.services, now.Sub(e.fetched) >= TTL, e.fetched, nil
}

func (c *Client) evict(now time.Time) {
	for k, e := range c.cache {
		select {
		case <-e.done:
			if now.Sub(e.fetched) >= MaxStale || e.err != nil {
				delete(c.cache, k)
			}
		default:
		}
	}
}

type upstream struct {
	Services []struct {
		ServiceNo string
		NextBus   upBus
		NextBus2  upBus
		NextBus3  upBus
	}
}

type upBus struct {
	EstimatedArrival string
	Monitored        int
	Load             string
	Feature          string
}

func (c *Client) fetch(ctx context.Context, stop string) ([]Service, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.Base+"?BusStopCode="+stop, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("AccountKey", c.Key)
	req.Header.Set("accept", "application/json")
	res, err := c.HTTP.Do(req)
	if err != nil {
		return nil, errors.New("datamall unreachable") // never wrap: the error must not carry the request
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("datamall HTTP %d", res.StatusCode)
	}
	var u upstream
	if err := json.NewDecoder(io.LimitReader(res.Body, 1<<20)).Decode(&u); err != nil {
		return nil, errors.New("datamall answer not JSON")
	}
	out := make([]Service, 0, len(u.Services))
	for _, s := range u.Services {
		if !serviceRe.MatchString(s.ServiceNo) {
			continue
		}
		sv := Service{No: s.ServiceNo}
		for _, b := range []upBus{s.NextBus, s.NextBus2, s.NextBus3} {
			t, err := time.Parse(time.RFC3339, b.EstimatedArrival)
			if err != nil {
				continue // "" = no bus
			}
			sv.Bus = append(sv.Bus, Bus{At: t, Monitored: b.Monitored == 1, Load: b.Load, Feature: b.Feature})
		}
		out = append(out, sv)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].No < out[j].No })
	return out, nil
}

// Minutes is the box's view of a service: whole minutes from now to each bus (0 = arriving), soonest first.
func Minutes(s Service, now time.Time) []int {
	out := make([]int, 0, len(s.Bus))
	for _, b := range s.Bus {
		m := int(b.At.Sub(now) / time.Minute)
		if m < 0 {
			m = 0
		}
		out = append(out, m)
	}
	return out
}

// ValidService says whether a service number is worth filtering on.
func ValidService(s string) bool { return serviceRe.MatchString(s) }
