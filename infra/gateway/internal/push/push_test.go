package push

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"io"
	"math/big"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestAPNsRequestAndJWT(t *testing.T) {
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	var hdr http.Header
	var path string
	var body map[string]any
	status := 200
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hdr, path = r.Header, r.URL.Path
		b, _ := io.ReadAll(r.Body)
		json.Unmarshal(b, &body)
		w.WriteHeader(status)
		if status != 200 {
			w.Write([]byte(`{"reason":"BadDeviceToken"}`))
		}
	}))
	defer srv.Close()
	a := &APNs{Key: key, KeyID: "KID123", TeamID: "TEAM123", Topic: "com.asirive.cortex", Endpoint: srv.URL}
	if err := a.Send("ios", "devtoken123", Message{Title: "Asirive", Body: "Incoming call", Data: map[string]string{"call_id": "c1"}}); err != nil {
		t.Fatal(err)
	}
	if path != "/3/device/devtoken123" || hdr.Get("apns-topic") != "com.asirive.cortex" || body["call_id"] != "c1" {
		t.Fatalf("bad request %s %v %v", path, hdr, body)
	}
	parts := strings.Split(strings.TrimPrefix(hdr.Get("authorization"), "bearer "), ".")
	sig, _ := base64.RawURLEncoding.DecodeString(parts[2])
	h := sha256.Sum256([]byte(parts[0] + "." + parts[1]))
	if len(sig) != 64 || !ecdsa.Verify(&key.PublicKey, h[:], new(big.Int).SetBytes(sig[:32]), new(big.Int).SetBytes(sig[32:])) {
		t.Fatal("APNs JWT signature invalid")
	}
	status = 410
	if err := a.Send("ios", "dead", Message{}); err != ErrUnregistered {
		t.Fatalf("dead token not reported: %v", err)
	}
	if a.Send("android", "x", Message{}) == nil {
		t.Fatal("wrong platform accepted")
	}
}

func TestFCMFlow(t *testing.T) {
	rk, _ := rsa.GenerateKey(rand.Reader, 2048)
	der, _ := x509.MarshalPKCS8PrivateKey(rk)
	pemKey := string(pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der}))
	var sent map[string]any
	var auth string
	sendStatus, sendBody := 200, ""
	mux := http.NewServeMux()
	mux.HandleFunc("/token", func(w http.ResponseWriter, r *http.Request) {
		r.ParseForm()
		p := strings.Split(r.Form.Get("assertion"), ".")
		sig, _ := base64.RawURLEncoding.DecodeString(p[2])
		h := sha256.Sum256([]byte(p[0] + "." + p[1]))
		if rsa.VerifyPKCS1v15(&rk.PublicKey, 5, h[:], sig) != nil { // crypto.SHA256 == 5
			w.WriteHeader(401)
			return
		}
		w.Write([]byte(`{"access_token":"at-1","expires_in":3600}`))
	})
	mux.HandleFunc("/v1/projects/proj/messages:send", func(w http.ResponseWriter, r *http.Request) {
		auth = r.Header.Get("Authorization")
		b, _ := io.ReadAll(r.Body)
		json.Unmarshal(b, &sent)
		w.WriteHeader(sendStatus)
		w.Write([]byte(sendBody))
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()
	sa, _ := json.Marshal(map[string]string{"project_id": "proj", "client_email": "svc@proj.iam", "private_key": pemKey, "token_uri": srv.URL + "/token"})
	p := filepath.Join(t.TempDir(), "sa.json")
	os.WriteFile(p, sa, 0o600)
	f, err := NewFCM(p)
	if err != nil {
		t.Fatal(err)
	}
	f.Endpoint = srv.URL
	if err := f.Send("android", "tok-abcdefgh", Message{Title: "Asirive", Body: "Incoming call", Data: map[string]string{"call_id": "c1"}}); err != nil {
		t.Fatal(err)
	}
	m := sent["message"].(map[string]any)
	if auth != "Bearer at-1" || m["token"] != "tok-abcdefgh" {
		t.Fatalf("bad FCM request: %s %v", auth, sent)
	}
	sendStatus, sendBody = 404, `{"error":{"status":"NOT_FOUND","details":[{"errorCode":"UNREGISTERED"}]}}`
	if err := f.Send("android", "dead", Message{}); err != ErrUnregistered {
		t.Fatalf("dead token not reported: %v", err)
	}
}
