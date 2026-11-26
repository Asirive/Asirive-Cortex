// Package gemini is the gateway's second-opinion proxy: when the box's local model is not sure, the box sends
// the current camera frame and the question here, and the gateway asks Gemini (generateContent) with the
// server's key. The key never leaves the server. Frames and questions are passed through, never stored or logged.
package gemini

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

const (
	DefaultBase  = "https://generativelanguage.googleapis.com/v1beta"
	DefaultModel = "gemini-2.5-flash"
	MaxQuestion  = 500
	MaxImage     = 1 << 20 // 1 MB; a 640x360 frame is ~30-60 kB
	MaxAnswer    = 400
)

var (
	ErrNoKey    = errors.New("second opinion not configured")
	ErrBadInput = errors.New("bad second-opinion request")
	ErrUpstream = errors.New("gemini did not answer")
)

// System holds Cortex's speaking rules (core/AGENTS.md section 3): the answer is spoken to a blind user as is.
const System = "You are Cortex, a voice assistant on smart glasses worn by a blind or low-vision person in " +
	"Singapore. The image is what their camera sees right now. Answer the question in at most two short " +
	"spoken sentences, plain text, no lists or markdown. Give positions relative to the user (in front of you, " +
	"on your left, at 2 o'clock); never use colour as the only way to identify something. If the image does not " +
	"show what is needed to answer, say so plainly instead of guessing."

type Client struct {
	Key   string
	Base  string
	Model string
	HTTP  *http.Client
}

func New(key string) *Client {
	return &Client{Key: strings.TrimSpace(key), Base: DefaultBase, Model: DefaultModel,
		HTTP: &http.Client{Timeout: 12 * time.Second}}
}

type part struct {
	Text       string      `json:"text,omitempty"`
	InlineData *inlineData `json:"inlineData,omitempty"`
}

type inlineData struct {
	MimeType string `json:"mimeType"`
	Data     string `json:"data"`
}

// Ask returns Gemini's spoken answer to question about jpeg (nil: no image, e.g. the camera is off).
func (c *Client) Ask(ctx context.Context, question string, jpeg []byte) (string, error) {
	if c == nil || c.Key == "" {
		return "", ErrNoKey
	}
	q := strings.TrimSpace(question)
	if q == "" || len(q) > MaxQuestion {
		return "", fmt.Errorf("%w: question empty or over %d bytes", ErrBadInput, MaxQuestion)
	}
	if jpeg != nil && (len(jpeg) > MaxImage || len(jpeg) < 4 || jpeg[0] != 0xFF || jpeg[1] != 0xD8) {
		return "", fmt.Errorf("%w: image is not a JPEG under 1 MB", ErrBadInput)
	}
	parts := []part{}
	if jpeg != nil {
		parts = append(parts, part{InlineData: &inlineData{"image/jpeg", base64.StdEncoding.EncodeToString(jpeg)}})
	}
	parts = append(parts, part{Text: q})
	body, _ := json.Marshal(map[string]any{
		"systemInstruction": map[string]any{"parts": []part{{Text: System}}},
		"contents":          []any{map[string]any{"role": "user", "parts": parts}},
		"generationConfig":  map[string]any{"temperature": 0.2, "maxOutputTokens": 200},
	})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost,
		strings.TrimRight(c.Base, "/")+"/models/"+c.Model+":generateContent", bytes.NewReader(body))
	if err != nil {
		return "", fmt.Errorf("%w: %v", ErrUpstream, err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("x-goog-api-key", c.Key)
	res, err := c.HTTP.Do(req)
	if err != nil {
		return "", fmt.Errorf("%w: %v", ErrUpstream, err)
	}
	defer res.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(res.Body, 1<<20))
	if res.StatusCode != http.StatusOK {
		return "", fmt.Errorf("%w: HTTP %d", ErrUpstream, res.StatusCode)
	}
	var out struct {
		Candidates []struct {
			Content struct {
				Parts []struct {
					Text string `json:"text"`
				} `json:"parts"`
			} `json:"content"`
		} `json:"candidates"`
	}
	if err := json.Unmarshal(raw, &out); err != nil {
		return "", fmt.Errorf("%w: bad JSON", ErrUpstream)
	}
	var sb strings.Builder
	if len(out.Candidates) > 0 {
		for _, p := range out.Candidates[0].Content.Parts {
			sb.WriteString(p.Text)
		}
	}
	text := strings.Join(strings.Fields(sb.String()), " ")
	if text == "" {
		return "", fmt.Errorf("%w: empty or blocked answer", ErrUpstream)
	}
	return cut(text), nil
}

// cut keeps whole sentences up to MaxAnswer bytes (a hard cut only when the first sentence is longer).
func cut(s string) string {
	if len(s) <= MaxAnswer {
		return s
	}
	head := s[:MaxAnswer]
	if i := strings.LastIndexAny(head, ".!?"); i > 0 {
		return head[:i+1]
	}
	return strings.TrimSpace(head)
}
