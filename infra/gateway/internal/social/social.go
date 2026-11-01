// Package social holds the companion features: invites and per-companion grants,
// the owner's location (30-day TTL, no media ever) and call signaling.
//
// A companion sees only what the owner granted, and the owner or the companion
// can end the link at any time, which also ends open calls and stops location reads.
package social

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"math"
	"strings"
	"sync"
	"time"
)

var (
	ErrNotFound  = errors.New("not found")
	ErrForbidden = errors.New("not allowed")
	ErrInvalid   = errors.New("invalid input")
	ErrBadCode   = errors.New("invite code invalid or expired")
	ErrRate      = errors.New("too many attempts")
	ErrBusy      = errors.New("already in a call")
)

const (
	InviteTTL     = 48 * time.Hour
	LocationTTL   = 30 * 24 * time.Hour
	HistoryEvery  = 5 * time.Minute
	HistoryMax    = 9000
	RingTimeout   = 60 * time.Second
	CallRecordTTL = 30 * 24 * time.Hour
	MaxSDP        = 16 << 10
	MaxICE        = 64
)

const alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

func rnd(n int) []byte { b := make([]byte, n); rand.Read(b); return b }
func code(n int) string {
	out := make([]byte, n)
	for i, b := range rnd(n) {
		out[i] = alphabet[int(b)%len(alphabet)]
	}
	return string(out)
}
func hid(prefix string) string { return prefix + hex.EncodeToString(rnd(8)) }
func sum(s string) string      { h := sha256.Sum256([]byte(s)); return hex.EncodeToString(h[:]) }

type Link struct {
	ID          string `json:"id"`
	Owner       string `json:"owner"`
	Companion   string `json:"companion,omitempty"` // empty until the invite is accepted
	Label       string `json:"label"`               // what the owner calls them
	State       string `json:"state"`               // pending | active | revoked
	GrantLoc    bool   `json:"grant_location"`
	GrantCall   bool   `json:"grant_call"`
	InviteHash  string `json:"invite_hash,omitempty"`
	InviteUntil int64  `json:"invite_until_ms,omitempty"`
	CreatedMs   int64  `json:"created_ms"`
}

type Point struct {
	Lat float64 `json:"lat"`
	Lon float64 `json:"lon"`
	Acc float64 `json:"accuracy_m"`
	Ts  int64   `json:"ts_ms"`
}

type Call struct {
	ID      string   `json:"id"`
	From    string   `json:"from"`
	To      string   `json:"to"`
	State   string   `json:"state"` // ringing | active | ended | declined | missed
	Offer   string   `json:"offer,omitempty"`
	Answer  string   `json:"answer,omitempty"`
	ICEFrom []string `json:"ice_from,omitempty"`
	ICETo   []string `json:"ice_to,omitempty"`
	Created int64    `json:"created_ms"`
	Ended   int64    `json:"ended_ms,omitempty"`
}

type Store struct {
	mu      sync.Mutex
	links   map[string]*Link
	latest  map[string]Point
	history map[string][]Point
	calls   map[string]*Call
	fails   map[string][]time.Time
	push    map[string][]PushToken
}

type PushToken struct {
	Platform string `json:"platform"` // ios | android
	Token    string `json:"token"`
}

func New() *Store {
	return &Store{links: map[string]*Link{}, latest: map[string]Point{}, history: map[string][]Point{}, calls: map[string]*Call{}, fails: map[string][]time.Time{}, push: map[string][]PushToken{}}
}

// ---- companions ----

func (s *Store) Invite(owner, label string, now time.Time) (*Link, string, error) {
	label = strings.TrimSpace(label)
	if n := len([]rune(label)); n == 0 || n > 60 {
		return nil, "", ErrInvalid
	}
	c := code(8)
	s.mu.Lock()
	defer s.mu.Unlock()
	pending := 0
	for _, l := range s.links {
		if l.Owner == owner && l.State == "pending" && now.UnixMilli() < l.InviteUntil {
			pending++
		}
	}
	if pending >= 5 {
		return nil, "", ErrRate
	}
	l := &Link{ID: hid("c_"), Owner: owner, Label: label, State: "pending", InviteHash: sum(c), InviteUntil: now.Add(InviteTTL).UnixMilli(), CreatedMs: now.UnixMilli()}
	s.links[l.ID] = l
	cp := *l
	return &cp, c[:4] + "-" + c[4:], nil
}

