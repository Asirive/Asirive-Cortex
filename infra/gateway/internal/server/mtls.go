package server

import (
	"bytes"
	"crypto/tls"
	"errors"
	"net/http"
	"time"

	"github.com/asirive/cortex/gateway/internal/registry"
)

// DeviceHandler is the ONLY thing served on the device (mTLS) listener: the device
// WebSocket and certificate renewal. The operator API and app API are not reachable here.
func (s *Server) DeviceHandler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/ws/device", s.deviceWS)
	mux.HandleFunc("POST /device/renew", s.renewCert)
	return secure(mux)
}

// checkCert enforces: a CA-verified client certificate (done by the TLS stack), whose
// name is the claimed device id, whose key is the one registered at claim, and a device
// that has not been revoked.
func (s *Server) checkCert(r *http.Request, devID string) error {
	if r.TLS == nil || len(r.TLS.PeerCertificates) == 0 {
		return errors.New("no client certificate")
	}
	leaf := r.TLS.PeerCertificates[0]
	if devID == "" || leaf.Subject.CommonName != devID {
		return errors.New("certificate is for a different device")
	}
	reg, ok := s.Reg.Get(devID)
	if !ok || reg.State != registry.Claimed {
		return errors.New("device not active")
	}
	if want := s.Reg.PubKey(devID); len(want) == 0 || !bytes.Equal(want, leaf.RawSubjectPublicKeyInfo) {
		return errors.New("certificate key does not match the registered key")
	}
	return nil
}

// DeviceTLS builds the listener config: TLS 1.3 only, client certificate required and
// verified against our CA, and revoked/unknown devices refused during the handshake.
func (s *Server) DeviceTLS(serverCert tls.Certificate) *tls.Config {
	return &tls.Config{
		MinVersion:   tls.VersionTLS13,
		Certificates: []tls.Certificate{serverCert},
		ClientAuth:   tls.RequireAndVerifyClientCert,
		ClientCAs:    s.CA.Pool(),
		VerifyConnection: func(cs tls.ConnectionState) error {
			if len(cs.PeerCertificates) == 0 {
				return errors.New("no client certificate")
			}
			id := cs.PeerCertificates[0].Subject.CommonName
			if reg, ok := s.Reg.Get(id); !ok || reg.State != registry.Claimed {
				return errors.New("device not active")
			}
			return nil
		},
	}
}

// renewCert issues a fresh certificate for the same registered key. It needs a still-valid
// certificate; a device whose certificate has expired must be re-claimed.
func (s *Server) renewCert(w http.ResponseWriter, r *http.Request) {
	id := ""
	if r.TLS != nil && len(r.TLS.PeerCertificates) > 0 {
		id = r.TLS.PeerCertificates[0].Subject.CommonName
	}
	if err := s.checkCert(r, id); err != nil {
		writeErr(w, http.StatusUnauthorized, "unauthorized", "Certificate not accepted.")
		return
	}
	pem, exp, err := s.CA.IssueDevice(id, s.Reg.PubKey(id), time.Now())
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "cert_failed", "Couldn't renew.")
		return
	}
	s.record("system", "device:cert-renew", id, "renewed", "")
	writeJSON(w, map[string]any{"device_cert_pem": string(pem), "cert_expires_ms": exp.UnixMilli()})
}
