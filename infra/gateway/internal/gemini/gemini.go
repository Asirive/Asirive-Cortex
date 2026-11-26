// Package gemini is the gateway's second-opinion proxy. When the box's local model is not sure, the box sends a
// short clip of camera frames (oldest first, about a second apart) and the question; the gateway opens a Gemini Live
// session (gemini-3.8-live-extended-thinking, thinking LOW) with the server's key and streams the answer back
// sentence by sentence. The key never leaves the server and never goes in a URL. Frames and questions are passed
// through, never stored or logged.
//
// Measured against the real API on 2026-11-26 (synthetic bus-stop frames, 3 runs each):
//   - the model only answers in AUDIO (TEXT is refused), so the answer is its output transcription;
//   - frames sent in a burst on realtimeInput.video are not seen; paced at 1/s they are, but that costs ~1 s per
//     frame before the question. Frames inline in the turn (clientContent) are seen at once: first words 1.1-2.2 s
//     after the question, motion between frames understood;
//   - an answer can span several utterances: turnComplete with interactionStatus IN_PROGRESS means more is coming,
//     IDLE means done. Without "never invent" in the system instruction it once made up a London bus route.
package gemini

import (
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"
	"unicode"

	"github.com/gorilla/websocket"
)

const (
	DefaultBase     = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
	DefaultModel    = "gemini-3.8-live-extended-thinking"
	DefaultThinking = "LOW"
	MaxQuestion     = 500
	MaxFrames       = 6
	MaxFrame        = 512 << 10 // a 640x360 frame is ~30-60 kB
	MaxAnswer       = 400
)

var (
	ErrNoKey    = errors.New("second opinion not configured")
	ErrBadInput = errors.New("bad second-opinion request")
	ErrUpstream = errors.New("gemini did not answer")
)

// System holds Cortex's speaking rules (core/AGENTS.md section 3); the answer is spoken to a blind user as is.
const System = "You are Cortex, the voice of smart glasses worn by a blind or low-vision person in Singapore. The " +
	"frames are the last few seconds from their camera, oldest first, about one second apart. Answer the question " +
	"in at most two short sentences. Say only what the frames show: never invent numbers, names, routes or " +
	"destinations you cannot read. Give positions relative to the user (left, right, ahead, clock positions); never " +
	"use colour as the only way to identify something. Do not say filler like 'let me check'. If the frames do not " +
	"show the answer, say so in one sentence."

type Client struct {
	Key      string
	Base     string // the Live WebSocket endpoint
	Model    string
	Thinking string        // LOW, MEDIUM or HIGH ("" = not sent, for models without thinking)
	Timeout  time.Duration // whole session, connect to the last sentence
}

func New(key string) *Client {
	return &Client{Key: strings.TrimSpace(key), Base: DefaultBase, Model: DefaultModel, Thinking: DefaultThinking,
		Timeout: 25 * time.Second}
}

type part struct {
	Text       string      `json:"text,omitempty"`
	InlineData *inlineData `json:"inlineData,omitempty"`
}

type inlineData struct {
	MimeType string `json:"mimeType"`
	Data     string `json:"data"`
}

type serverMsg struct {
	SetupComplete *struct{} `json:"setupComplete"`
	ServerContent *struct {
		OutputTranscription *struct {
			Text string `json:"text"`
		} `json:"outputTranscription"`
		TurnComplete      bool   `json:"turnComplete"`
		InteractionStatus string `json:"interactionStatus"`
	} `json:"serverContent"`
	InteractionStatus string    `json:"interactionStatus"` // docs disagree on where it sits; accept both
	GoAway            *struct{} `json:"goAway"`
}