func (s *Store) Accept(me, inviteCode string, now time.Time) (*Link, error) {
	c := strings.ToUpper(strings.NewReplacer("-", "", " ", "").Replace(inviteCode))
	s.mu.Lock()
	defer s.mu.Unlock()
	f := s.fails[me][:0:0]
	for _, t := range s.fails[me] {
		if now.Sub(t) < time.Minute {
			f = append(f, t)
		}
	}
	s.fails[me] = f
	if len(f) >= 5 {
		return nil, ErrRate
	}
	h := sum(c)
	for _, l := range s.links {
		if l.State == "pending" && l.InviteHash == h && now.UnixMilli() <= l.InviteUntil {
			if l.Owner == me {
				return nil, ErrInvalid
			}
			for _, o := range s.links {
				if o.Owner == l.Owner && o.Companion == me && o.State == "active" {
					return nil, ErrInvalid
				}
			}
			l.Companion, l.State, l.InviteHash = me, "active", ""
			cp := *l
			return &cp, nil
		}
	}
	s.fails[me] = append(s.fails[me], now)
	return nil, ErrBadCode
}

// Links returns links the account owns and links where it is the companion.
func (s *Store) Links(me string, now time.Time) (owned, watching []Link) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, l := range s.links {
		switch {
		case l.Owner == me && (l.State == "active" || (l.State == "pending" && now.UnixMilli() < l.InviteUntil)):
			c := *l
			c.InviteHash = ""
			owned = append(owned, c)
		case l.Companion == me && l.State == "active":
			c := *l
			c.InviteHash = ""
			watching = append(watching, c)
		}
	}
	return
}

func (s *Store) SetGrants(owner, id string, loc, call bool) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	l := s.links[id]
	if l == nil || l.Owner != owner || l.State != "active" {
		return ErrNotFound
	}
	l.GrantLoc, l.GrantCall = loc, call
	if !call {
		s.endLinkCalls(l, time.Now())
	}
	return nil
}

// Revoke ends a link; either side may do it.
func (s *Store) Revoke(me, id string, now time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	l := s.links[id]
	if l == nil || (l.Owner != me && l.Companion != me) || l.State == "revoked" {
		return ErrNotFound
	}
	l.State, l.GrantLoc, l.GrantCall, l.InviteHash = "revoked", false, false, ""
	s.endLinkCalls(l, now)
	return nil
}

func (s *Store) endLinkCalls(l *Link, now time.Time) {
	for _, c := range s.calls {
		if (c.State == "ringing" || c.State == "active") && ((c.From == l.Owner && c.To == l.Companion) || (c.From == l.Companion && c.To == l.Owner)) {
			end(c, "ended", now)
		}
	}
}

func end(c *Call, state string, now time.Time) {
	c.State, c.Ended = state, now.UnixMilli()
	c.Offer, c.Answer, c.ICEFrom, c.ICETo = "", "", nil, nil // signalling data is not kept
}

// activeLink finds an active link between two accounts in either direction.
func (s *Store) activeLink(a, b string) *Link {
	for _, l := range s.links {
		if l.State == "active" && ((l.Owner == a && l.Companion == b) || (l.Owner == b && l.Companion == a)) {
			return l
		}
	}
	return nil
}

// ---- location ----

