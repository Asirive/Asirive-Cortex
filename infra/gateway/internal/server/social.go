package server

import (
	"errors"
	"google.golang.org/protobuf/encoding/protojson"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/asirive/cortex/gateway/internal/fleet"
	pb "github.com/asirive/cortex/gateway/internal/gen/cortex/v1"
	"github.com/asirive/cortex/gateway/internal/ota"
	"github.com/asirive/cortex/gateway/internal/social"
)

func (s *Server) socialRoutes(mux *http.ServeMux) {
	mux.HandleFunc("POST /v1/companions", s.appAuth(s.compInvite))
	mux.HandleFunc("POST /v1/companions/accept", s.appAuth(s.compAccept))
	mux.HandleFunc("GET /v1/companions", s.appAuth(s.compList))
	mux.HandleFunc("PUT /v1/companions/{id}/grants", s.appAuth(s.compGrants))
	mux.HandleFunc("DELETE /v1/companions/{id}", s.appAuth(s.compRevoke))
	mux.HandleFunc("PUT /v1/me/location", s.appAuth(s.locPut))
	mux.HandleFunc("DELETE /v1/me/location", s.appAuth(s.locClear))
	mux.HandleFunc("GET /v1/companion/users/{id}/location", s.appAuth(s.locGet))
	mux.HandleFunc("POST /v1/calls", s.appAuth(s.callStart))
	mux.HandleFunc("GET /v1/calls/inbox", s.appAuth(s.callInbox))
	mux.HandleFunc("GET /v1/calls/{id}", s.appAuth(s.callGet))
	mux.HandleFunc("POST /v1/calls/{id}/answer", s.appAuth(s.callAnswer))
	mux.HandleFunc("POST /v1/calls/{id}/ice", s.appAuth(s.callICE))
	mux.HandleFunc("POST /v1/calls/{id}/end", s.appAuth(s.callEnd))
	mux.HandleFunc("POST /v1/feedback", s.appAuth(s.appFeedback))
	mux.HandleFunc("GET /v1/me/devices/{id}/update", s.appAuth(s.updateGet))
	mux.HandleFunc("POST /v1/me/devices/{id}/update", s.appAuth(s.updateReport))
}

func (s *Server) socialErr(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, social.ErrRate):
		writeErr(w, 429, "rate_limited", "Too many attempts. Wait a minute and try again.")
	case errors.Is(err, social.ErrBadCode):
		writeErr(w, 422, "invalid_or_expired", "That invite code is wrong or has expired. Ask for a new one.")
	case errors.Is(err, social.ErrForbidden):
		writeErr(w, 403, "not_allowed", "That isn't allowed. The other person has to grant it first.")
	case errors.Is(err, social.ErrBusy):
		writeErr(w, 409, "busy", "Someone is already in a call.")
	case errors.Is(err, social.ErrInvalid):
		writeErr(w, 400, "bad_request", "That request wasn't valid.")
	default:
		writeErr(w, 404, "not_found", "Not found.")
	}
}

func (s *Server) compInvite(w http.ResponseWriter, r *http.Request) {
	var req struct{ Label string }
	if !decode(w, r, &req) {
		return
	}
	l, code, err := s.Social.Invite(acct(r).ID, req.Label, time.Now())
	if err != nil {
		s.socialErr(w, err)
		return
	}
	raw := strings.ReplaceAll(code, "-", "")
	writeJSON(w, map[string]any{"link": l, "invite_code": code, "invite_link": s.AppLinkBase + "companion?code=" + raw,
		"note": "Shown once. Expires in 48 hours. The companion sees nothing until you grant it."})
}

func (s *Server) compAccept(w http.ResponseWriter, r *http.Request) {
	var req struct{ Code string }
	if !decode(w, r, &req) {
		return
	}
	l, err := s.Social.Accept(acct(r).ID, req.Code, time.Now())
	if err != nil {
		s.socialErr(w, err)
		return
	}
	s.record("app:"+acct(r).ID, "companion:accept", l.ID, "active", "")
	writeJSON(w, map[string]any{"link_id": l.ID, "owner_id": l.Owner, "owner_email": s.Accounts.Email(l.Owner), "grants": map[string]bool{"location": false, "call": false}})
}

