package gemini

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

var jpeg = append([]byte{0xFF, 0xD8, 0xFF, 0xE0}, make([]byte, 100)...)

func fake(t *testing.T, status int, body any, seen *map[string]any) *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("x-goog-api-key") != "g-key" {
			w.WriteHeader(403)
			return
		}
		if r.URL.Path != "/models/test-model:generateContent" || r.Method != http.MethodPost {
			t.Errorf("path %s %s", r.Method, r.URL.Path)
		}
		if strings.Contains(r.URL.RawQuery, "key=") {
			t.Errorf("key in the URL")
		}
		if seen != nil {
			json.NewDecoder(r.Body).Decode(seen)
		}
		w.WriteHeader(status)
		json.NewEncoder(w).Encode(body)
	}))
}

func answer(text string) map[string]any {
	return map[string]any{"candidates": []any{map[string]any{"content": map[string]any{
		"parts": []any{map[string]any{"text": text}}}}}}
}

func client(base string) *Client {
	c := New("g-key")
	c.Base, c.Model = base, "test-model"
	return c
}

func TestAskSendsImageQuestionAndRules(t *testing.T) {
	var seen map[string]any
	srv := fake(t, 200, answer("  A red bus, number 858, right in front of you. "), &seen)
	defer srv.Close()
	got, err := client(srv.URL).Ask(context.Background(), "what bus is this", jpeg)
	if err != nil || got != "A red bus, number 858, right in front of you." {
		t.Fatalf("%q %v", got, err)
	}
	parts := seen["contents"].([]any)[0].(map[string]any)["parts"].([]any)
	img := parts[0].(map[string]any)["inlineData"].(map[string]any)
	if img["mimeType"] != "image/jpeg" || img["data"] != base64.StdEncoding.EncodeToString(jpeg) {
		t.Fatalf("image part %v", img)
	}
	if parts[1].(map[string]any)["text"] != "what bus is this" {
		t.Fatalf("question part %v", parts[1])
	}
	sys := seen["systemInstruction"].(map[string]any)["parts"].([]any)[0].(map[string]any)["text"].(string)
	if !strings.Contains(sys, "blind") || !strings.Contains(sys, "at most two short") {
		t.Fatalf("system %q", sys)
	}
}

func TestAskWithoutImage(t *testing.T) {
	var seen map[string]any
	srv := fake(t, 200, answer("Paris."), &seen)
	defer srv.Close()
	if got, err := client(srv.URL).Ask(context.Background(), "capital of France?", nil); err != nil || got != "Paris." {
		t.Fatalf("%q %v", got, err)
	}
	if parts := seen["contents"].([]any)[0].(map[string]any)["parts"].([]any); len(parts) != 1 {
		t.Fatalf("parts %v", parts)
	}
}

func TestLongAnswerCutAtASentence(t *testing.T) {
	long := strings.Repeat("This is a sentence. ", 40)
	srv := fake(t, 200, answer(long), nil)
	defer srv.Close()
	got, err := client(srv.URL).Ask(context.Background(), "q", jpeg)
	if err != nil || len(got) > MaxAnswer || !strings.HasSuffix(got, ".") {
		t.Fatalf("%d %q %v", len(got), got, err)
	}
}

func TestErrors(t *testing.T) {
	if _, err := New("").Ask(context.Background(), "q", jpeg); !errors.Is(err, ErrNoKey) {
		t.Fatalf("no key: %v", err)
	}
	c := client("http://127.0.0.1:1")
	for _, tc := range []struct {
		q   string
		img []byte
	}{{"", jpeg}, {"   ", jpeg}, {strings.Repeat("x", MaxQuestion+1), jpeg}, {"q", []byte("not a jpeg")},
		{"q", append([]byte{0xFF, 0xD8}, make([]byte, MaxImage)...)}} {
		if _, err := c.Ask(context.Background(), tc.q, tc.img); !errors.Is(err, ErrBadInput) {
			t.Fatalf("bad input %q: %v", tc.q[:min(len(tc.q), 10)], err)
		}
	}
	for _, body := range []any{map[string]any{"candidates": []any{}}, map[string]any{"promptFeedback": map[string]any{
		"blockReason": "SAFETY"}}, answer("   ")} {
		srv := fake(t, 200, body, nil)
		if _, err := client(srv.URL).Ask(context.Background(), "q", jpeg); !errors.Is(err, ErrUpstream) {
			t.Fatalf("empty %v: %v", body, err)
		}
		srv.Close()
	}
	srv := fake(t, 500, map[string]any{"error": "boom"}, nil)
	defer srv.Close()
	if _, err := client(srv.URL).Ask(context.Background(), "q", jpeg); !errors.Is(err, ErrUpstream) {
		t.Fatalf("500: %v", err)
	}
	if _, err := c.Ask(context.Background(), "q", jpeg); !errors.Is(err, ErrUpstream) {
		t.Fatalf("unreachable: %v", err)
	}
}
