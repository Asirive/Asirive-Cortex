package main

import (
	"crypto/ed25519"
	"encoding/hex"
	"flag"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/asirive/cortex/gateway/internal/fleet"
	"github.com/asirive/cortex/gateway/internal/ota"
	"github.com/asirive/cortex/gateway/internal/server"
)

func main() {
	addr := flag.String("addr", ":8080", "listen address")
	shared := flag.Bool("dev-shared-device-token", false, "DEV ONLY: let devices connect with the shared token (simulator)")
	flag.Parse()
	token := os.Getenv("CORTEX_DEV_TOKEN")
	if token == "" {
		log.Fatal("CORTEX_DEV_TOKEN must be set")
	}
	f := fleet.New()
	go func() {
		for range time.Tick(2 * time.Second) {
			f.Sweep(time.Now())
		}
	}()
	srv := server.New(f, token)
	srv.AllowSharedDeviceToken = *shared
	if k := os.Getenv("CORTEX_OTA_PUBKEY"); k != "" { // hex ed25519 public key; the private key never touches the gateway
		pub, err := hex.DecodeString(k)
		if err != nil || len(pub) != ed25519.PublicKeySize {
			log.Fatal("CORTEX_OTA_PUBKEY must be a 32-byte hex ed25519 public key")
		}
		srv.WireOTA(ota.NewEngine(pub))
		go func() {
			for range time.Tick(30 * time.Second) {
				srv.OTA.Evaluate(time.Now())
			}
		}()
	} else {
		log.Print("OTA disabled: CORTEX_OTA_PUBKEY not set")
	}
	log.Printf("cortex gateway listening on %s", *addr)
	httpSrv := &http.Server{Addr: *addr, Handler: srv.Handler(), ReadHeaderTimeout: 10 * time.Second, ReadTimeout: 30 * time.Second, IdleTimeout: 120 * time.Second}
	log.Fatal(httpSrv.ListenAndServe())
}