func (s *Server) compList(w http.ResponseWriter, r *http.Request) {
	owned, watching := s.Social.Links(acct(r).ID, time.Now())
	w2 := []map[string]any{}
	for _, l := range watching {
		w2 = append(w2, map[string]any{"link_id": l.ID, "owner_id": l.Owner, "owner_email": s.Accounts.Email(l.Owner), "grants": map[string]bool{"location": l.GrantLoc, "call": l.GrantCall}})
	}
	if owned == nil {
		owned = []social.Link{}
	}
	writeJSON(w, map[string]any{"companions": owned, "looking_after": w2})
}

func (s *Server) compGrants(w http.ResponseWriter, r *http.Request) {
	var req struct{ Location, Call bool }
	if !decode(w, r, &req) {
		return
	}
	if err := s.Social.SetGrants(acct(r).ID, r.PathValue("id"), req.Location, req.Call); err != nil {
		s.socialErr(w, err)
		return
	}
	s.record("app:"+acct(r).ID, "companion:grants", r.PathValue("id"), "set", "location="+strconv.FormatBool(req.Location)+" call="+strconv.FormatBool(req.Call))
	writeJSON(w, map[string]any{"grants": map[string]bool{"location": req.Location, "call": req.Call}})
}

func (s *Server) compRevoke(w http.ResponseWriter, r *http.Request) {
	if err := s.Social.Revoke(acct(r).ID, r.PathValue("id"), time.Now()); err != nil {
		s.socialErr(w, err)
		return
	}
	s.record("app:"+acct(r).ID, "companion:revoke", r.PathValue("id"), "revoked", "")
	writeJSON(w, map[string]string{"result": "revoked"})
}

func (s *Server) locPut(w http.ResponseWriter, r *http.Request) {
	var p social.Point
	if !decode(w, r, &p) {
		return
	}
	if err := s.Social.PutLocation(acct(r).ID, p, time.Now()); err != nil {
		s.socialErr(w, err)
		return
	}
	writeJSON(w, map[string]string{"result": "ok"})
}

func (s *Server) locClear(w http.ResponseWriter, r *http.Request) {
	s.Social.ClearLocation(acct(r).ID)
	writeJSON(w, map[string]string{"result": "cleared"})
}

func (s *Server) locGet(w http.ResponseWriter, r *http.Request) {
	p, err := s.Social.CompanionLocation(acct(r).ID, r.PathValue("id"), time.Now())
	if err != nil {
		s.socialErr(w, err)
		return
	}
	writeJSON(w, p)
}

func (s *Server) callStart(w http.ResponseWriter, r *http.Request) {
	var req struct{ To, Offer string }
	if !decode(w, r, &req) {
		return
	}
	c, err := s.Social.StartCall(acct(r).ID, req.To, req.Offer, time.Now())
	if err != nil {
		s.socialErr(w, err)
		return
	}
	writeJSON(w, map[string]any{"call_id": c.ID})
}

func (s *Server) callInbox(w http.ResponseWriter, r *http.Request) {
	in := s.Social.Inbox(acct(r).ID, time.Now())
	if in == nil {
		in = []social.Call{}
	}
	writeJSON(w, in)
}

// callGet returns only what the caller needs: state, the other side's answer and ICE candidates.
func (s *Server) callGet(w http.ResponseWriter, r *http.Request) {
	me := acct(r).ID
	c, err := s.Social.GetCall(me, r.PathValue("id"), time.Now())
	if err != nil {
		s.socialErr(w, err)
		return
	}
	out := map[string]any{"id": c.ID, "state": c.State, "from": c.From, "to": c.To}
	if me == c.From {
		out["answer"], out["ice"] = c.Answer, c.ICETo
	} else {
		out["offer"], out["ice"] = c.Offer, c.ICEFrom
	}
	writeJSON(w, out)
}

func (s *Server) callAnswer(w http.ResponseWriter, r *http.Request) {
	var req struct{ Answer string }
	if !decode(w, r, &req) {
		return
	}
	if err := s.Social.Answer(acct(r).ID, r.PathValue("id"), req.Answer, time.Now()); err != nil {
		s.socialErr(w, err)
		return
	}
	writeJSON(w, map[string]string{"result": "answered"})
}

