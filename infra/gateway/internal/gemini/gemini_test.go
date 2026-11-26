package gemini

import (
	"context"
	"encoding/base64"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

var jpeg = append([]byte{0xFF, 0xD8, 0xFF, 0xE0}, make([]byte, 100)...)

// fakeLive plays the Live API the way gemini-3.8-live-extended-thinking was seen to on 2026-11-26: setupComplete,
// then per utterance transcription fragments + audio, generationComplete, turnComplete with interactionStatus
// IN_PROGRESS (more coming) or IDLE (done).
type fakeLive struct {
	t          *testing.T
	utterances [][]string // fragments per utterance
	setup      map[string]any
	turn       map[string]any
	header     string
	query      string
	closeEarly bool
	delay      time.Duration
}

func (f *fakeLive) start() *httptest.Server {
	up := websocket.Upgrader{}
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.header, f.query = r.Header.Get("x-goog-api-key"), r.URL.RawQuery
		if f.header != "g-key" {
			w.WriteHeader(403)
			return
		}
		c, err := up.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer c.Close()
		c.ReadJSON(&f.setup)
		c.WriteJSON(map[string]any{"setupComplete": map[string]any{}})
		c.ReadJSON(&f.turn)
		if f.closeEarly {
			return
		}
		time.Sleep(f.delay)
		for i, u := range f.utterances {
			for _, frag := range u {
				c.WriteJSON(map[string]any{"serverContent": map[string]any{
					"modelTurn":           map[string]any{"parts": []any{map[string]any{"inlineData": map[string]any{"mimeType": "audio/pcm;rate=24000", "data": "AAAA"}}}},
					"outputTranscription": map[string]any{"text": frag}}})
			}
			status := "IN_PROGRESS"
			if i == len(f.utterances)-1 {
				status = "IDLE"
			}
			c.WriteJSON(map[string]any{"serverContent": map[string]any{"generationComplete": true}})
			c.WriteJSON(map[string]any{"serverContent": map[string]any{"turnComplete": true, "interactionStatus": status}})
		}
		c.ReadMessage() // wait for the client to hang up
	}))
}

func client(srv *httptest.Server) *Client {
	c := New("g-key")
	c.Base = "ws" + strings.TrimPrefix(srv.URL, "http")
	return c
}

func collect(c *Client, q string, frames [][]byte) ([]string, string, error) {
	var said []string
	ans, err := c.Ask(context.Background(), q, frames, func(s string) { said = append(said, s) })
	return said, ans, err
}

func TestAskStreamsSentencesFromTheLiveSession(t *testing.T) {
	f := &fakeLive{t: t, utterances: [][]string{{"This is bus ", "858, moving to ", "your left. The pole", " is at 10 o'clock."}}}
	srv := f.start()
	defer srv.Close()
	said, ans, err := collect(client(srv), "which bus is this", [][]byte{jpeg, jpeg, jpeg})
	if err != nil {
		t.Fatal(err)
	}
	if len(said) != 2 || said[0] != "This is bus 858, moving to your left." || said[1] != "The pole is at 10 o'clock." {
		t.Fatalf("said %q", said)
	}
	if ans != "This is bus 858, moving to your left. The pole is at 10 o'clock." {
		t.Fatalf("answer %q", ans)
	}
	if f.query != "" {
		t.Fatalf("key or anything else in the URL: %q", f.query)
	}
	s := f.setup["setup"].(map[string]any)
	gc := s["generationConfig"].(map[string]any)
	if s["model"] != "models/"+DefaultModel || gc["thinkingConfig"].(map[string]any)["thinkingLevel"] != "LOW" ||
		gc["responseModalities"].([]any)[0] != "AUDIO" || s["outputAudioTranscription"] == nil {
		t.Fatalf("setup %v", s)
	}
	sys := s["systemInstruction"].(map[string]any)["parts"].([]any)[0].(map[string]any)["text"].(string)
	if !strings.Contains(sys, "blind") || !strings.Contains(sys, "never invent") {
		t.Fatalf("system %q", sys)
	}
	cc := f.turn["clientContent"].(map[string]any)
	if cc["turnComplete"] != true {
		t.Fatal("turn not complete")
	}
	parts := cc["turns"].([]any)[0].(map[string]any)["parts"].([]any)
	imgs := 0
	for _, p := range parts {
		if d, ok := p.(map[string]any)["inlineData"].(map[string]any); ok {
			imgs++
			if d["mimeType"] != "image/jpeg" || d["data"] != base64.StdEncoding.EncodeToString(jpeg) {
				t.Fatalf("frame part %v", d)
			}
		}
	}
	if imgs != 3 || parts[len(parts)-1].(map[string]any)["text"] != "which bus is this" {
		t.Fatalf("turn parts %v", parts)
	}
	if !strings.Contains(parts[0].(map[string]any)["text"].(string), "oldest first") {
		t.Fatalf("frames not introduced: %v", parts[0])
	}
}

