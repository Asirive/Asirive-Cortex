package server

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"regexp"
	"strings"
	"time"
)

// Role is ordered: each role can do everything the ones before it can.
type Role int

const (
	RoleViewer   Role = iota + 1 // read the fleet, never change it
	RoleOperator                 // register/revoke devices, alpha debug commands
	RoleRelease                  // register, halt and resume OTA releases
	RoleAdmin                    // manage operators
)

var roleNames = map[string]Role{"viewer": RoleViewer, "operator": RoleOperator, "release": RoleRelease, "admin": RoleAdmin}

func (r Role) String() string {
	for n, v := range roleNames {
		if v == r {
			return n
		}
	}
	return "none"
}

// Operator is a named console user with a personal token. Only the token hash is kept.
type Operator struct {
	Name      string `json:"name"`
	Role      string `json:"role"`
	TokenHash []byte `json:"token_hash,omitempty"`
	CreatedAt int64  `json:"created_at_ms"`
	Revoked   bool   `json:"revoked,omitempty"`
}

type ctxKey struct{}

type principal struct {
	Name string
	Role Role
}

func actor(r *http.Request) string {
	if p, ok := r.Context().Value(ctxKey{}).(principal); ok {
		return p.Name
	}
	return "unknown"
}

var opName = regexp.MustCompile(`^[a-z][a-z0-9._-]{1,31}$`)

func hashTok(t string) []byte { h := sha256.Sum256([]byte(t)); return h[:] }

// identify maps a bearer token to a principal. The shared bootstrap token is an
// admin named "bootstrap"; use it once to create real operators, then retire it.
func (s *Server) identify(tok string) (principal, bool) {
	if tok == "" {
		return principal{}, false
	}
	if subtle.ConstantTimeCompare([]byte(tok), []byte(s.DevToken)) == 1 {
		return principal{"bootstrap", RoleAdmin}, true
	}
	h := hashTok(tok)
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, o := range s.operators {
		if !o.Revoked && subtle.ConstantTimeCompare(o.TokenHash, h) == 1 {
			return principal{o.Name, roleNames[o.Role]}, true
		}
	}
	return principal{}, false
}

func (s *Server) whoami(w http.ResponseWriter, r *http.Request) {
	p := r.Context().Value(ctxKey{}).(principal)
	writeJSON(w, map[string]any{"name": p.Name, "role": p.Role.String()})
}

func (s *Server) listOperators(w http.ResponseWriter, r *http.Request) {
	s.mu.Lock()
	out := make([]Operator, 0, len(s.operators))
	for _, o := range s.operators {
		c := *o
		c.TokenHash = nil
		out = append(out, c)
	}
	s.mu.Unlock()
	writeJSON(w, out)
}

func (s *Server) createOperator(w http.ResponseWriter, r *http.Request) {
	var req struct{ Name, Role string }
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4<<10)).Decode(&req); err != nil {
		writeErr(w, 400, "bad_request", "Send JSON with name and role.")
		return
	}
	req.Name = strings.ToLower(strings.TrimSpace(req.Name))
	if !opName.MatchString(req.Name) || req.Name == "bootstrap" || req.Name == "system" {
		writeErr(w, 400, "bad_name", "Name must be 2-32 characters: lowercase letters, digits, . _ -, starting with a letter.")
		return
	}
	if _, ok := roleNames[req.Role]; !ok {
		writeErr(w, 400, "bad_role", "Role must be viewer, operator, release or admin.")
		return
	}
	b := make([]byte, 24)
	rand.Read(b)
	tok := "op_" + hex.EncodeToString(b)
	s.mu.Lock()
	if old := s.operators[req.Name]; old != nil && !old.Revoked {
		s.mu.Unlock()
		writeErr(w, 409, "exists", "An active operator with that name already exists. Revoke it first.")
		return
	}
	s.operators[req.Name] = &Operator{Name: req.Name, Role: req.Role, TokenHash: hashTok(tok), CreatedAt: time.Now().UnixMilli()}
	s.mu.Unlock()
	s.record(actor(r), "operator:create", req.Name, "created", req.Role)
	writeJSON(w, map[string]any{"name": req.Name, "role": req.Role, "token": tok, "note": "Shown once. Give it to that person only."})
}

func (s *Server) revokeOperator(w http.ResponseWriter, r *http.Request) {
	name := r.PathValue("name")
	if name == actor(r) {
		writeErr(w, 400, "self", "You can't revoke yourself. Ask another admin.")
		return
	}
	s.mu.Lock()
	o := s.operators[name]
	if o == nil || o.Revoked {
		s.mu.Unlock()
		writeErr(w, 404, "not_found", "No active operator with that name.")
		return
	}
	o.Revoked = true
	s.mu.Unlock()
	s.record(actor(r), "operator:revoke", name, "revoked", "")
	writeJSON(w, map[string]any{"ok": true})
}
