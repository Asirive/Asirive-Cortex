// Package accounts is the app-user identity store: email+password accounts,
// email verification, password reset, sessions, beta opt-in and deletion.
//
// Secrets (passwords, session tokens, mail tokens) are never stored in the
// clear: passwords use argon2id, tokens a SHA-256 of 192 random bits.
package accounts

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"sync"
	"time"

	"golang.org/x/crypto/argon2"
)

var (
	ErrInvalid      = errors.New("invalid input")
	ErrWeakPassword = errors.New("password must be 10-128 characters")
	ErrCredentials  = errors.New("email or password is wrong")
	ErrUnverified   = errors.New("email not verified")
	ErrRateLimit    = errors.New("too many attempts")
	ErrToken        = errors.New("link is invalid or expired")
	ErrNoSession    = errors.New("not signed in")
)

const (
	SessionTTL = 30 * 24 * time.Hour
	VerifyTTL  = 24 * time.Hour
	ResetTTL   = time.Hour
)

type Account struct {
	ID            string `json:"id"`
	Email         string `json:"email"`
	PassHash      string `json:"pass_hash"`
	Verified      bool   `json:"verified"`
	Beta          bool   `json:"beta"`
	BetaConsentMs int64  `json:"beta_consent_ms,omitempty"` // when the user opted in
	BetaConsentV  string `json:"beta_consent_version,omitempty"`
	CreatedMs     int64  `json:"created_ms"`
}

type session struct {
	Account string `json:"account"`
	Expires int64  `json:"expires_ms"`
}

type mailToken struct {
	Account string `json:"account"`
	Kind    string `json:"kind"` // verify | reset
	Expires int64  `json:"expires_ms"`
}

type Store struct {
	mu       sync.Mutex
	byID     map[string]*Account
	byEmail  map[string]string
	sessions map[string]session   // sha256(token) hex
	tokens   map[string]mailToken // sha256(token) hex
	fails    map[string][]time.Time
	sem      chan struct{}
	dummy    string
}

func New() *Store {
	s := &Store{byID: map[string]*Account{}, byEmail: map[string]string{}, sessions: map[string]session{},
		tokens: map[string]mailToken{}, fails: map[string][]time.Time{}, sem: make(chan struct{}, 4)}
	s.dummy = s.hash("dummy-password-for-timing")
	return s
}

var emailRe = regexp.MustCompile(`^[^@\s]+@[^@\s]+\.[^@\s]+$`)

func NormEmail(e string) (string, error) {
	e = strings.ToLower(strings.TrimSpace(e))
	if len(e) > 254 || !emailRe.MatchString(e) {
		return "", ErrInvalid
	}
	return e, nil
}

func rnd(n int) []byte { b := make([]byte, n); rand.Read(b); return b }

func newToken(prefix string) (tok, key string) {
	tok = prefix + hex.EncodeToString(rnd(24))
	return tok, tkey(tok)
}

func tkey(t string) string { h := sha256.Sum256([]byte(t)); return hex.EncodeToString(h[:]) }

// argon2id, OWASP minimum profile (19 MiB, t=2, p=1). Concurrency is capped so a
// burst of logins cannot exhaust memory.
func (s *Store) hash(pw string) string {
	s.sem <- struct{}{}
	defer func() { <-s.sem }()
	salt := rnd(16)
	k := argon2.IDKey([]byte(pw), salt, 2, 19*1024, 1, 32)
	return fmt.Sprintf("argon2id$%s$%s", base64.RawStdEncoding.EncodeToString(salt), base64.RawStdEncoding.EncodeToString(k))
}

func (s *Store) check(pw, enc string) bool {
	p := strings.Split(enc, "$")
	if len(p) != 3 || p[0] != "argon2id" {
		return false
	}
	salt, e1 := base64.RawStdEncoding.DecodeString(p[1])
	want, e2 := base64.RawStdEncoding.DecodeString(p[2])
	if e1 != nil || e2 != nil {
		return false
	}
	s.sem <- struct{}{}
	defer func() { <-s.sem }()
	got := argon2.IDKey([]byte(pw), salt, 2, 19*1024, 1, 32)
	return subtle.ConstantTimeCompare(got, want) == 1
}