func (s *Store) PutLocation(owner string, p Point, now time.Time) error {
	if math.IsNaN(p.Lat) || math.IsNaN(p.Lon) || p.Lat < -90 || p.Lat > 90 || p.Lon < -180 || p.Lon > 180 || p.Acc < 0 || p.Acc > 100000 {
		return ErrInvalid
	}
	p.Ts = now.UnixMilli() // trust our clock, not the phone's
	s.mu.Lock()
	defer s.mu.Unlock()
	s.latest[owner] = p
	h := s.history[owner]
	if len(h) == 0 || now.Sub(time.UnixMilli(h[len(h)-1].Ts)) >= HistoryEvery {
		h = append(h, p)
		if len(h) > HistoryMax {
			h = h[len(h)-HistoryMax:]
		}
		s.history[owner] = h
	}
	return nil
}

func (s *Store) ClearLocation(owner string) {
	s.mu.Lock()
	delete(s.latest, owner)
	delete(s.history, owner)
	s.mu.Unlock()
}

// CompanionLocation returns the owner's latest point only if me holds an active location grant.
func (s *Store) CompanionLocation(me, owner string, now time.Time) (Point, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	ok := false
	for _, l := range s.links {
		if l.Owner == owner && l.Companion == me && l.State == "active" && l.GrantLoc {
			ok = true
		}
	}
	p, have := s.latest[owner]
	if !ok || !have || now.Sub(time.UnixMilli(p.Ts)) > LocationTTL {
		return Point{}, ErrNotFound // same answer for "no grant" and "no data"
	}
	return p, nil
}

// Sweep drops expired data: old location, stale invites, old call records.
func (s *Store) Sweep(now time.Time) {
	s.mu.Lock()
	defer s.mu.Unlock()
	cut := now.Add(-LocationTTL).UnixMilli()
	for o, h := range s.history {
		i := 0
		for i < len(h) && h[i].Ts < cut {
			i++
		}
		if i == len(h) {
			delete(s.history, o)
		} else {
			s.history[o] = h[i:]
		}
	}
	for o, p := range s.latest {
		if p.Ts < cut {
			delete(s.latest, o)
		}
	}
	for id, l := range s.links {
		if (l.State == "pending" && now.UnixMilli() > l.InviteUntil) || (l.State == "revoked" && now.UnixMilli()-l.CreatedMs > int64(CallRecordTTL/time.Millisecond)) {
			delete(s.links, id)
		}
	}
	for id, c := range s.calls {
		s.expire(c, now)
		if c.State != "ringing" && c.State != "active" && now.UnixMilli()-c.Created > int64(CallRecordTTL/time.Millisecond) {
			delete(s.calls, id)
		}
	}
}

// ---- calls ----

func (s *Store) expire(c *Call, now time.Time) {
	if c.State == "ringing" && now.UnixMilli()-c.Created > int64(RingTimeout/time.Millisecond) {
		end(c, "missed", now)
	}
}

