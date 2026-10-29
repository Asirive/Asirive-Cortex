package server

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/asirive/cortex/gateway/internal/accounts"
)

type appKey struct{}

// BetaConsentVersion is the id of the consent text the app shows. Bump it when the text changes.
const BetaConsentVersion = "beta-2026-10"

func (s *Server) appRoutes(mux *http.ServeMux) {
	mux.HandleFunc("POST /v1/auth/register", s.appRegister)
	mux.HandleFunc("POST /v1/auth/verify", s.appVerify)
	mux.HandleFunc("POST /v1/auth/resend", s.appResend)
	mux.HandleFunc("POST /v1/auth/login", s.appLogin)
	mux.HandleFunc("POST /v1/auth/logout", s.appAuth(s.appLogout))
	mux.HandleFunc("POST /v1/auth/reset-request", s.appResetRequest)
	mux.HandleFunc("POST /v1/auth/reset", s.appReset)
	mux.HandleFunc("GET /v1/me", s.appAuth(s.appMe))
	mux.HandleFunc("DELETE /v1/me", s.appAuth(s.appDelete))
	mux.HandleFunc("PUT /v1/me/beta", s.appAuth(s.appBeta))
	mux.HandleFunc("GET /v1/me/devices", s.appAuth(s.appDevices))
	s.socialRoutes(mux)
}

func bearer(r *http.Request) string {
	return strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
}

func (s *Server) appAuth(h http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		a, err := s.Accounts.Authenticate(bearer(r), time.Now())
		if err != nil {
			writeErr(w, 401, "signed_out", "Please sign in again.")
			return
		}
		h(w, r.WithContext(context.WithValue(r.Context(), appKey{}, a)))
	}
}

func acct(r *http.Request) *accounts.Account { return r.Context().Value(appKey{}).(*accounts.Account) }

func decode(w http.ResponseWriter, r *http.Request, v any) bool {
	if json.NewDecoder(io.LimitReader(r.Body, 1<<14)).Decode(v) != nil {
		writeErr(w, 400, "bad_request", "That request wasn't understood.")
		return false
	}
	return true
}

// mailAsync never blocks or fails the request: a mail outage must not reveal which emails exist.
func (s *Server) mailAsync(to, subject, text string) {
	go func() {
		if err := s.Mailer.Send(to, subject, text); err != nil {
			log.Printf("mail to account failed: %v", err)
		}
	}()
}

func (s *Server) link(kind, tok string) string { return s.AppLinkBase + kind + "?token=" + tok }

func (s *Server) appRegister(w http.ResponseWriter, r *http.Request) {
	var req struct{ Email, Password string }
	if !decode(w, r, &req) {
		return
	}
	tok, err := s.Accounts.Register(req.Email, req.Password, time.Now())
	switch {
	case errors.Is(err, accounts.ErrWeakPassword):
		writeErr(w, 400, "weak_password", "Use a password of at least 10 characters.")
		return
	case err != nil:
		writeErr(w, 400, "bad_email", "That doesn't look like an email address.")
		return
	}
	if tok != "" {
		s.mailAsync(strings.ToLower(strings.TrimSpace(req.Email)), "Confirm your Asirive account",
			"Welcome to Asirive.\n\nOpen this link on your phone to confirm your email:\n"+s.link("verify", tok)+"\n\nIf you didn't sign up, ignore this email.")
	}
	// same answer whether or not the address already had an account
	writeJSON(w, map[string]string{"result": "check_email"})
}

func (s *Server) appResend(w http.ResponseWriter, r *http.Request) {
	var req struct{ Email string }
	if !decode(w, r, &req) {
		return
	}
	if tok := s.Accounts.ResendVerify(req.Email, time.Now()); tok != "" {
		s.mailAsync(strings.ToLower(strings.TrimSpace(req.Email)), "Confirm your Asirive account", "Open this link to confirm your email:\n"+s.link("verify", tok))
	}
	writeJSON(w, map[string]string{"result": "check_email"})
}

func (s *Server) appVerify(w http.ResponseWriter, r *http.Request) {
	var req struct{ Token string }
	if !decode(w, r, &req) {
		return
	}
	if s.Accounts.Verify(req.Token, time.Now()) != nil {
		writeErr(w, 422, "bad_link", "This link is invalid or has expired. Ask for a new one.")
		return
	}
	writeJSON(w, map[string]string{"result": "verified"})
}

func (s *Server) appLogin(w http.ResponseWriter, r *http.Request) {
	var req struct{ Email, Password string }
	if !decode(w, r, &req) {
		return
	}
	tok, a, err := s.Accounts.Login(req.Email, req.Password, clientIP(r), time.Now())
	switch {
	case errors.Is(err, accounts.ErrRateLimit):
		writeErr(w, 429, "rate_limited", "Too many attempts. Wait 15 minutes and try again.")
	case errors.Is(err, accounts.ErrUnverified):
		writeErr(w, 403, "unverified", "Confirm your email first. We can send the link again.")
	case err != nil:
		writeErr(w, 401, "bad_credentials", "Email or password is wrong.")
	default:
		s.record("app:"+a.ID, "app:login", a.ID, "ok", "")
		writeJSON(w, map[string]any{"token": tok, "expires_in_s": int(accounts.SessionTTL.Seconds()), "account": accountView(a)})
	}
}

