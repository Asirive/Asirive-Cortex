package server

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/asirive/cortex/gateway/internal/fleet"
)

type htmlInbox struct {
	mu            sync.Mutex
	to, text, htm string
}

func (h *htmlInbox) Send(to, subj, text string) error { return h.SendHTML(to, subj, text, "") }
func (h *htmlInbox) SendHTML(to, subj, text, htm string) error {
	h.mu.Lock()
	h.to, h.text, h.htm = to, text, htm
	h.mu.Unlock()
	return nil
}

func TestVerifyMailIsHTMLWithHTTPSLink(t *testing.T) {
	s := New(fleet.New(), "boot")
	in := &htmlInbox{}
	s.Mailer, s.WebBase = in, "https://infra.example.test"
	ts := httptest.NewServer(s.Handler())
	defer ts.Close()
	if c, r := post(t, ts.URL+"/v1/auth/register", "", map[string]any{"email": "sam@example.com", "password": "correct horse battery"}); c != 200 {
		t.Fatal(c, r)
	}
	deadline := time.Now().Add(2 * time.Second)
	for {
		in.mu.Lock()
		got := in.htm
		in.mu.Unlock()
		if got != "" || time.Now().After(deadline) {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	in.mu.Lock()
	defer in.mu.Unlock()
	if in.htm == "" {
		t.Fatal("no HTML part sent")
	}
	if !strings.Contains(in.htm, `href="https://infra.example.test/v1/link/verify?token=mt_`) {
		t.Fatalf("button is not an https link: %s", in.htm)
	}
	if !strings.Contains(in.htm, "#eaff00") || !strings.Contains(in.text, "https://infra.example.test/v1/link/verify?token=mt_") {
		t.Fatal("theme or plain-text link missing")
	}
	if strings.Contains(in.text, "asirive://") || strings.Contains(in.htm, "asirive://") {
		t.Fatal("custom-scheme link leaked into the email")
	}
}

func TestLinkPageIsSafeAndOnlyKnownKinds(t *testing.T) {
	s := New(fleet.New(), "boot")
	ts := httptest.NewServer(s.Handler())
	defer ts.Close()
	for _, kind := range []string{"verify", "reset"} {
		res, err := http.Get(ts.URL + "/v1/link/" + kind + "?token=mt_abc")
		if err != nil {
			t.Fatal(err)
		}
		b, _ := io.ReadAll(res.Body)
		res.Body.Close()
		if res.StatusCode != 200 || !strings.Contains(string(b), "ASIRIVE") {
			t.Fatalf("%s page: %d", kind, res.StatusCode)
		}
		if strings.Contains(string(b), "mt_abc") {
			t.Fatal("token must never be written into the page")
		}
		if res.Header.Get("Referrer-Policy") != "no-referrer" || res.Header.Get("Cache-Control") != "no-store" || res.Header.Get("Content-Security-Policy") == "" {
			t.Fatalf("%s page missing security headers: %v", kind, res.Header)
		}
	}
	res, _ := http.Get(ts.URL + "/v1/link/evil")
	if res.StatusCode != 404 {
		t.Fatalf("unknown kind served: %d", res.StatusCode)
	}
	res.Body.Close()
}

func TestMailUsesAppBrandAndSurvivesOutlookDarkMode(t *testing.T) {
	h := renderMailHTML(mailKinds["verify"], "https://x.test/v1/link/verify?token=mt_1", "https://x.test")
	for _, want := range []string{
		"#131a14", "#0a0a08", // app surface + ground, not plain grey/black
		"'Anton'", "'Space Grotesk'", "'JetBrains Mono'", "https://x.test/v1/brand/Anton-Regular.ttf",
		"linear-gradient(#eaff00,#eaff00)",           // yellow Outlook will not darken
		"[data-ogsb] .cx-acc", "[data-ogsc] .cx-ink", // and its dark-mode rewrite undone
		"border-radius:28px", "CONFIRM YOUR EMAIL",
	} {
		if !strings.Contains(h, want) {
			t.Errorf("email is missing %q", want)
		}
	}
}

func TestBrandFontsServedWithCORSAndNothingElse(t *testing.T) {
	ts := httptest.NewServer(New(fleet.New(), "boot").Handler())
	defer ts.Close()
	res, err := http.Get(ts.URL + "/v1/brand/Anton-Regular.ttf")
	if err != nil {
		t.Fatal(err)
	}
	b, _ := io.ReadAll(res.Body)
	res.Body.Close()
	if res.StatusCode != 200 || len(b) < 10000 || res.Header.Get("Access-Control-Allow-Origin") != "*" || res.Header.Get("Content-Type") != "font/ttf" {
		t.Fatalf("font: %d %d %v", res.StatusCode, len(b), res.Header)
	}
	for _, p := range []string{"/v1/brand/..%2fmailtpl.go", "/v1/brand/nope.ttf", "/v1/brand/x.go"} {
		r, _ := http.Get(ts.URL + p)
		if r.StatusCode != 404 {
			t.Errorf("%s served: %d", p, r.StatusCode)
		}
		r.Body.Close()
	}
}
