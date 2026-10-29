package main

import (
	"crypto/ed25519"
	"encoding/hex"
	"flag"
	"github.com/asirive/cortex/gateway/internal/mail"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/asirive/cortex/gateway/internal/fleet"
	"github.com/asirive/cortex/gateway/internal/ota"
	"github.com/asirive/cortex/gateway/internal/server"
)

func main() {
	addr := flag.String("addr", ":8080", "listen address")
	shared := flag.Bool("dev-shared-device-token", false, "DEV ONLY: let devices connect with the shared token (simulator)")
	statePath := flag.String("state", "cortex-state.json", "durable state file (registrations, releases, audit)")
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
	if k := os.Getenv("RESEND_API_KEY"); k != "" {
		from := os.Getenv("CORTEX_MAIL_FROM")
		if from == "" {
			log.Fatal("CORTEX_MAIL_FROM is required with RESEND_API_KEY, e.g. 'Asirive <no-reply@asirive.com>'")
		}
		srv.Mailer = &mail.Resend{APIKey: k, From: from}
	} else {
		log.Print("WARNING: RESEND_API_KEY not set; app emails (verify, reset) are written to this log. DEV ONLY.")
	}
	if b := os.Getenv("CORTEX_APP_LINK_BASE"); b != "" {
		srv.AppLinkBase = b
	}
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
	if err := srv.LoadState(*statePath); err != nil {
		log.Fatalf("load state %s: %v (refusing to start with unreadable state)", *statePath, err)
	}
	save := func() {
		if err := srv.SaveState(*statePath); err != nil {
			log.Printf("save state: %v", err)
		}
	}
	go func() {
		for range time.Tick(10 * time.Minute) {
			srv.Social.Sweep(time.Now())
		}
	}()
	go func() {
		for range time.Tick(3 * time.Second) {
			save()
		}
	}()
	log.Printf("cortex gateway listening on %s", *addr)
	httpSrv := &http.Server{Addr: *addr, Handler: srv.Handler(), ReadHeaderTimeout: 10 * time.Second, ReadTimeout: 30 * time.Second, IdleTimeout: 120 * time.Second}
	go func() {
		sig := make(chan os.Signal, 1)
		signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
		<-sig
		save()
		os.Exit(0)
	}()
	log.Fatal(httpSrv.ListenAndServe())
}