func TestAskWaitsForIdleAcrossUtterances(t *testing.T) {
	f := &fakeLive{t: t, utterances: [][]string{{"The bus is "}, {"858"}}} // no full stop: flushed at turnComplete
	srv := f.start()
	defer srv.Close()
	said, ans, err := collect(client(srv), "q", nil)
	if err != nil || len(said) != 2 || said[0] != "The bus is" || said[1] != "858" || ans != "The bus is 858" {
		t.Fatalf("%q %q %v", said, ans, err)
	}
	if parts := f.turn["clientContent"].(map[string]any)["turns"].([]any)[0].(map[string]any)["parts"].([]any); len(parts) != 1 {
		t.Fatalf("no frames: parts %v", parts)
	}
}

func TestLongAnswerStopsAtTheCap(t *testing.T) {
	f := &fakeLive{t: t, utterances: [][]string{{strings.Repeat("This is a sentence. ", 60)}}}
	srv := f.start()
	defer srv.Close()
	said, ans, err := collect(client(srv), "q", nil)
	if err != nil || len(ans) > MaxAnswer || len(said) == 0 || !strings.HasSuffix(ans, ".") {
		t.Fatalf("%d %q %v", len(ans), ans, err)
	}
}

func TestErrors(t *testing.T) {
	if _, err := New("").Ask(context.Background(), "q", nil, nil); !errors.Is(err, ErrNoKey) {
		t.Fatalf("no key: %v", err)
	}
	c := New("g-key")
	c.Base = "ws://127.0.0.1:1"
	tooMany := make([][]byte, MaxFrames+1)
	for i := range tooMany {
		tooMany[i] = jpeg
	}
	for _, tc := range []struct {
		q      string
		frames [][]byte
	}{{"", nil}, {"   ", nil}, {strings.Repeat("x", MaxQuestion+1), nil}, {"q", [][]byte{[]byte("not a jpeg")}},
		{"q", [][]byte{append([]byte{0xFF, 0xD8}, make([]byte, MaxFrame)...)}}, {"q", tooMany}} {
		if _, err := c.Ask(context.Background(), tc.q, tc.frames, nil); !errors.Is(err, ErrBadInput) {
			t.Fatalf("bad input %d frames: %v", len(tc.frames), err)
		}
	}
	if _, err := c.Ask(context.Background(), "q", nil, nil); !errors.Is(err, ErrUpstream) {
		t.Fatalf("unreachable: %v", err)
	}
	f := &fakeLive{t: t, closeEarly: true}
	srv := f.start()
	if _, _, err := collect(client(srv), "q", nil); !errors.Is(err, ErrUpstream) {
		t.Fatalf("closed without an answer: %v", err)
	}
	srv.Close()
	bad := New("wrong")
	f = &fakeLive{t: t}
	srv = f.start()
	defer srv.Close()
	bad.Base = "ws" + strings.TrimPrefix(srv.URL, "http")
	if _, err := bad.Ask(context.Background(), "q", nil, nil); !errors.Is(err, ErrUpstream) {
		t.Fatalf("refused key: %v", err)
	}
	slow := &fakeLive{t: t, utterances: [][]string{{"late."}}, delay: 300 * time.Millisecond}
	srv2 := slow.start()
	defer srv2.Close()
	c2 := client(srv2)
	c2.Timeout = 100 * time.Millisecond
	if _, _, err := collect(c2, "q", nil); !errors.Is(err, ErrUpstream) {
		t.Fatalf("timeout: %v", err)
	}
}

func TestSentences(t *testing.T) {
	var s splitter
	var out []string
	emit := func(x string) { out = append(out, x) }
	s.add("Bus 858 is here. It is ", emit)
	s.add("moving! Pole on the left", emit)
	s.flush(emit)
	want := []string{"Bus 858 is here.", "It is moving!", "Pole on the left"}
	if strings.Join(out, "|") != strings.Join(want, "|") {
		t.Fatalf("%q", out)
	}
}
