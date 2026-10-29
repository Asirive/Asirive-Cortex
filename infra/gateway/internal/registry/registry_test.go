package registry

import (
	"testing"
	"time"
)

func TestLifecycle(t *testing.T) {
	r := New()
	now := time.Now()
	reg, code, _ := r.Register("bench unit 1", "ALPHA", "ALPHA", true, now, nil)
	if reg.State != Pending || len(code) != 9 {
		t.Fatalf("bad registration %+v %q", reg, code)
	}
	if _, _, err := r.Claim("WRONG-CODE", nil, "acct", "ip1", now); err != ErrBadClaim {
		t.Fatalf("wrong code accepted: %v", err)
	}
	got, tok, err := r.Claim(lower(code), []byte("pk"), "acct", "ip1", now) // case/dash insensitive
	if err != nil || got.ID != reg.ID {
		t.Fatalf("claim failed: %v", err)
	}
	if _, _, err := r.Claim(code, nil, "acct", "ip1", now); err != ErrBadClaim {
		t.Fatal("claim code reusable")
	}
	if _, err := r.Authenticate(reg.ID, tok); err != nil {
		t.Fatalf("valid token rejected: %v", err)
	}
	if _, err := r.Authenticate(reg.ID, "nope"); err == nil {
		t.Fatal("bad token accepted")
	}
	r.Revoke(reg.ID)
	if _, err := r.Authenticate(reg.ID, tok); err != ErrRevoked {
		t.Fatalf("revoked device still authenticates: %v", err)
	}
}

func lower(s string) string {
	b := []byte(s)
	for i, c := range b {
		if c >= 'A' && c <= 'Z' {
			b[i] = c + 32
		}
	}
	return string(b)
}

func TestExpiryAndRateLimit(t *testing.T) {
	r := New()
	now := time.Now()
	_, code, _ := r.Register("x", "BETA", "BETA", false, now, nil)
	if _, _, err := r.Claim(code, nil, "a", "ip", now.Add(8*24*time.Hour)); err != ErrBadClaim {
		t.Fatalf("expired code accepted: %v", err)
	}
	r2 := New()
	_, code2, _ := r2.Register("x", "BETA", "BETA", false, now, nil)
	for i := 0; i < 5; i++ {
		r2.Claim("AAAA-AAAA", nil, "a", "ip", now)
	}
	if _, _, err := r2.Claim(code2, nil, "a", "ip", now); err != ErrRateLimit {
		t.Fatalf("guessing not rate limited: %v", err)
	}
}

func TestBenchOnlyForAlpha(t *testing.T) {
	r := New()
	reg, _, _ := r.Register("x", "BETA", "BETA", true, time.Now(), nil)
	if reg.Bench {
		t.Fatal("beta device flagged bench")
	}
}