// Ask asks Gemini about frames (JPEG, oldest first; none: the camera is off) and calls say with each finished
// sentence as it is transcribed. It returns the whole answer.
func (c *Client) Ask(ctx context.Context, question string, frames [][]byte, say func(string)) (string, error) {
	if c == nil || c.Key == "" {
		return "", ErrNoKey
	}
	q := strings.TrimSpace(question)
	if q == "" || len(q) > MaxQuestion {
		return "", fmt.Errorf("%w: question empty or over %d bytes", ErrBadInput, MaxQuestion)
	}
	if len(frames) > MaxFrames {
		return "", fmt.Errorf("%w: more than %d frames", ErrBadInput, MaxFrames)
	}
	for _, f := range frames {
		if len(f) > MaxFrame || len(f) < 4 || f[0] != 0xFF || f[1] != 0xD8 {
			return "", fmt.Errorf("%w: a frame is not a JPEG under %d kB", ErrBadInput, MaxFrame>>10)
		}
	}
	if say == nil {
		say = func(string) {}
	}
	ctx, cancel := context.WithTimeout(ctx, c.Timeout)
	defer cancel()
	d := websocket.Dialer{HandshakeTimeout: 8 * time.Second}
	conn, res, err := d.DialContext(ctx, c.Base, http.Header{"x-goog-api-key": {c.Key}})
	if err != nil {
		if res != nil {
			return "", fmt.Errorf("%w: handshake HTTP %d", ErrUpstream, res.StatusCode)
		}
		return "", fmt.Errorf("%w: %v", ErrUpstream, errors.Unwrap(err))
	}
	defer conn.Close()
	stop := context.AfterFunc(ctx, func() { conn.Close() }) // a timeout ends a blocked read
	defer stop()

	gen := map[string]any{"responseModalities": []string{"AUDIO"}}
	if c.Thinking != "" {
		gen["thinkingConfig"] = map[string]any{"thinkingLevel": c.Thinking}
	}
	setup := map[string]any{"setup": map[string]any{
		"model": "models/" + c.Model, "generationConfig": gen,
		"systemInstruction":        map[string]any{"parts": []part{{Text: System}}},
		"outputAudioTranscription": map[string]any{},
	}}
	if err := conn.WriteJSON(setup); err != nil {
		return "", fmt.Errorf("%w: setup", ErrUpstream)
	}
	var m serverMsg
	if err := conn.ReadJSON(&m); err != nil || m.SetupComplete == nil {
		return "", fmt.Errorf("%w: setup refused", ErrUpstream)
	}
	parts := []part{}
	if len(frames) > 0 {
		parts = append(parts, part{Text: fmt.Sprintf("%d camera frames, oldest first, about one second apart:", len(frames))})
		for _, f := range frames {
			parts = append(parts, part{InlineData: &inlineData{"image/jpeg", base64.StdEncoding.EncodeToString(f)}})
		}
	}
	parts = append(parts, part{Text: q})
	turn := map[string]any{"clientContent": map[string]any{
		"turns": []any{map[string]any{"role": "user", "parts": parts}}, "turnComplete": true}}
	if err := conn.WriteJSON(turn); err != nil {
		return "", fmt.Errorf("%w: send", ErrUpstream)
	}

	var sp splitter
	var all []string
	total := 0
	full := false
	emit := func(s string) {
		if full {
			return
		}
		if total+len(s)+1 > MaxAnswer {
			full = true
			return
		}
		total += len(s) + 1
		all = append(all, s)
		say(s)
	}
	thinking := strings.Contains(c.Model, "extended-thinking")
	for !full {
		m = serverMsg{}
		if err := conn.ReadJSON(&m); err != nil {
			if len(all) > 0 { // cut after speaking something: keep what was said
				break
			}
			return "", fmt.Errorf("%w: session ended without an answer", ErrUpstream)
		}
		sc := m.ServerContent
		if sc == nil {
			continue
		}
		if sc.OutputTranscription != nil {
			sp.add(sc.OutputTranscription.Text, emit)
		}
		if sc.TurnComplete {
			sp.flush(emit)
			status := sc.InteractionStatus
			if status == "" {
				status = m.InteractionStatus
			}
			if status == "IDLE" || (!thinking && status == "") {
				break
			}
		}
	}
	if len(all) == 0 {
		return "", fmt.Errorf("%w: empty answer", ErrUpstream)
	}
	return strings.Join(all, " "), nil
}

// splitter turns transcription fragments into whole sentences: a sentence ends at . ! or ? followed by a space.
type splitter struct{ buf string }

func (s *splitter) add(frag string, emit func(string)) {
	s.buf += frag
	for {
		cut := -1
		for i := 0; i+1 < len(s.buf); i++ {
			if strings.ContainsRune(".!?", rune(s.buf[i])) && unicode.IsSpace(rune(s.buf[i+1])) {
				cut = i + 1
				break
			}
		}
		if cut < 0 {
			return
		}
		if t := strings.Join(strings.Fields(s.buf[:cut]), " "); t != "" {
			emit(t)
		}
		s.buf = s.buf[cut:]
	}
}

func (s *splitter) flush(emit func(string)) {
	if t := strings.Join(strings.Fields(s.buf), " "); t != "" {
		emit(t)
	}
	s.buf = ""
}
