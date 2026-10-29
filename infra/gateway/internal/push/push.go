// Package push wakes a phone: FCM (Android) and APNs (iOS). Payloads are generic
// ("Incoming call") and carry only an opaque call id, never names or locations.
package push

import (
	"bytes"
	"crypto"
	"crypto/ecdsa"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"
)

// ErrUnregistered means the token is dead and should be forgotten.
var ErrUnregistered = errors.New("push token no longer valid")

type Message struct {
	Title, Body string
	Data        map[string]string
}

type Pusher interface {
	Send(platform, token string, m Message) error
}

func b64(b []byte) string { return base64.RawURLEncoding.EncodeToString(b) }

func jwt(header, claims map[string]any, sign func([]byte) ([]byte, error)) (string, error) {
	h, _ := json.Marshal(header)
	c, _ := json.Marshal(claims)
	in := b64(h) + "." + b64(c)
	sig, err := sign([]byte(in))
	if err != nil {
		return "", err
	}
	return in + "." + b64(sig), nil
}

func parsePEM(path string) (any, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return parseKey(raw)
}

func parseKey(raw []byte) (any, error) {
	blk, _ := pem.Decode(raw)
	if blk == nil {
		return nil, errors.New("no PEM block")
	}
	return x509.ParsePKCS8PrivateKey(blk.Bytes)
}

// ---- APNs ----

type APNs struct {
	Key      *ecdsa.PrivateKey
	KeyID    string
	TeamID   string
	Topic    string // bundle id
	Endpoint string // default https://api.push.apple.com
	Client   *http.Client

	mu  sync.Mutex
	tok string
	iat time.Time
}

func NewAPNs(keyPath, keyID, teamID, topic string) (*APNs, error) {
	k, err := parsePEM(keyPath)
	if err != nil {
		return nil, err
	}
	ec, ok := k.(*ecdsa.PrivateKey)
	if !ok {
		return nil, errors.New("APNs key is not an EC key")
	}
	return &APNs{Key: ec, KeyID: keyID, TeamID: teamID, Topic: topic}, nil
}

func (a *APNs) bearer(now time.Time) (string, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.tok != "" && now.Sub(a.iat) < 40*time.Minute { // Apple wants a refresh between 20 and 60 minutes
		return a.tok, nil
	}
	t, err := jwt(map[string]any{"alg": "ES256", "kid": a.KeyID}, map[string]any{"iss": a.TeamID, "iat": now.Unix()}, func(in []byte) ([]byte, error) {
		h := sha256.Sum256(in)
		r, s, err := ecdsa.Sign(rand.Reader, a.Key, h[:])
		if err != nil {
			return nil, err
		}
		out := make([]byte, 64)
		r.FillBytes(out[:32])
		s.FillBytes(out[32:])
		return out, nil
	})
	if err == nil {
		a.tok, a.iat = t, now
	}
	return t, err
}

func (a *APNs) Send(platform, token string, m Message) error {
	if platform != "ios" {
		return errors.New("apns: not an ios token")
	}
	b, err := a.bearer(time.Now())
	if err != nil {
		return err
	}
	ep := a.Endpoint
	if ep == "" {
		ep = "https://api.push.apple.com"
	}
	body := map[string]any{"aps": map[string]any{"alert": map[string]string{"title": m.Title, "body": m.Body}, "sound": "default", "interruption-level": "time-sensitive"}}
	for k, v := range m.Data {
		body[k] = v
	}
	js, _ := json.Marshal(body)
	req, _ := http.NewRequest("POST", ep+"/3/device/"+url.PathEscape(token), bytes.NewReader(js))
	req.Header.Set("authorization", "bearer "+b)
	req.Header.Set("apns-topic", a.Topic)
	req.Header.Set("apns-push-type", "alert")
	req.Header.Set("apns-priority", "10")
	req.Header.Set("apns-expiration", fmt.Sprint(time.Now().Add(60*time.Second).Unix()))
	c := a.Client
	if c == nil {
		c = &http.Client{Timeout: 10 * time.Second}
	}
	res, err := c.Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	if res.StatusCode == 200 {
		return nil
	}
	rb, _ := io.ReadAll(io.LimitReader(res.Body, 512))
	if res.StatusCode == 410 || strings.Contains(string(rb), "BadDeviceToken") || strings.Contains(string(rb), "Unregistered") {
		return ErrUnregistered
	}
	return fmt.Errorf("apns: %s: %s", res.Status, rb)
}

// ---- FCM (HTTP v1) ----

