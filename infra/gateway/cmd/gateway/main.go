package main

import (
	"context"
	"crypto/ed25519"
	"crypto/tls"
	"encoding/hex"
	"flag"
	"github.com/asirive/cortex/gateway/internal/mail"
	"github.com/asirive/cortex/gateway/internal/pki"
	"github.com/asirive/cortex/gateway/internal/push"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
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
	deviceAddr := flag.String("device-addr", "", "mTLS listener for devices, e.g. :8443 (enables device certificates; /ws/device moves here)")
	deviceCert := flag.String("device-cert", "", "TLS server certificate (PEM) for the device listener, e.g. from Let's Encrypt")
	deviceKey := flag.String("device-key", "", "TLS server key (PEM) for the device listener")
	pkiDir := flag.String("pki-dir", "pki", "directory holding the device CA (ca.crt, ca.key); created on first start")
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
	var rt push.Router
	if p := os.Getenv("CORTEX_FCM_SERVICE_ACCOUNT"); p != "" {
		f, err := push.NewFCM(p)
		if err != nil {
			log.Fatalf("FCM: %v", err)
		}
		rt.Android = f
	}
	if p := os.Getenv("CORTEX_APNS_KEY"); p != "" {
		a, err := push.NewAPNs(p, os.Getenv("CORTEX_APNS_KEY_ID"), os.Getenv("CORTEX_APNS_TEAM_ID"), os.Getenv("CORTEX_APNS_TOPIC"))
		if err != nil {
			log.Fatalf("APNs: %v", err)
		}
		rt.IOS = a
	}
	if rt.IOS != nil || rt.Android != nil {
		srv.Pusher = rt
	} else {
		log.Print("WARNING: no FCM/APNs credentials; incoming calls only reach apps that poll. Push is logged, not sent.")
		srv.Pusher = push.Log{}
	}
	srv.TurnSecret = os.Getenv("CORTEX_TURN_SECRET")
	if u := os.Getenv("CORTEX_TURN_URLS"); u != "" {
		srv.TurnURLs = strings.Split(u, ",")
	}
	if a := os.Getenv("CORTEX_ALERT_EMAILS"); a != "" {
		srv.AlertTo = strings.Split(a, ",")
		srv.StartAlerts()
	} else {
		log.Print("alerts off: set CORTEX_ALERT_EMAILS to be emailed when devices need attention")
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
	var store server.StateStore = server.FileStore{Path: *statePath}
	if dsn := os.Getenv("CORTEX_PG_DSN"); dsn != "" {
		pg, err := server.OpenPG(context.Background(), dsn)
		if err != nil {
			log.Fatalf("postgres: %v", err)
		}
		for { // warm standby: wait until the current leader's lock is released
			ok, err := pg.TryLead(context.Background())
			if err != nil {
				log.Fatalf("postgres lock: %v", err)
			}
			if ok {
				break
			}
			log.Print("standby: another gateway holds the lead; waiting")
			time.Sleep(5 * time.Second)
		}
		store = pg
		go func() { // lost the lock (connection dropped)? Stop writing and exit so the supervisor restarts us as standby.
			for range time.Tick(5 * time.Second) {
				if !pg.StillLeader(context.Background()) {
					log.Fatal("lost the postgres lead; exiting")
				}
			}
		}()
		log.Print("state store: postgres (leader)")
	}
	if err := srv.LoadFrom(store); err != nil {
		log.Fatalf("load state: %v (refusing to start with unreadable state)", err)
	}
	save := func() {
		if err := srv.SaveTo(store); err != nil {
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
	if *deviceAddr != "" {
		if *deviceCert == "" || *deviceKey == "" {
			log.Fatal("-device-addr needs -device-cert and -device-key")
		}
		ca, err := pki.LoadOrCreate(*pkiDir, time.Now())
		if err != nil {
			log.Fatalf("device CA: %v", err)
		}
		sc, err := tls.LoadX509KeyPair(*deviceCert, *deviceKey)
		if err != nil {
			log.Fatalf("device TLS cert: %v", err)
		}
		srv.CA, srv.RequireMTLS, srv.AllowSharedDeviceToken = ca, true, false
		ds := &http.Server{Addr: *deviceAddr, Handler: srv.DeviceHandler(), TLSConfig: srv.DeviceTLS(sc), ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 5 * time.Minute}
		go func() { log.Fatal(ds.ListenAndServeTLS("", "")) }()
		log.Printf("device mTLS listener on %s (CA in %s; back up ca.key)", *deviceAddr, *pkiDir)
	} else {
		log.Print("WARNING: no -device-addr; devices connect without client certificates (dev only)")
	}
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
