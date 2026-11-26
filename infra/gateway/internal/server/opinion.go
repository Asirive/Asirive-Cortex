package server

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/asirive/cortex/gateway/internal/gemini"
)

// The Gemini second opinion for the box, on the device (mTLS) listener only. When the box's local model is not
// sure, a claimed, unrevoked device sends
//
//	POST /device/second-opinion  {"question": "...", "image_jpeg": "<base64>"}   (image_jpeg empty: no image)
//
// and gets {"answer": "..."}: at most two spoken sentences, said to the user as is. The Gemini key stays here.
// Frames and questions are passed through, never stored or logged. Cost caps per device: opinionPerMin a minute
// and opinionPerDay a day.
const (
	opinionPerMin = 6
	opinionPerDay = 100
	opinionBody   = 2 << 20 // base64 of a 1 MB image plus the question
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
		Question  string `json:"question"`
		ImageJPEG string `json:"image_jpeg"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, opinionBody)).Decode(&req); err != nil {
		writeErr(w, http.StatusBadRequest, "bad_request", "Bad second-opinion request.")
		return
	}
	var img []byte
	if req.ImageJPEG != "" {
		b, err := base64.StdEncoding.DecodeString(req.ImageJPEG)
		if err != nil {
			writeErr(w, http.StatusBadRequest, "bad_image", "The image is not base64.")
			return
		}
		img = b
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
	ans, err := s.Gemini.Ask(r.Context(), req.Question, img)
	switch {
	case errors.Is(err, gemini.ErrBadInput):
		writeErr(w, http.StatusBadRequest, "bad_request", "Question empty or too long, or the image is not a JPEG under 1 MB.")
		return
	case err != nil:
		writeErr(w, http.StatusBadGateway, "opinion_failed", "Gemini did not answer.")
		return
	}
	writeJSON(w, map[string]any{"answer": ans})
}