func checkPassword(pw string) error {
	if n := len([]rune(pw)); n < 10 || n > 128 {
		return ErrWeakPassword
	}
	return nil
}

// Register creates an unverified account and returns a verification token to
// email. If the address is already registered it returns ("", nil) so callers
// cannot use the response to learn which emails have accounts.
func (s *Store) Register(email, pw string, now time.Time) (verifyToken string, err error) {
	email, err = NormEmail(email)
	if err != nil {
		return "", err
	}
	if err := checkPassword(pw); err != nil {
		return "", err
	}
	h := s.hash(pw)
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, taken := s.byEmail[email]; taken {
		return "", nil
	}
	id := "u_" + hex.EncodeToString(rnd(8))
	s.byID[id] = &Account{ID: id, Email: email, PassHash: h, CreatedMs: now.UnixMilli()}
	s.byEmail[email] = id
	return s.issue(id, "verify", VerifyTTL, now), nil
}

func (s *Store) issue(acct, kind string, ttl time.Duration, now time.Time) string {
	tok, key := newToken("mt_")
	s.tokens[key] = mailToken{acct, kind, now.Add(ttl).UnixMilli()}
	return tok
}

// ResendVerify returns a fresh verification token for an unverified account, or "".
func (s *Store) ResendVerify(email string, now time.Time) string {
	email, err := NormEmail(email)
	if err != nil {
		return ""
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	a := s.byID[s.byEmail[email]]
	if a == nil || a.Verified {
		return ""
	}
	return s.issue(a.ID, "verify", VerifyTTL, now)
}

func (s *Store) consume(tok, kind string, now time.Time) (string, error) {
	k := tkey(tok)
	t, ok := s.tokens[k]
	if !ok || t.Kind != kind || now.UnixMilli() > t.Expires {
		delete(s.tokens, k)
		return "", ErrToken
	}
	delete(s.tokens, k)
	return t.Account, nil
}

func (s *Store) Verify(tok string, now time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	id, err := s.consume(tok, "verify", now)
	if err != nil {
		return err
	}
	if a := s.byID[id]; a != nil {
		a.Verified = true
	}
	return nil
}

func (s *Store) limited(key string, now time.Time) bool {
	f := s.fails[key][:0:0]
	for _, t := range s.fails[key] {
		if now.Sub(t) < 15*time.Minute {
			f = append(f, t)
		}
	}
	s.fails[key] = f
	return len(f) >= 10
}

// Login checks credentials and returns a session token. Failures are limited per
// email and per source address.
func (s *Store) Login(email, pw, source string, now time.Time) (string, *Account, error) {
	email, err := NormEmail(email)
	if err != nil {
		return "", nil, ErrCredentials
	}
	s.mu.Lock()
	if s.limited("e:"+email, now) || s.limited("i:"+source, now) {
		s.mu.Unlock()
		return "", nil, ErrRateLimit
	}
	a := s.byID[s.byEmail[email]]
	enc := s.dummy
	if a != nil {
		enc = a.PassHash
	}
	s.mu.Unlock()
	ok := s.check(pw, enc) // always run the hash so timing does not reveal whether the email exists
	s.mu.Lock()
	defer s.mu.Unlock()
	if a == nil || !ok {
		s.fails["e:"+email] = append(s.fails["e:"+email], now)
		s.fails["i:"+source] = append(s.fails["i:"+source], now)
		return "", nil, ErrCredentials
	}
	if !a.Verified {
		return "", nil, ErrUnverified
	}
	tok, key := newToken("ses_")
	s.sessions[key] = session{a.ID, now.Add(SessionTTL).UnixMilli()}
	c := *a
	return tok, &c, nil
}

func (s *Store) Authenticate(tok string, now time.Time) (*Account, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	k := tkey(tok)
	se, ok := s.sessions[k]
	if !ok || now.UnixMilli() > se.Expires {
		delete(s.sessions, k)
		return nil, ErrNoSession
	}
	a := s.byID[se.Account]
	if a == nil {
		return nil, ErrNoSession
	}
	c := *a
	return &c, nil
}

func (s *Store) Logout(tok string) { s.mu.Lock(); delete(s.sessions, tkey(tok)); s.mu.Unlock() }

func (s *Store) dropSessions(id string) {
	for k, se := range s.sessions {
		if se.Account == id {
			delete(s.sessions, k)
		}
	}
}

// ResetRequest returns (email, token) for a known address, else ("", "").
func (s *Store) ResetRequest(email string, now time.Time) (string, string) {
	email, err := NormEmail(email)
	if err != nil {
		return "", ""
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	a := s.byID[s.byEmail[email]]
	if a == nil {
		return "", ""
	}
	return a.Email, s.issue(a.ID, "reset", ResetTTL, now)
}

// Reset sets a new password and signs out every session. A reset email also proves
// the address, so it verifies the account.
func (s *Store) Reset(tok, pw string, now time.Time) error {
	if err := checkPassword(pw); err != nil {
		return err
	}
	h := s.hash(pw)
	s.mu.Lock()
	defer s.mu.Unlock()
	id, err := s.consume(tok, "reset", now)
	if err != nil {
		return err
	}
	a := s.byID[id]
	if a == nil {
		return ErrToken
	}
	a.PassHash, a.Verified = h, true
	s.dropSessions(id)
	return nil
}

// Delete removes the account after re-checking the password.
func (s *Store) Delete(id, pw string) error {
	s.mu.Lock()
	a := s.byID[id]
	s.mu.Unlock()
	if a == nil {
		return ErrNoSession
	}
	if !s.check(pw, a.PassHash) {
		return ErrCredentials
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.byID, id)
	delete(s.byEmail, a.Email)
	s.dropSessions(id)
	for k, t := range s.tokens {
		if t.Account == id {
			delete(s.tokens, k)
		}
	}
	return nil
}

// SetBeta records opt-in (with the consent text version and time) or opt-out.
func (s *Store) SetBeta(id string, on bool, consentVersion string, now time.Time) error {
	if on && strings.TrimSpace(consentVersion) == "" {
		return ErrInvalid
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	a := s.byID[id]
	if a == nil {
		return ErrNoSession
	}
	a.Beta = on
	if on {
		a.BetaConsentMs, a.BetaConsentV = now.UnixMilli(), consentVersion
	}
	return nil
}

type snap struct {
	Accounts []*Account           `json:"accounts"`
	Sessions map[string]session   `json:"sessions"`
	Tokens   map[string]mailToken `json:"tokens"`
}

func (s *Store) Snapshot() ([]byte, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	o := snap{Sessions: s.sessions, Tokens: s.tokens}
	for _, a := range s.byID {
		o.Accounts = append(o.Accounts, a)
	}
	return json.Marshal(o)
}

func (s *Store) Restore(data []byte) error {
	var o snap
	if err := json.Unmarshal(data, &o); err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.byID, s.byEmail = map[string]*Account{}, map[string]string{}
	for _, x := range o.Accounts {
		s.byID[x.ID], s.byEmail[x.Email] = x, x.ID
	}
	s.sessions, s.tokens = o.Sessions, o.Tokens
	if s.sessions == nil {
		s.sessions = map[string]session{}
	}
	if s.tokens == nil {
		s.tokens = map[string]mailToken{}
	}
	return nil
}

// Email returns the address for an account id ("" if unknown).
func (s *Store) Email(id string) string {
	s.mu.Lock()
	defer s.mu.Unlock()
	if a := s.byID[id]; a != nil {
		return a.Email
	}
	return ""
}

// Exists reports whether the account id is live.
func (s *Store) Exists(id string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.byID[id] != nil
}
