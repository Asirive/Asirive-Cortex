package server

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/asirive/cortex/gateway/internal/fleet"
	"github.com/asirive/cortex/gateway/internal/mail"
)

type inbox struct {
	mu   sync.Mutex
	msgs []string
}

func (i *inbox) Send(to, subj, text string) error {
	i.mu.Lock()
	i.msgs = append(i.msgs, to+"|"+text)
	i.mu.Unlock()
	return nil
}
func (i *inbox) last(t *testing.T) string {
	t.Helper()
	for n := 0; n < 50; n++ {
		i.mu.Lock()
		if len(i.msgs) > 0 {
			m := i.msgs[len(i.msgs)-1]
			i.mu.Unlock()
			return m
		}
		i.mu.Unlock()
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("no email sent")
	return ""
}
func (i *inbox) count() int { i.mu.Lock(); defer i.mu.Unlock(); return len(i.msgs) }

var tokRe = regexp.MustCompile(`token=(mt_[0-9a-f]+)`)

func del(t *testing.T, url, token string, body any) int {
	b, _ := json.Marshal(body)
	req, _ := http.NewRequest("DELETE", url, strings.NewReader(string(b)))
	req.Header.Set("Authorization", "Bearer "+token)
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	res.Body.Close()
	return res.StatusCode
}

func put(t *testing.T, url, token string, body any) (int, map[string]any) {
	b, _ := json.Marshal(body)
	req, _ := http.NewRequest("PUT", url, strings.NewReader(string(b)))
	req.Header.Set("Authorization", "Bearer "+token)
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	var out map[string]any
	json.NewDecoder(res.Body).Decode(&out)
	return res.StatusCode, out
}

func TestAccountLifecycle(t *testing.T) {
	s := New(fleet.New(), "boot")
	in := &inbox{}
	s.Mailer = in
	ts := httptest.NewServer(s.Handler())
	defer ts.Close()
	u := ts.URL + "/v1"

	if c, _ := post(t, u+"/auth/register", "", map[string]any{"email": "nope", "password": "longenough123"}); c != 400 {
		t.Fatalf("bad email accepted: %d", c)
	}
	if c, _ := post(t, u+"/auth/register", "", map[string]any{"email": "a@example.com", "password": "short"}); c != 400 {
		t.Fatalf("weak password accepted: %d", c)
	}
	c1, r1 := post(t, u+"/auth/register", "", map[string]any{"email": "Sam@Example.com", "password": "correct horse battery"})
	if c1 != 200 {
		t.Fatal(c1, r1)
	}
	verify := tokRe.FindStringSubmatch(in.last(t))[1]

	// unverified cannot sign in
	if c, _ := post(t, u+"/auth/login", "", map[string]any{"email": "sam@example.com", "password": "correct horse battery"}); c != 403 {
		t.Fatalf("unverified login: %d", c)
	}
	// registering the same email again answers identically and sends no mail
	n := in.count()
	c2, r2 := post(t, u+"/auth/register", "", map[string]any{"email": "sam@example.com", "password": "another password 1"})
	time.Sleep(100 * time.Millisecond)
	if c2 != 200 || r2["result"] != r1["result"] || in.count() != n {
		t.Fatalf("registration leaks whether the email exists: %d %v mails %d->%d", c2, r2, n, in.count())
	}
	if c, _ := post(t, u+"/auth/verify", "", map[string]any{"token": "mt_bogus"}); c != 422 {
		t.Fatalf("bogus verify token: %d", c)
	}
	if c, _ := post(t, u+"/auth/verify", "", map[string]any{"token": verify}); c != 200 {
		t.Fatalf("verify: %d", c)
	}
	if c, _ := post(t, u+"/auth/verify", "", map[string]any{"token": verify}); c != 422 {
		t.Fatal("verify token reusable")
	}
	if c, _ := post(t, u+"/auth/login", "", map[string]any{"email": "sam@example.com", "password": "wrong password!"}); c != 401 {
		t.Fatalf("wrong password: %d", c)
	}
	c, l := post(t, u+"/auth/login", "", map[string]any{"email": "sam@example.com", "password": "correct horse battery"})
	if c != 200 {
		t.Fatalf("login: %d %v", c, l)
	}
	tok := l["token"].(string)
	if c, _ := get(t, u+"/me", tok); c != 200 {
		t.Fatalf("me: %d", c)
	}
	if c, _ := get(t, u+"/me", "ses_forged"); c != 401 {
		t.Fatalf("forged session: %d", c)
	}
	// an app session is not an operator token
	if c, _ := get(t, ts.URL+"/api/devices", tok); c != 401 {
		t.Fatalf("app session reached the fleet console: %d", c)
	}

	// claiming a device needs a session, and the account owns it afterwards
	_, reg := post(t, ts.URL+"/api/registrations", "boot", map[string]any{"tier": "STABLE", "label": "Sam's glasses"})
	code := reg["claim_code"]
	if c, _ := post(t, u+"/claim", "", map[string]any{"claim_code": code}); c != 401 {
		t.Fatalf("anonymous claim: %d", c)
	}
	c, cl := post(t, u+"/claim", tok, map[string]any{"claim_code": code})
	if c != 200 {
		t.Fatalf("claim: %d %v", c, cl)
	}
	devID, devTok := cl["device_id"].(string), cl["device_token"].(string)
	_, dl := get(t, u+"/me/devices", tok)
	if !strings.Contains(string(dl), devID) {
		t.Fatalf("device not listed for owner: %s", dl)
	}
	// another account sees nothing
	other := login(t, s, "other@example.com")
	_, dl2 := get(t, u+"/me/devices", other)
	if strings.Contains(string(dl2), devID) {
		t.Fatal("device visible to a different account")
	}

	// beta opt-in needs consent; moves the device; opt-out moves it back
	if c, _ := put(t, u+"/me/beta", tok, map[string]any{"enabled": true}); c != 400 {
		t.Fatalf("beta without consent: %d", c)
	}
	if c, r := put(t, u+"/me/beta", tok, map[string]any{"enabled": true, "consent_version": BetaConsentVersion}); c != 200 {
		t.Fatalf("beta on: %d %v", c, r)
	}
	if rg, _ := s.Reg.Get(devID); rg.Tier != "BETA" || rg.Ring != "BETA" {
		t.Fatalf("device channel not moved: %+v", rg)
	}
	put(t, u+"/me/beta", tok, map[string]any{"enabled": false})
	if rg, _ := s.Reg.Get(devID); rg.Tier != "STABLE" {
		t.Fatal("opt-out did not move the device back")
	}
	// an alpha device never changes channel
	_, ar := post(t, ts.URL+"/api/registrations", "boot", map[string]any{"tier": "ALPHA", "label": "bench", "bench": true})
	post(t, u+"/claim", tok, map[string]any{"claim_code": ar["claim_code"]})
	put(t, u+"/me/beta", tok, map[string]any{"enabled": true, "consent_version": BetaConsentVersion})
	for _, d := range s.Reg.ListByAccount(l["account"].(map[string]any)["id"].(string)) {
		if d.Bench && d.Tier != "ALPHA" {
			t.Fatal("beta toggle touched an alpha device")
		}
	}

	// password reset kills sessions and the old password
	post(t, u+"/auth/reset-request", "", map[string]any{"email": "sam@example.com"})
	rt := tokRe.FindStringSubmatch(in.last(t))[1]
	if c, _ := post(t, u+"/auth/reset", "", map[string]any{"token": rt, "password": "brand new password"}); c != 200 {
		t.Fatalf("reset: %d", c)
	}
	if c, _ := get(t, u+"/me", tok); c != 401 {
		t.Fatal("old session survived a password reset")
	}
	if c, _ := post(t, u+"/auth/login", "", map[string]any{"email": "sam@example.com", "password": "correct horse battery"}); c != 401 {
		t.Fatal("old password still works")
	}
	_, l = post(t, u+"/auth/login", "", map[string]any{"email": "sam@example.com", "password": "brand new password"})
	tok = l["token"].(string)

	// deletion needs the password, then kills the account, session and devices
	if c := del(t, u+"/me", tok, map[string]any{"password": "wrong"}); c != 401 {
		t.Fatalf("delete with wrong password: %d", c)
	}
	if c := del(t, u+"/me", tok, map[string]any{"password": "brand new password"}); c != 200 {
		t.Fatalf("delete: %d", c)
	}
	if c, _ := get(t, u+"/me", tok); c != 401 {
		t.Fatal("session survived deletion")
	}
	if c, _ := post(t, u+"/auth/login", "", map[string]any{"email": "sam@example.com", "password": "brand new password"}); c != 401 {
		t.Fatal("deleted account can log in")
	}
	if _, _, err := dial(t, ts, devID, devTok); err == nil {
		t.Fatal("deleted account's device still connects")
	}
}

func TestLoginRateLimit(t *testing.T) {
	s := New(fleet.New(), "boot")
	ts := httptest.NewServer(s.Handler())
	defer ts.Close()
	login(t, s, "v@example.com")
	var last int
	for i := 0; i < 12; i++ {
		last, _ = post(t, ts.URL+"/v1/auth/login", "", map[string]any{"email": "v@example.com", "password": "guess guess guess"})
	}
	if last != 429 {
		t.Fatalf("no lockout after repeated failures: %d", last)
	}
	if c, _ := post(t, ts.URL+"/v1/auth/login", "", map[string]any{"email": "v@example.com", "password": "correct horse battery"}); c != 429 {
		t.Fatal("correct password bypassed the lockout")
	}
}

func TestAccountsSurviveRestartWithoutPlaintext(t *testing.T) {
	s := New(fleet.New(), "boot")
	tok := login(t, s, "r@example.com")
	path := t.TempDir() + "/s.json"
	s.SaveState(path)
	raw, _ := os.ReadFile(path)
	if strings.Contains(string(raw), "correct horse battery") || strings.Contains(string(raw), tok) {
		t.Fatal("password or session token stored in the clear")
	}
	s2 := New(fleet.New(), "boot")
	if err := s2.LoadState(path); err != nil {
		t.Fatal(err)
	}
	ts := httptest.NewServer(s2.Handler())
	defer ts.Close()
	if c, _ := get(t, ts.URL+"/v1/me", tok); c != 200 {
		t.Fatalf("session lost on restart: %d", c)
	}
	if c, _ := post(t, ts.URL+"/v1/auth/login", "", map[string]any{"email": "r@example.com", "password": "correct horse battery"}); c != 200 {
		t.Fatalf("login after restart: %d", c)
	}
}

func TestResendMailer(t *testing.T) {
	var got map[string]any
	var auth string
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		auth = r.Header.Get("Authorization")
		b, _ := io.ReadAll(r.Body)
		json.Unmarshal(b, &got)
		w.Write([]byte(`{"id":"x"}`))
	}))
	defer fake.Close()
	m := &mail.Resend{APIKey: "re_test", From: "Asirive <no-reply@asirive.com>", Endpoint: fake.URL}
	if err := m.Send("a@b.com", "Hi", "body"); err != nil {
		t.Fatal(err)
	}
	if auth != "Bearer re_test" || got["from"] != "Asirive <no-reply@asirive.com>" || got["subject"] != "Hi" {
		t.Fatalf("bad request to Resend: %v %s", got, auth)
	}
	bad := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(422) }))
	defer bad.Close()
	if (&mail.Resend{APIKey: "k", From: "f", Endpoint: bad.URL}).Send("a@b.com", "s", "t") == nil {
		t.Fatal("provider error swallowed")
	}
}