func (s *Store) StartCall(from, to, offer string, now time.Time) (*Call, error) {
	if offer == "" || len(offer) > MaxSDP {
		return nil, ErrInvalid
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	l := s.activeLink(from, to)
	if l == nil || !l.GrantCall {
		return nil, ErrForbidden
	}
	for _, c := range s.calls {
		s.expire(c, now)
		if (c.State == "ringing" || c.State == "active") && (c.From == from || c.To == from || c.From == to || c.To == to) {
			return nil, ErrBusy
		}
	}
	c := &Call{ID: hid("call_"), From: from, To: to, State: "ringing", Offer: offer, Created: now.UnixMilli()}
	s.calls[c.ID] = c
	cp := *c
	return &cp, nil
}

func (s *Store) Inbox(me string, now time.Time) []Call {
	s.mu.Lock()
	defer s.mu.Unlock()
	var out []Call
	for _, c := range s.calls {
		s.expire(c, now)
		if c.To == me && c.State == "ringing" {
			out = append(out, *c)
		}
	}
	return out
}

func (s *Store) part(me, id string, now time.Time) (*Call, error) {
	c := s.calls[id]
	if c == nil || (c.From != me && c.To != me) {
		return nil, ErrNotFound
	}
	s.expire(c, now)
	return c, nil
}

func (s *Store) GetCall(me, id string, now time.Time) (Call, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	c, err := s.part(me, id, now)
	if err != nil {
		return Call{}, err
	}
	return *c, nil
}

func (s *Store) Answer(me, id, sdp string, now time.Time) error {
	if sdp == "" || len(sdp) > MaxSDP {
		return ErrInvalid
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	c, err := s.part(me, id, now)
	if err != nil || c.To != me || c.State != "ringing" {
		return ErrNotFound
	}
	if l := s.activeLink(c.From, c.To); l == nil || !l.GrantCall {
		end(c, "ended", now)
		return ErrForbidden
	}
	c.Answer, c.State = sdp, "active"
	return nil
}

func (s *Store) AddICE(me, id, cand string, now time.Time) error {
	if cand == "" || len(cand) > 2048 {
		return ErrInvalid
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	c, err := s.part(me, id, now)
	if err != nil || (c.State != "ringing" && c.State != "active") {
		return ErrNotFound
	}
	list := &c.ICETo
	if c.From == me {
		list = &c.ICEFrom
	}
	if len(*list) >= MaxICE {
		return ErrRate
	}
	*list = append(*list, cand)
	return nil
}

// Finish ends a call. The callee declining a ringing call is recorded as declined.
func (s *Store) Finish(me, id string, now time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	c, err := s.part(me, id, now)
	if err != nil || (c.State != "ringing" && c.State != "active") {
		return ErrNotFound
	}
	if c.State == "ringing" && c.To == me {
		end(c, "declined", now)
	} else {
		end(c, "ended", now)
	}
	return nil
}

// ---- deletion and persistence ----

// DeleteAccount removes every trace of an account: links, location, call records.
func (s *Store) DeleteAccount(id string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for k, l := range s.links {
		if l.Owner == id || l.Companion == id {
			delete(s.links, k)
		}
	}
	for k, c := range s.calls {
		if c.From == id || c.To == id {
			delete(s.calls, k)
		}
	}
	delete(s.latest, id)
	delete(s.history, id)
	delete(s.push, id)
}

type snap struct {
	Links   map[string]*Link       `json:"links"`
	Latest  map[string]Point       `json:"latest"`
	History map[string][]Point     `json:"history"`
	Calls   map[string]*Call       `json:"calls"`
	Push    map[string][]PushToken `json:"push"`
}

func (s *Store) Snapshot() ([]byte, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return json.Marshal(snap{s.links, s.latest, s.history, s.calls, s.push})
}

func (s *Store) Restore(b []byte) error {
	var o snap
	if err := json.Unmarshal(b, &o); err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if o.Links != nil {
		s.links = o.Links
	}
	if o.Latest != nil {
		s.latest = o.Latest
	}
	if o.History != nil {
		s.history = o.History
	}
	if o.Calls != nil {
		s.calls = o.Calls
	}
	if o.Push != nil {
		s.push = o.Push
	}
	return nil
}

// ---- push tokens ----

// SetPush registers a device token for an account (max 5; a token belongs to one account only).
func (s *Store) SetPush(acct, platform, token string) error {
	if (platform != "ios" && platform != "android") || len(token) < 8 || len(token) > 512 {
		return ErrInvalid
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	for a, list := range s.push { // a phone that changes hands moves with the latest sign-in
		kept := list[:0]
		for _, t := range list {
			if t.Token != token {
				kept = append(kept, t)
			}
		}
		s.push[a] = kept
	}
	l := append(s.push[acct], PushToken{platform, token})
	if len(l) > 5 {
		l = l[len(l)-5:]
	}
	s.push[acct] = l
	return nil
}

func (s *Store) ClearPush(acct, token string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	kept := s.push[acct][:0]
	for _, t := range s.push[acct] {
		if token != "" && t.Token != token {
			kept = append(kept, t)
		}
	}
	s.push[acct] = kept
}

func (s *Store) PushTokens(acct string) []PushToken {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]PushToken(nil), s.push[acct]...)
}
