package server

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/rsa"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/asirive/cortex/gateway/internal/fleet"
	"github.com/asirive/cortex/gateway/internal/pki"
	"github.com/gorilla/websocket"
)

// serverCert makes a throwaway TLS server certificate for 127.0.0.1 and the pool that trusts it.
func serverCert(t *testing.T) (tls.Certificate, *x509.CertPool) {
	k, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	tpl := &x509.Certificate{SerialNumber: big.NewInt(7), Subject: pkix.Name{CommonName: "gw"}, NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour),
		IPAddresses: []net.IP{net.ParseIP("127.0.0.1")}, KeyUsage: x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign, IsCA: true, BasicConstraintsValid: true,
		ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}}
	der, _ := x509.CreateCertificate(rand.Reader, tpl, tpl, &k.PublicKey, k)
	c, _ := x509.ParseCertificate(der)
	p := x509.NewCertPool()
	p.AddCert(c)
	return tls.Certificate{Certificate: [][]byte{der}, PrivateKey: k}, p
}

type devKit struct {
	id, tok string
	key     *ecdsa.PrivateKey
	cert    []byte
}

func (d devKit) tlsCfg(roots *x509.CertPool) *tls.Config {
	blk, _ := pem.Decode(d.cert)
	return &tls.Config{RootCAs: roots, Certificates: []tls.Certificate{{Certificate: [][]byte{blk.Bytes}, PrivateKey: d.key}}}
}

func claimDevice(t *testing.T, s *Server, base string, acctTok string) devKit {
	_, reg := post(t, base+"/api/registrations", "boot", map[string]any{"tier": "BETA", "label": "mtls"})
	k, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	der, _ := x509.MarshalPKIXPublicKey(&k.PublicKey)
	code, c := post(t, base+"/v1/claim", acctTok, map[string]any{"claim_code": reg["claim_code"], "device_public_key": der})
	if code != 200 {
		t.Fatalf("claim: %d %v", code, c)
	}
	return devKit{id: c["device_id"].(string), tok: c["device_token"].(string), key: k, cert: []byte(c["device_cert_pem"].(string))}
}

func wsURL(base string) string { return "wss" + strings.TrimPrefix(base, "https") + "/ws/device" }

func TestMutualTLSDeviceListener(t *testing.T) {
	ca, err := pki.LoadOrCreate(t.TempDir(), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	s := New(fleet.New(), "boot")
	s.CA, s.RequireMTLS = ca, true
	api := httptest.NewServer(s.Handler()) // public listener (behind the HTTPS proxy)
	defer api.Close()
	sc, roots := serverCert(t)
	dev := httptest.NewUnstartedServer(s.DeviceHandler())
	dev.TLS = s.DeviceTLS(sc)
	dev.StartTLS()
	defer dev.Close()

	acct := login(t, s, "m@example.com")
	// claim demands a proper key and does not burn the code on a bad one
	_, reg := post(t, api.URL+"/api/registrations", "boot", map[string]any{"tier": "BETA", "label": "bad key"})
	if c, _ := post(t, api.URL+"/v1/claim", acct, map[string]any{"claim_code": reg["claim_code"]}); c != 400 {
		t.Fatalf("claim without a device key: %d", c)
	}
	rk, _ := rsa.GenerateKey(rand.Reader, 2048)
	rder, _ := x509.MarshalPKIXPublicKey(&rk.PublicKey)
	if c, _ := post(t, api.URL+"/v1/claim", acct, map[string]any{"claim_code": reg["claim_code"], "device_public_key": rder}); c != 400 {
		t.Fatalf("RSA device key accepted: %d", c)
	}
	if c, _ := post(t, api.URL+"/v1/claim", acct, map[string]any{"claim_code": "NOPE-NOPE"}); c == 200 {
		t.Fatal("bogus claim")
	}

	a, b := claimDevice(t, s, api.URL, acct), claimDevice(t, s, api.URL, acct)
	hdr := func(d devKit, tok string) http.Header {
		return http.Header{"Authorization": {"Bearer " + tok}, "X-Device-Id": {d.id}}
	}
	dial := func(cfg *tls.Config, h http.Header) error {
		c, _, err := (&websocket.Dialer{TLSClientConfig: cfg, HandshakeTimeout: 3 * time.Second}).Dial(wsURL(dev.URL), h)
		if err == nil {
			c.Close()
		}
		return err
	}

	if err := dial(a.tlsCfg(roots), hdr(a, a.tok)); err != nil {
		t.Fatalf("valid certificate + token refused: %v", err)
	}
	if err := dial(&tls.Config{RootCAs: roots}, hdr(a, a.tok)); err == nil {
		t.Fatal("connected without a client certificate")
	}
	if err := dial(a.tlsCfg(roots), hdr(a, "wrong")); err == nil {
		t.Fatal("certificate alone was enough; the token must still match")
	}
	if err := dial(b.tlsCfg(roots), hdr(a, a.tok)); err == nil {
		t.Fatal("device B's certificate accepted for device A")
	}
	// a certificate from a different CA
	other, _ := pki.LoadOrCreate(t.TempDir(), time.Now())
	der, _ := x509.MarshalPKIXPublicKey(&a.key.PublicKey)
	forged, _, _ := other.IssueDevice(a.id, der, time.Now())
	f := a
	f.cert = forged
	if err := dial(f.tlsCfg(roots), hdr(a, a.tok)); err == nil {
		t.Fatal("certificate from another CA accepted")
	}
	// the public listener does not serve the device socket at all
	if _, _, err := websocket.DefaultDialer.Dial("ws"+strings.TrimPrefix(api.URL, "http")+"/ws/device", hdr(a, a.tok)); err == nil {
		t.Fatal("device socket exposed on the public listener")
	}
	// the device listener does not serve the operator API
	c := &http.Client{Transport: &http.Transport{TLSClientConfig: a.tlsCfg(roots)}}
	if res, err := c.Get(dev.URL + "/api/devices"); err == nil && res.StatusCode == 200 {
		t.Fatal("operator API reachable on the device listener")
	}

	// renewal keeps the same key and issues a different certificate
	res, err := c.Post(dev.URL+"/device/renew", "application/json", nil)
	if err != nil || res.StatusCode != 200 {
		t.Fatalf("renew: %v %v", err, res)
	}
	res.Body.Close()

	// revoking kills the next handshake
	post(t, api.URL+"/api/registrations/"+a.id+"/revoke", "boot", nil)
	if err := dial(a.tlsCfg(roots), hdr(a, a.tok)); err == nil {
		t.Fatal("revoked device still connects")
	}
	if err := dial(b.tlsCfg(roots), hdr(b, b.tok)); err != nil {
		t.Fatalf("revoking A broke B: %v", err)
	}
}

func TestCARoundTripsAndKeepsKey(t *testing.T) {
	dir := t.TempDir()
	a, err := pki.LoadOrCreate(dir, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	b, err := pki.LoadOrCreate(dir, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if string(a.PEM) != string(b.PEM) {
		t.Fatal("CA regenerated on restart; every device would be locked out")
	}
}