type FCM struct {
	ProjectID   string
	ClientEmail string
	Key         *rsa.PrivateKey
	TokenURI    string // OAuth endpoint
	Endpoint    string // default https://fcm.googleapis.com
	Client      *http.Client

	mu     sync.Mutex
	access string
	until  time.Time
}

func NewFCM(serviceAccountPath string) (*FCM, error) {
	raw, err := os.ReadFile(serviceAccountPath)
	if err != nil {
		return nil, err
	}
	var sa struct {
		ProjectID   string `json:"project_id"`
		ClientEmail string `json:"client_email"`
		PrivateKey  string `json:"private_key"`
		TokenURI    string `json:"token_uri"`
	}
	if err := json.Unmarshal(raw, &sa); err != nil {
		return nil, err
	}
	k, err := parseKey([]byte(sa.PrivateKey))
	if err != nil {
		return nil, err
	}
	rk, ok := k.(*rsa.PrivateKey)
	if !ok {
		return nil, errors.New("service account key is not RSA")
	}
	return &FCM{ProjectID: sa.ProjectID, ClientEmail: sa.ClientEmail, Key: rk, TokenURI: sa.TokenURI}, nil
}

func (f *FCM) client() *http.Client {
	if f.Client != nil {
		return f.Client
	}
	return &http.Client{Timeout: 10 * time.Second}
}

func (f *FCM) accessToken(now time.Time) (string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.access != "" && now.Before(f.until) {
		return f.access, nil
	}
	as, err := jwt(map[string]any{"alg": "RS256", "typ": "JWT"}, map[string]any{
		"iss": f.ClientEmail, "scope": "https://www.googleapis.com/auth/firebase.messaging", "aud": f.TokenURI, "iat": now.Unix(), "exp": now.Add(time.Hour).Unix()},
		func(in []byte) ([]byte, error) {
			h := sha256.Sum256(in)
			return rsa.SignPKCS1v15(rand.Reader, f.Key, crypto.SHA256, h[:])
		})
	if err != nil {
		return "", err
	}
	res, err := f.client().PostForm(f.TokenURI, url.Values{"grant_type": {"urn:ietf:params:oauth:grant-type:jwt-bearer"}, "assertion": {as}})
	if err != nil {
		return "", err
	}
	defer res.Body.Close()
	var out struct {
		AccessToken string `json:"access_token"`
		ExpiresIn   int    `json:"expires_in"`
	}
	if res.StatusCode != 200 || json.NewDecoder(res.Body).Decode(&out) != nil || out.AccessToken == "" {
		return "", fmt.Errorf("fcm oauth: %s", res.Status)
	}
	f.access, f.until = out.AccessToken, now.Add(time.Duration(out.ExpiresIn-60)*time.Second)
	return f.access, nil
}

func (f *FCM) Send(platform, token string, m Message) error {
	if platform != "android" {
		return errors.New("fcm: not an android token")
	}
	at, err := f.accessToken(time.Now())
	if err != nil {
		return err
	}
	ep := f.Endpoint
	if ep == "" {
		ep = "https://fcm.googleapis.com"
	}
	msg := map[string]any{"token": token, "data": m.Data, "android": map[string]any{"priority": "HIGH", "ttl": "60s",
		"notification": map[string]string{"title": m.Title, "body": m.Body}}}
	js, _ := json.Marshal(map[string]any{"message": msg})
	req, _ := http.NewRequest("POST", ep+"/v1/projects/"+f.ProjectID+"/messages:send", bytes.NewReader(js))
	req.Header.Set("Authorization", "Bearer "+at)
	req.Header.Set("Content-Type", "application/json")
	res, err := f.client().Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	if res.StatusCode == 200 {
		return nil
	}
	rb, _ := io.ReadAll(io.LimitReader(res.Body, 512))
	if res.StatusCode == 404 || strings.Contains(string(rb), "UNREGISTERED") {
		return ErrUnregistered
	}
	return fmt.Errorf("fcm: %s: %s", res.Status, rb)
}

// ---- routing and dev ----

// Router sends to the right provider by platform.
type Router struct{ IOS, Android Pusher }

func (r Router) Send(platform, token string, m Message) error {
	p := r.IOS
	if platform == "android" {
		p = r.Android
	}
	if p == nil {
		return errors.New("no push provider configured for " + platform)
	}
	return p.Send(platform, token, m)
}

// Log prints instead of sending (dev).
type Log struct{}

func (Log) Send(platform, token string, m Message) error {
	log.Printf("DEV PUSH %s %.6s… %q %v", platform, token, m.Body, m.Data)
	return nil
}
