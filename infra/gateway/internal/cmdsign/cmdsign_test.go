package cmdsign

import (
	"crypto/ed25519"
	"crypto/rand"
	"testing"
	"time"

	pb "github.com/asirive/cortex/gateway/internal/gen/cortex/v1"
)

func TestSignedCommandRules(t *testing.T) {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	now := time.Now()
	mk := func() *pb.DebugCommand {
		c := &pb.DebugCommand{CommandId: "c1", Name: "reboot", Args: map[string]string{"a": "b"}}
		Sign(c, "ALPHA-0001", "omar", priv, now)
		return c
	}
	v := &Verifier{Pub: pub, DeviceID: "ALPHA-0001"}
	c := mk()
	if err := v.Verify(c, now); err != nil {
		t.Fatal(err)
	}
	if v.Verify(c, now) != ErrReplay {
		t.Fatal("replay accepted")
	}
	t2 := mk()
	t2.Name = "restart_service"
	if v.Verify(t2, now) != ErrBadSignature {
		t.Fatal("tampered command accepted")
	}
	if (&Verifier{Pub: pub, DeviceID: "ALPHA-0002"}).Verify(mk(), now) != ErrWrongDevice {
		t.Fatal("command for another device accepted")
	}
	if v.Verify(mk(), now.Add(2*time.Minute)) != ErrExpired {
		t.Fatal("expired command accepted")
	}
	other, _, _ := ed25519.GenerateKey(rand.Reader)
	if (&Verifier{Pub: other, DeviceID: "ALPHA-0001"}).Verify(mk(), now) != ErrBadSignature {
		t.Fatal("wrong key accepted")
	}
}