func (s *Server) callICE(w http.ResponseWriter, r *http.Request) {
	var req struct{ Candidate string }
	if !decode(w, r, &req) {
		return
	}
	if err := s.Social.AddICE(acct(r).ID, r.PathValue("id"), req.Candidate, time.Now()); err != nil {
		s.socialErr(w, err)
		return
	}
	writeJSON(w, map[string]string{"result": "ok"})
}

func (s *Server) callEnd(w http.ResponseWriter, r *http.Request) {
	if err := s.Social.Finish(acct(r).ID, r.PathValue("id"), time.Now()); err != nil {
		s.socialErr(w, err)
		return
	}
	writeJSON(w, map[string]string{"result": "ended"})
}

// ownedDevice returns the registration if the signed-in account owns it.
func (s *Server) ownedDevice(r *http.Request) (id, tier, ring string, ok bool) {
	for _, d := range s.Reg.ListByAccount(acct(r).ID) {
		if d.ID == r.PathValue("id") {
			return d.ID, d.Tier, d.Ring, true
		}
	}
	return "", "", "", false
}

func (s *Server) appFeedback(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Text       string          `json:"text"`
		AppVersion string          `json:"app_version"`
		Log        []fleet.LogLine `json:"log_excerpt"`
	}
	if !decode(w, r, &req) {
		return
	}
	devs := s.Reg.ListByAccount(acct(r).ID)
	if strings.TrimSpace(req.Text) == "" || len(devs) == 0 {
		writeErr(w, 400, "bad_request", "Write a message, and pair a device first.")
		return
	}
	if len(req.Log) > 50 {
		req.Log = req.Log[len(req.Log)-50:]
	}
	for i := range req.Log {
		req.Log[i].Message = clip(req.Log[i].Message, 300)
	}
	s.Fleet.AddFeedback(fleet.Feedback{TsMs: time.Now().UnixMilli(), DeviceID: devs[0].ID, Tier: devs[0].Tier, Text: clip(req.Text, 2000), App: clip(req.AppVersion, 40), Log: req.Log})
	writeJSON(w, map[string]string{"result": "received"})
}

func ringOf(s string) pb.Ring {
	return map[string]pb.Ring{"ALPHA": pb.Ring_RING_ALPHA, "BETA": pb.Ring_RING_BETA, "STABLE": pb.Ring_RING_STABLE}[s]
}

// updateGet gives the app the signed manifest its device should install, or 204.
// The app downloads the artifact and hands it to the device over USB; the device
// verifies the signature and anti-rollback counter itself, so this path is untrusted transport.
func (s *Server) updateGet(w http.ResponseWriter, r *http.Request) {
	id, _, ring, ok := s.ownedDevice(r)
	if !ok {
		writeErr(w, 404, "not_found", "That isn't one of your devices.")
		return
	}
	if s.OTA == nil {
		w.WriteHeader(http.StatusNoContent)
		return
	}
	counter, _ := strconv.ParseUint(r.URL.Query().Get("counter"), 10, 64)
	m := s.OTA.Offer(id, ringOf(ring), counter)
	if m == nil {
		w.WriteHeader(http.StatusNoContent)
		return
	}
	b, _ := (protojsonOpts).Marshal(m)
	w.Header().Set("Content-Type", "application/json")
	w.Write(b)
}

func (s *Server) updateReport(w http.ResponseWriter, r *http.Request) {
	id, _, _, ok := s.ownedDevice(r)
	if !ok || s.OTA == nil {
		writeErr(w, 404, "not_found", "That isn't one of your devices.")
		return
	}
	var req struct {
		ReleaseID string `json:"release_id"`
		Outcome   string `json:"outcome"`
		Version   string `json:"version"`
	}
	if !decode(w, r, &req) {
		return
	}
	o, valid := map[string]ota.Outcome{"committed": ota.Committed, "rolled_back": ota.RolledBack, "rejected": ota.Rejected}[req.Outcome]
	if !valid {
		writeErr(w, 400, "bad_request", "outcome must be committed, rolled_back or rejected.")
		return
	}
	s.OTA.Report(req.ReleaseID, id, o)
	s.record("app:"+acct(r).ID, "update:report", id, req.Outcome, req.ReleaseID)
	writeJSON(w, map[string]string{"result": "recorded"})
}

var protojsonOpts = protojson.MarshalOptions{EmitUnpopulated: false}