func accountView(a *accounts.Account) map[string]any {
	return map[string]any{"id": a.ID, "email": a.Email, "beta": a.Beta, "beta_consent_version": BetaConsentVersion}
}

func (s *Server) appLogout(w http.ResponseWriter, r *http.Request) {
	s.Accounts.Logout(bearer(r))
	writeJSON(w, map[string]string{"result": "signed_out"})
}

func (s *Server) appResetRequest(w http.ResponseWriter, r *http.Request) {
	var req struct{ Email string }
	if !decode(w, r, &req) {
		return
	}
	if to, tok := s.Accounts.ResetRequest(req.Email, time.Now()); tok != "" {
		s.mailAsync(to, "Reset your Asirive password", "Open this link to choose a new password (valid for 1 hour):\n"+s.link("reset", tok)+"\n\nIf you didn't ask for this, ignore this email.")
	}
	writeJSON(w, map[string]string{"result": "check_email"})
}

func (s *Server) appReset(w http.ResponseWriter, r *http.Request) {
	var req struct{ Token, Password string }
	if !decode(w, r, &req) {
		return
	}
	switch err := s.Accounts.Reset(req.Token, req.Password, time.Now()); {
	case errors.Is(err, accounts.ErrWeakPassword):
		writeErr(w, 400, "weak_password", "Use a password of at least 10 characters.")
	case err != nil:
		writeErr(w, 422, "bad_link", "This link is invalid or has expired. Ask for a new one.")
	default:
		writeJSON(w, map[string]string{"result": "password_changed"})
	}
}

func (s *Server) appMe(w http.ResponseWriter, r *http.Request) { writeJSON(w, accountView(acct(r))) }

func (s *Server) appDelete(w http.ResponseWriter, r *http.Request) {
	var req struct{ Password string }
	if !decode(w, r, &req) {
		return
	}
	a := acct(r)
	if err := s.Accounts.Delete(a.ID, req.Password); err != nil {
		writeErr(w, 401, "bad_credentials", "Password is wrong, so nothing was deleted.")
		return
	}
	ids := s.Reg.ReleaseAccount(a.ID)
	s.Social.DeleteAccount(a.ID)
	s.Fleet.DeleteFeedback(ids)
	for _, id := range ids {
		s.mu.Lock()
		c := s.conns[id]
		s.mu.Unlock()
		if c != nil {
			c.ws.Close()
		}
	}
	s.record("app:"+a.ID, "account:delete", a.ID, "deleted", "devices released: "+strings.Join(ids, ","))
	writeJSON(w, map[string]any{"result": "deleted", "devices_released": ids})
}

func (s *Server) appBeta(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Enabled bool   `json:"enabled"`
		Consent string `json:"consent_version"`
	}
	if !decode(w, r, &req) {
		return
	}
	if req.Enabled && req.Consent != BetaConsentVersion {
		writeErr(w, 400, "consent_required", "Please read and accept the current beta terms first.")
		return
	}
	a := acct(r)
	if err := s.Accounts.SetBeta(a.ID, req.Enabled, req.Consent, time.Now()); err != nil {
		writeErr(w, 400, "bad_request", "Couldn't change the beta setting.")
		return
	}
	tier := "STABLE"
	if req.Enabled {
		tier = "BETA"
	}
	moved := []string{}
	for _, d := range s.Reg.ListByAccount(a.ID) {
		if d.Tier != "ALPHA" && s.Reg.SetChannel(d.ID, tier) == nil {
			moved = append(moved, d.ID)
		}
	}
	s.record("app:"+a.ID, "account:beta", a.ID, tier, "consent "+req.Consent+"; devices "+strings.Join(moved, ","))
	writeJSON(w, map[string]any{"beta": req.Enabled, "devices_moved": moved, "note": "Devices switch channel at their next update check."})
}

func (s *Server) appDevices(w http.ResponseWriter, r *http.Request) {
	out := []map[string]any{}
	for _, d := range s.Reg.ListByAccount(acct(r).ID) {
		m := map[string]any{"id": d.ID, "label": d.Label, "tier": d.Tier, "claimed_at": d.ClaimedAt}
		if dev, _, _, ok := s.Fleet.Get(d.ID); ok {
			m["online"], m["firmware"], m["battery_pct"], m["safety"] = dev.Online, dev.Firmware, dev.Battery, dev.Safety
		}
		out = append(out, m)
	}
	writeJSON(w, out)
}
