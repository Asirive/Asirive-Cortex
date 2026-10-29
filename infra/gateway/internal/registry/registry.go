// Package registry is the device identity lifecycle: pre-register -> claim -> revoke.
//
// An operator pre-registers a device and gets a one-time claim code. The phone
// app sends that code plus the device's public key to the gateway (over the
// internet, with the device relayed over USB). The gateway binds the key,
// issues the device its own credential, and from then on the device's tier,
// ring and bench flag come from HERE, never from what the device says about itself.
package registry

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"errors"
	"sync"
	"time"
)

type State string

const (
	Pending State = "PENDING" // registered, waiting for the app to claim it
	Claimed State = "CLAIMED"
	Revoked State = "REVOKED"
)

const claimAlphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789" // no 0/O/1/I/L

var (
	ErrBadClaim       = errors.New("claim code invalid or expired")
	ErrNotFound       = errors.New("device not found")
	ErrRevoked        = errors.New("device revoked")
	ErrRateLimit      = errors.New("too many attempts, try again later")
	ErrAlreadyRevoked = errors.New("already revoked")
	ErrIDSpace        = errors.New("no free device id")
)

type Registration struct {
	ID        string    `json:"id"`
	Label     string    `json:"label"`
	Tier      string    `json:"tier"`
	Ring      string    `json:"ring"`
	Bench     bool      `json:"bench"`
	State     State     `json:"state"`
	CreatedAt time.Time `json:"created_at"`
	ExpiresAt time.Time `json:"claim_expires_at,omitempty"`
	ClaimedAt time.Time `json:"claimed_at,omitempty"`
	AccountID string    `json:"account_id,omitempty"`

	claimHash [32]byte
	tokenHash [32]byte
	pubKey    []byte
}

type Registry struct {
	mu       sync.Mutex
	byID     map[string]*Registration
	fails    map[string][]time.Time
	n        int
	ClaimTTL time.Duration
}

func New() *Registry {
	return &Registry{byID: map[string]*Registration{}, fails: map[string][]time.Time{}, ClaimTTL: 7 * 24 * time.Hour}
}

func randString(alphabet string, n int) string {
	b := make([]byte, n)
	rand.Read(b)
	out := make([]byte, n)
	for i := range b {
		out[i] = alphabet[int(b[i])%len(alphabet)]
	}
	return string(out)
}

func normalize(code string) string {
	out := make([]byte, 0, len(code))
	for _, c := range []byte(code) {
		switch {
		case c >= 'a' && c <= 'z':
			out = append(out, c-32)
		case c == '-' || c == ' ':
		default:
			out = append(out, c)
		}
	}
	return string(out)
}

// Register creates a PENDING device and returns its one-time claim code. The
// code is shown once; only its hash is kept.
// taken reports ids in use elsewhere (e.g. live devices); may be nil.
func (r *Registry) Register(label, tier, ring string, bench bool, now time.Time, taken func(string) bool) (*Registration, string, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.n++
	prefix := map[string]string{"ALPHA": "ALPHA", "BETA": "BETA", "STABLE": "STBL"}[tier]
	id := ""
	for tries := 0; ; tries++ {
		if tries > 2000 {
			return nil, "", ErrIDSpace
		}
		id = prefix + "-" + randString("0123456789", 4)
		if r.byID[id] == nil && (taken == nil || !taken(id)) {
			break
		}
	}
	code := randString(claimAlphabet, 8)
	reg := &Registration{ID: id, Label: label, Tier: tier, Ring: ring, Bench: bench && tier == "ALPHA",
		State: Pending, CreatedAt: now, ExpiresAt: now.Add(r.ClaimTTL), claimHash: sha256.Sum256([]byte(code))}
	r.byID[id] = reg
	return cp(reg), code[:4] + "-" + code[4:], nil
}

func cp(x *Registration) *Registration { c := *x; return &c }

// Claim binds a public key to the device whose pending claim code matches and
// returns the device's credential (shown once; only its hash is stored).
func (r *Registry) Claim(code string, pubKey []byte, accountID, source string, now time.Time) (*Registration, string, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	f := r.fails[source][:0:0]
	for _, t := range r.fails[source] {
		if now.Sub(t) < time.Minute {
			f = append(f, t)
		}
	}
	r.fails[source] = f
	if len(f) >= 5 {
		return nil, "", ErrRateLimit
	}
	h := sha256.Sum256([]byte(normalize(code)))
	for _, reg := range r.byID {
		if reg.State == Pending && subtle.ConstantTimeCompare(reg.claimHash[:], h[:]) == 1 {
			if now.After(reg.ExpiresAt) {
				break
			}
			tok := randString("0123456789abcdef", 48)
			reg.tokenHash = sha256.Sum256([]byte(tok))
			reg.pubKey, reg.AccountID, reg.State, reg.ClaimedAt = pubKey, accountID, Claimed, now
			return cp(reg), tok, nil
		}
	}
	r.fails[source] = append(r.fails[source], now)
	return nil, "", ErrBadClaim
}

// Authenticate checks a device credential. Revoked devices fail immediately.
func (r *Registry) Authenticate(id, token string) (*Registration, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	reg := r.byID[id]
	if reg == nil {
		return nil, ErrNotFound
	}
	if reg.State == Revoked {
		return nil, ErrRevoked
	}
	h := sha256.Sum256([]byte(token))
	if reg.State != Claimed || subtle.ConstantTimeCompare(reg.tokenHash[:], h[:]) != 1 {
		return nil, ErrNotFound
	}
	return cp(reg), nil
}

func (r *Registry) Revoke(id string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	reg := r.byID[id]
	if reg == nil {
		return ErrNotFound
	}
	if reg.State == Revoked {
		return ErrAlreadyRevoked
	}
	reg.State = Revoked
	reg.tokenHash = [32]byte{}
	return nil
}

func (r *Registry) Get(id string) (*Registration, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	reg := r.byID[id]
	if reg == nil {
		return nil, false
	}
	return cp(reg), true
}

func (r *Registry) List() []Registration {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make([]Registration, 0, len(r.byID))
	for _, reg := range r.byID {
		out = append(out, *cp(reg))
	}
	return out
}

func HexToken(b []byte) string { return hex.EncodeToString(b) }

// ListByAccount returns the devices an account has claimed (not revoked).
func (r *Registry) ListByAccount(acct string) []Registration {
	r.mu.Lock()
	defer r.mu.Unlock()
	var out []Registration
	for _, reg := range r.byID {
		if reg.AccountID == acct && reg.State == Claimed {
			out = append(out, *cp(reg))
		}
	}
	return out
}

// ReleaseAccount revokes every device the account owns (used on account deletion)
// and returns their ids. The credentials die; an operator must register the
// hardware again before a new owner can claim it.
func (r *Registry) ReleaseAccount(acct string) []string {
	r.mu.Lock()
	defer r.mu.Unlock()
	var ids []string
	for id, reg := range r.byID {
		if reg.AccountID == acct && reg.State != Revoked {
			reg.State = Revoked
			reg.tokenHash = [32]byte{}
			ids = append(ids, id)
		}
	}
	return ids
}

// SetChannel moves a claimed device between STABLE and BETA. ALPHA is assigned
// only by an operator at registration and is never changed here.
func (r *Registry) SetChannel(id, tier string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	reg := r.byID[id]
	if reg == nil {
		return ErrNotFound
	}
	if reg.Tier == "ALPHA" || (tier != "BETA" && tier != "STABLE") {
		return ErrNotFound
	}
	reg.Tier, reg.Ring = tier, tier
	return nil
}
