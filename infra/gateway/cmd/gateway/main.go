package main

import (
	"flag"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/asirive/cortex/gateway/internal/fleet"
	"github.com/asirive/cortex/gateway/internal/server"
)

func main() {
	addr := flag.String("addr", ":8080", "listen address")
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
	log.Printf("cortex gateway listening on %s", *addr)
	log.Fatal(http.ListenAndServe(*addr, server.New(f, token).Handler()))
}
