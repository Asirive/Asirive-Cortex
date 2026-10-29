package server

import (
	"fmt"
	"log"
	"sort"
	"strings"
	"time"

	"github.com/asirive/cortex/gateway/internal/registry"
)

// Alerting emails the ops team when a live device needs attention for longer than
// AlertAfter (so brief reconnects stay quiet), repeats every AlertRepeat while it
// stays unresolved, and sends one all-clear. Auto-halted releases alert immediately.
type alertState struct {
	since time.Time
	last  time.Time // last email, zero = not yet sent
	text  string
}

const (
	AlertAfter  = 3 * time.Minute
	AlertRepeat = 6 * time.Hour
)

// alertTick is called periodically (and directly by tests).
func (s *Server) alertTick(now time.Time) {
	if len(s.AlertTo) == 0 {
		return
	}
	cur := map[string]string{}
	for _, d := range s.merged() {
		if d.RegState == string(registry.Pending) || d.RegState == string(registry.Revoked) || d.Attention == "" {
			continue
		}
		label := d.Label
		if label == "" {
			label = d.ID
		}
		cur[d.ID] = fmt.Sprintf("%s (%s, %s): %s", label, d.ID, d.Tier, d.Attention)
	}
	s.mu.Lock()
	if s.alerts == nil {
		s.alerts = map[string]*alertState{}
	}
	var fire, clear []string
	for id, text := range cur {
		a := s.alerts[id]
		if a == nil || a.text != text {
			a = &alertState{since: now, text: text, last: time.Time{}}
			if old := s.alerts[id]; old != nil {
				a.since, a.last = old.since, old.last // same device, changed detail: keep the clock
			}
			s.alerts[id] = a
		}
		if now.Sub(a.since) >= AlertAfter && (a.last.IsZero() || now.Sub(a.last) >= AlertRepeat) {
			a.last = now
			fire = append(fire, text)
		}
	}
	for id, a := range s.alerts {
		if _, still := cur[id]; !still {
			if !a.last.IsZero() {
				clear = append(clear, a.text)
			}
			delete(s.alerts, id)
		}
	}
	s.mu.Unlock()
	sort.Strings(fire)
	sort.Strings(clear)
	if len(fire) > 0 {
		s.alertMail(fmt.Sprintf("Asirive fleet: %d device(s) need attention", len(fire)), strings.Join(fire, "\n"))
	}
	if len(clear) > 0 {
		s.alertMail("Asirive fleet: recovered", "No longer needing attention:\n"+strings.Join(clear, "\n"))
	}
}

func (s *Server) alertMail(subject, body string) {
	for _, to := range s.AlertTo {
		to := to
		go func() {
			if err := s.Mailer.Send(to, subject, body+"\n\nOpen the console to act."); err != nil {
				log.Printf("alert mail failed: %v", err)
			}
		}()
	}
}

// StartAlerts runs the periodic check.
func (s *Server) StartAlerts() {
	go func() {
		for range time.Tick(30 * time.Second) {
			s.alertTick(time.Now())
		}
	}()
}
