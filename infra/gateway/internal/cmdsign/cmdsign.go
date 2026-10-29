// Package cmdsign signs alpha debug commands so a device can reject replays,
// misdirected commands and stale ones.
//
// Limit, stated plainly: the key lives on the gateway, so this does NOT protect
// against a compromised gateway (it can sign anything). It protects against replay,
// cross-device misdirection, delay and tampering between gateway and device.
// Real separation needs an operator-held key (WebAuthn), not built.
package cmdsign

import (
	"crypto/ed25519"
	"crypto/rand"
	"errors"
	"time"

	pb "github.com/asirive/cortex/gateway/internal/gen/cortex/v1"
	"google.golang.org/protobuf/proto"
)

const TTL = 60 * time.Second

var (
	ErrBadSignature = errors.New("command signature invalid")
	ErrWrongDevice  = errors.New("command is for another device")
	ErrExpired      = errors.New("command expired or not yet valid")
	ErrReplay       = errors.New("command nonce already used")
)

func bytesToSign(c *pb.DebugCommand) ([]byte, error) {
	x := proto.Clone(c).(*pb.DebugCommand)
	x.Signature = nil
	return proto.MarshalOptions{Deterministic: true}.Marshal(x)
}

func Sign(c *pb.DebugCommand, deviceID, issuer string, key ed25519.PrivateKey, now time.Time) error {
	c.DeviceId, c.Issuer = deviceID, issuer
	c.IssuedMs, c.ExpiresMs = now.UnixMilli(), now.Add(TTL).UnixMilli()
	c.Nonce = make([]byte, 16)
	rand.Read(c.Nonce)
	c.Signature = nil
	b, err := bytesToSign(c)
	if err != nil {
		return err
	}
	c.Signature = ed25519.Sign(key, b)
	return nil
}

// Verifier is the device-side check, kept here so the rules are tested in one place.
type Verifier struct {
	Pub      ed25519.PublicKey
	DeviceID string
	seen     map[string]bool
	order    []string
}

func (v *Verifier) Verify(c *pb.DebugCommand, now time.Time) error {
	b, err := bytesToSign(c)
	if err != nil || len(c.Signature) != ed25519.SignatureSize || !ed25519.Verify(v.Pub, b, c.Signature) {
		return ErrBadSignature
	}
	if c.DeviceId != v.DeviceID {
		return ErrWrongDevice
	}
	if now.UnixMilli() >= c.ExpiresMs || now.UnixMilli() < c.IssuedMs-5000 || c.ExpiresMs-c.IssuedMs > TTL.Milliseconds() {
		return ErrExpired
	}
	n := string(c.Nonce)
	if v.seen == nil {
		v.seen = map[string]bool{}
	}
	if v.seen[n] {
		return ErrReplay
	}
	v.seen[n] = true
	v.order = append(v.order, n)
	if len(v.order) > 256 {
		delete(v.seen, v.order[0])
		v.order = v.order[1:]
	}
	return nil
}
