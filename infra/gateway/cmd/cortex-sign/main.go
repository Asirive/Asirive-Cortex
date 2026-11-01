// cortex-sign runs OFF the gateway (CI or an offline machine). It holds the OTA
// signing key and produces signed manifests the gateway can register but not forge.
//
//	cortex-sign keygen -out ota.key                      # writes ota.key (private) and prints the public key
//	cortex-sign sign -key ota.key -release r-2026.10.30 -counter 12 -max-ring stable \
//	    -artifact compute:4.0.1:./compute.img:https://dl.example/compute.img -out r.manifest
package main

import (
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"flag"
	"fmt"
	"github.com/asirive/cortex/gateway/internal/cmdsign"
	"log"
	"os"
	"strings"
	"time"

	pb "github.com/asirive/cortex/gateway/internal/gen/cortex/v1"
	"github.com/asirive/cortex/gateway/internal/ota"
	"google.golang.org/protobuf/proto"
)

type multi []string

func (m *multi) String() string     { return strings.Join(*m, ",") }
func (m *multi) Set(v string) error { *m = append(*m, v); return nil }

func main() {
	if len(os.Args) < 2 {
		log.Fatal("usage: cortex-sign keygen|sign")
	}
	switch os.Args[1] {
	case "keygen":
		fs := flag.NewFlagSet("keygen", flag.ExitOnError)
		out := fs.String("out", "ota.key", "private key file")
		fs.Parse(os.Args[2:])
		pub, priv, _ := ed25519.GenerateKey(rand.Reader)
		if err := os.WriteFile(*out, []byte(hex.EncodeToString(priv)), 0o600); err != nil {
			log.Fatal(err)
		}
		fmt.Println("public key (CORTEX_OTA_PUBKEY):", hex.EncodeToString(pub))
	case "sign-command":
		// Test/ops helper: signs one alpha debug command with a command key (hex ed25519 private key)
		// and prints the serialized DebugCommand as hex. Used to cross-check the device verifier.
		fs := flag.NewFlagSet("sign-command", flag.ExitOnError)
		key := fs.String("key", "", "hex ed25519 private key")
		dev := fs.String("device", "", "device id")
		name := fs.String("name", "dump_state", "command name")
		var args multi
		fs.Var(&args, "arg", "k=v, repeatable")
		fs.Parse(os.Args[2:])
		priv, err := hex.DecodeString(*key)
		if err != nil || len(priv) != ed25519.PrivateKeySize || *dev == "" {
			log.Fatal("need -key (hex private key) and -device")
		}
		c := &pb.DebugCommand{CommandId: "fixture", Name: *name, Args: map[string]string{}}
		for _, a := range args {
			kv := strings.SplitN(a, "=", 2)
			if len(kv) == 2 {
				c.Args[kv[0]] = kv[1]
			}
		}
		if err := cmdsign.Sign(c, *dev, "fixture", ed25519.PrivateKey(priv), time.Now()); err != nil {
			log.Fatal(err)
		}
		b, _ := proto.Marshal(c)
		fmt.Println(hex.EncodeToString(b))
	case "sign":
		fs := flag.NewFlagSet("sign", flag.ExitOnError)
		key := fs.String("key", "ota.key", "private key file")
		rel := fs.String("release", "", "release id")
		counter := fs.Uint64("counter", 0, "anti-rollback version counter (must increase)")
		maxRing := fs.String("max-ring", "stable", "alpha|beta|stable")
		out := fs.String("out", "release.manifest", "output file")
		var arts multi
		fs.Var(&arts, "artifact", "kind:version:path:url (kind: compute|mcu|model|config), repeatable")
		fs.Parse(os.Args[2:])
		raw, err := os.ReadFile(*key)
		if err != nil {
			log.Fatal(err)
		}
		priv, err := hex.DecodeString(strings.TrimSpace(string(raw)))
		if err != nil || len(priv) != ed25519.PrivateKeySize || *rel == "" || *counter == 0 || len(arts) == 0 {
			log.Fatal("need a valid key, -release, -counter > 0 and at least one -artifact")
		}
		ring := map[string]pb.Ring{"alpha": pb.Ring_RING_ALPHA, "beta": pb.Ring_RING_BETA, "stable": pb.Ring_RING_STABLE}[*maxRing]
		kinds := map[string]pb.ArtifactKind{"compute": pb.ArtifactKind_ARTIFACT_KIND_COMPUTE_FIRMWARE, "mcu": pb.ArtifactKind_ARTIFACT_KIND_MCU_FIRMWARE,
			"model": pb.ArtifactKind_ARTIFACT_KIND_MODEL, "config": pb.ArtifactKind_ARTIFACT_KIND_CONFIG}
		m := &pb.Manifest{ReleaseId: *rel, VersionCounter: *counter, MaxRing: ring}
		for _, a := range arts {
			p := strings.SplitN(a, ":", 4)
			if len(p) != 4 || kinds[p[0]] == 0 {
				log.Fatalf("bad -artifact %q", a)
			}
			data, err := os.ReadFile(p[2])
			if err != nil {
				log.Fatal(err)
			}
			h := sha256.Sum256(data)
			m.Artifacts = append(m.Artifacts, &pb.Artifact{Kind: kinds[p[0]], Version: p[1], Url: p[3], SizeBytes: uint64(len(data)), Sha256: h[:]})
		}
		if err := ota.Sign(m, ed25519.PrivateKey(priv)); err != nil {
			log.Fatal(err)
		}
		b, _ := proto.Marshal(m)
		if err := os.WriteFile(*out, b, 0o644); err != nil {
			log.Fatal(err)
		}
		fmt.Println("signed", *rel, "->", *out)
	default:
		log.Fatal("usage: cortex-sign keygen|sign")
	}
}
