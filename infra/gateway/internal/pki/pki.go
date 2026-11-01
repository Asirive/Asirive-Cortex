// Package pki is the device certificate authority. The gateway issues each device
// a short-lived client certificate bound to the public key it registered at claim
// time, and the device listener only accepts connections presenting one.
//
// The device's private key never leaves the device (ideally never leaves a secure
// element/TPM); the gateway only ever sees the public half.
package pki

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"errors"
	"math/big"
	"os"
	"path/filepath"
	"time"
)

const DeviceCertTTL = 90 * 24 * time.Hour

var (
	ErrBadKey = errors.New("device public key must be an ECDSA P-256 key in PKIX DER form")
)

type CA struct {
	cert *x509.Certificate
	key  *ecdsa.PrivateKey
	PEM  []byte
}

// LoadOrCreate reads ca.crt/ca.key from dir, creating a new 10-year CA on first use.
// The key file is owner-only. Back it up: losing it means re-issuing every device.
func LoadOrCreate(dir string, now time.Time) (*CA, error) {
	crtPath, keyPath := filepath.Join(dir, "ca.crt"), filepath.Join(dir, "ca.key")
	crtPEM, e1 := os.ReadFile(crtPath)
	keyPEM, e2 := os.ReadFile(keyPath)
	if e1 == nil && e2 == nil {
		return parse(crtPEM, keyPEM)
	}
	if !errors.Is(e1, os.ErrNotExist) && e1 != nil {
		return nil, e1
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	k, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, err
	}
	tpl := &x509.Certificate{SerialNumber: serial(), Subject: pkix.Name{CommonName: "Asirive Cortex Device CA", Organization: []string{"Asirive"}},
		NotBefore: now.Add(-time.Hour), NotAfter: now.AddDate(10, 0, 0), IsCA: true, BasicConstraintsValid: true, MaxPathLenZero: true,
		KeyUsage: x509.KeyUsageCertSign | x509.KeyUsageCRLSign}
	der, err := x509.CreateCertificate(rand.Reader, tpl, tpl, &k.PublicKey, k)
	if err != nil {
		return nil, err
	}
	kd, _ := x509.MarshalECPrivateKey(k)
	crtPEM = pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	keyPEM = pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: kd})
	if err := os.WriteFile(keyPath, keyPEM, 0o600); err != nil {
		return nil, err
	}
	if err := os.WriteFile(crtPath, crtPEM, 0o644); err != nil {
		return nil, err
	}
	return parse(crtPEM, keyPEM)
}

func parse(crtPEM, keyPEM []byte) (*CA, error) {
	cb, _ := pem.Decode(crtPEM)
	kb, _ := pem.Decode(keyPEM)
	if cb == nil || kb == nil {
		return nil, errors.New("pki: bad PEM")
	}
	c, err := x509.ParseCertificate(cb.Bytes)
	if err != nil {
		return nil, err
	}
	k, err := x509.ParseECPrivateKey(kb.Bytes)
	if err != nil {
		return nil, err
	}
	return &CA{cert: c, key: k, PEM: crtPEM}, nil
}

func serial() *big.Int {
	n, _ := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 120))
	return n
}

// ParseDeviceKey validates a PKIX DER public key: it must be ECDSA P-256.
func ParseDeviceKey(der []byte) (*ecdsa.PublicKey, error) {
	k, err := x509.ParsePKIXPublicKey(der)
	if err != nil {
		return nil, ErrBadKey
	}
	ek, ok := k.(*ecdsa.PublicKey)
	if !ok || ek.Curve != elliptic.P256() {
		return nil, ErrBadKey
	}
	return ek, nil
}

// IssueDevice signs a client certificate for deviceID over the given key.
func (c *CA) IssueDevice(deviceID string, pubDER []byte, now time.Time) ([]byte, time.Time, error) {
	pk, err := ParseDeviceKey(pubDER)
	if err != nil {
		return nil, time.Time{}, err
	}
	exp := now.Add(DeviceCertTTL)
	tpl := &x509.Certificate{SerialNumber: serial(), Subject: pkix.Name{CommonName: deviceID, Organization: []string{"Asirive Cortex device"}},
		NotBefore: now.Add(-5 * time.Minute), NotAfter: exp, KeyUsage: x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth}}
	der, err := x509.CreateCertificate(rand.Reader, tpl, c.cert, pk, c.key)
	if err != nil {
		return nil, time.Time{}, err
	}
	return pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}), exp, nil
}

func (c *CA) Pool() *x509.CertPool {
	p := x509.NewCertPool()
	p.AddCert(c.cert)
	return p
}
