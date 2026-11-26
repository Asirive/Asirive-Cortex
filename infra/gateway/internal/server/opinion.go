package server

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"

	"github.com/asirive/cortex/gateway/internal/gemini"
)

// The Gemini second opinion for the box, on the device (mTLS) listener only. When the box's local model is not
// sure, a claimed, unrevoked device sends
//
//	POST /device/second-opinion  {"question": "...", "frames_jpeg": ["<base64>", ...]}
//
// frames_jpeg is a short clip, oldest first, about a second apart (at most gemini.MaxFrames; none: the camera is
// off). The gateway asks Gemini Live about it and returns {"answer": "..."}: at most two spoken sentences, said to
// the user as is. The Gemini key stays here.
//
// With "Accept: application/x-ndjson" the answer streams instead, one JSON object per line, flushed at once:
// {"sentence": "..."} for each finished sentence once Gemini has started the next one (the box speaks it straight
// away, while Gemini is still talking), then {"done": true, "answer": "<all of it>", "rest": "<the sentences not
// sent as lines, never empty>"}, which the box speaks and records as the template; or, if Gemini fails mid-answer,
// {"error": "opinion_failed"} (what was already said stays said; the box says the rest was lost). Input errors are
// found before the first line and are plain 400s.
// Frames and questions are passed through, never stored or logged. Cost caps per device: opinionPerMin a minute
// and opinionPerDay a day.
const (
	opinionPerMin = 6
	opinionPerDay = 100
	opinionBody   = 5 << 20 // base64 of gemini.MaxFrames frames plus the question
)

func (s *Server) secondOpinion(w http.ResponseWriter, r *http.Request) {
	id := ""
	if r.TLS != nil && len(r.TLS.PeerCertificates) > 0 {
		id = r.TLS.PeerCertificates[0].Subject.CommonName
	}
	if err := s.checkCert(r, id); err != nil {
		writeErr(w, http.StatusUnauthorized, "unauthorized", "Certificate not accepted.")
		return
	}
	if s.Gemini == nil || s.Gemini.Key == "" {
		writeErr(w, http.StatusServiceUnavailable, "opinion_unavailable", "Second opinion is not set up on this gateway.")
		return
	}
	var req struct {
		Question string   `json:"question"`
		Frames   []string `json:"frames_jpeg"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, opinionBody)).Decode(&req); err != nil {
		writeErr(w, http.StatusBadRequest, "bad_request", "Bad second-opinion request.")
		return
	}
	if len(req.Frames) > gemini.MaxFrames {
		writeErr(w, http.StatusBadRequest, "bad_request", "Too many frames.")
		return
	}
	frames := make([][]byte, 0, len(req.Frames))
	for _, f := range req.Frames {
		b, err := base64.StdEncoding.DecodeString(f)
		if err != nil {
			writeErr(w, http.StatusBadRequest, "bad_image", "A frame is not base64.")
			return
		}
		frames = append(frames, b)
	}
	now := time.Now()
	if !s.opinionDaily.allowWithin(id, now, opinionPerDay, 24*time.Hour) {
		writeErr(w, http.StatusTooManyRequests, "daily_limit", "Second-opinion limit for today reached.")
		return
	}
	if !s.opinionRate.allow(id, now, opinionPerMin) {
		writeErr(w, http.StatusTooManyRequests, "rate_limited", "Too many second-opinion requests; try again in a minute.")
		return
	}
	if strings.Contains(r.Header.Get("Accept"), "application/x-ndjson") {
		s.streamOpinion(w, r, req.Question, frames)
		return
	}
	ans, err := s.Gemini.Ask(r.Context(), req.Question, frames, nil)
	switch {
	case errors.Is(err, gemini.ErrBadInput):
		writeErr(w, http.StatusBadRequest, "bad_request", "Question empty or too long, or a frame is not a small JPEG.")
		return
	case err != nil:
		writeErr(w, http.StatusBadGateway, "opinion_failed", "Gemini did not answer.")
		return
	}
	writeJSON(w, map[string]any{"answer": ans})
}

// streamOpinion answers as NDJSON, flushing each sentence the moment Gemini finishes it.
func (s *Server) streamOpinion(w http.ResponseWriter, r *http.Request, question string, frames [][]byte) {
	if err := gemini.Check(question, frames); err != nil {
		writeErr(w, http.StatusBadRequest, "bad_request", "Question empty or too long, or a frame is not a small JPEG.")
		return
	}
	fl, _ := w.(http.Flusher)
	w.Header().Set("Content-Type", "application/x-ndjson")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Accel-Buffering", "no") // a proxy in front must not hold sentences back
	w.WriteHeader(http.StatusOK)
	enc := json.NewEncoder(w)
	line := func(v any) {
		enc.Encode(v)
		if fl != nil {
			fl.Flush()
		}
	}
	var said []string
	ans, err := s.Gemini.Ask(r.Context(), question, frames, func(x string) {
		said = append(said, x)
		line(map[string]string{"sentence": x})
	})
	if err != nil {
		line(map[string]string{"error": "opinion_failed"})
		return
	}
	rest := strings.TrimSpace(strings.TrimPrefix(ans, strings.Join(said, " ")))
	line(map[string]any{"done": true, "answer": ans, "rest": rest})
}
