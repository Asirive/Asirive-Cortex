// simdevice connects fake devices to a gateway so the fleet view has data.
package main

import (
	"flag"
	"fmt"
	"log"
	"math/rand"
	"net/http"
	"os"
	"sync"
	"time"

	pb "github.com/asirive/cortex/gateway/internal/gen/cortex/v1"
	"github.com/gorilla/websocket"
	"google.golang.org/protobuf/proto"
)

func main() {
	url := flag.String("url", "ws://localhost:8080/ws/device", "gateway device endpoint")
	alpha := flag.Int("alpha", 3, "alpha bench devices")
	beta := flag.Int("beta", 3, "beta devices")
	stable := flag.Int("stable", 2, "stable devices")
	flag.Parse()
	tok := os.Getenv("CORTEX_DEV_TOKEN")
	var wg sync.WaitGroup
	run := func(id string, tier pb.Tier, ring pb.Ring, bench bool) {
		wg.Add(1)
		go func() { defer wg.Done(); device(*url, tok, id, tier, ring, bench) }()
	}
	for i := 1; i <= *alpha; i++ {
		run(fmt.Sprintf("ALPHA-%03d", i), pb.Tier_TIER_ALPHA, pb.Ring_RING_ALPHA, true)
	}
	for i := 1; i <= *beta; i++ {
		run(fmt.Sprintf("BETA-%03d", i), pb.Tier_TIER_BETA, pb.Ring_RING_BETA, false)
	}
	for i := 1; i <= *stable; i++ {
		run(fmt.Sprintf("STBL-%03d", i), pb.Tier_TIER_STABLE, pb.Ring_RING_STABLE, false)
	}
	wg.Wait()
}

func device(url, tok, id string, tier pb.Tier, ring pb.Ring, bench bool) {
	var seq uint64
	for {
		h := http.Header{"Authorization": {"Bearer " + tok}}
		ws, _, err := websocket.DefaultDialer.Dial(url, h)
		if err != nil {
			log.Printf("%s dial: %v", id, err)
			time.Sleep(3 * time.Second)
			continue
		}
		send := func(t pb.PayloadType, m proto.Message) {
			pl, _ := proto.Marshal(m)
			seq++
			b, _ := proto.Marshal(&pb.Envelope{Header: &pb.Header{SchemaVersion: 1, DeviceId: id, Seq: seq,
				TsMs: time.Now().UnixMilli()}, Type: t, Payload: pl})
			ws.WriteMessage(websocket.BinaryMessage, b)
		}
		seq = 0
		send(pb.PayloadType_PAYLOAD_TYPE_HELLO, &pb.Hello{Tier: tier, Ring: ring, FirmwareVersion: "4.0.0-alpha.3",
			McuVersion: "0.2.1", ModelVersion: "lfm3-omni-2b-q4", Hardware: "dragon-q8b", BenchDevice: bench, HeartbeatIntervalS: 5})
		go func() { // drain gateway messages (commands, ack)
			for {
				_, data, err := ws.ReadMessage()
				if err != nil {
					return
				}
				var e pb.Envelope
				if proto.Unmarshal(data, &e) == nil && e.Type == pb.PayloadType_PAYLOAD_TYPE_OTA_OFFER {
					var o pb.OtaOffer
					proto.Unmarshal(e.Payload, &o)
					id := o.Manifest.ReleaseId
					send(pb.PayloadType_PAYLOAD_TYPE_OTA_PROGRESS, &pb.OtaProgress{ReleaseId: id, Stage: pb.OtaStage_OTA_STAGE_DOWNLOADING, Percent: 50})
					time.Sleep(2 * time.Second)
					out := pb.OtaOutcome_OTA_OUTCOME_COMMITTED
					if os.Getenv("SIM_FAIL_OTA") != "" {
						out = pb.OtaOutcome_OTA_OUTCOME_ROLLED_BACK
					}
					send(pb.PayloadType_PAYLOAD_TYPE_OTA_RESULT, &pb.OtaResult{ReleaseId: id, Outcome: out, RunningVersion: "4.0.1"})
				}
				if proto.Unmarshal(data, &e) == nil && e.Type == pb.PayloadType_PAYLOAD_TYPE_DEBUG_COMMAND {
					var c pb.DebugCommand
					proto.Unmarshal(e.Payload, &c)
					send(pb.PayloadType_PAYLOAD_TYPE_DEBUG_RESULT, &pb.DebugResult{CommandId: c.CommandId, Ok: true, Output: "ran " + c.Name})
				}
			}
		}()
		batt := uint32(50 + rand.Intn(50))
		for i := 0; ; i++ {
			brain := pb.BrainMode_BRAIN_MODE_LOCAL
			if rand.Intn(10) == 0 {
				brain = pb.BrainMode_BRAIN_MODE_CLOUD
			}
			safety := pb.SafetyState_SAFETY_STATE_OK
			if rand.Intn(40) == 0 {
				safety = pb.SafetyState_SAFETY_STATE_DEGRADED
			}
			send(pb.PayloadType_PAYLOAD_TYPE_HEARTBEAT, &pb.Heartbeat{BatteryPct: batt, Safety: safety, Brain: brain,
				Link: pb.LinkKind_LINK_KIND_USB_TETHER, LinkRttMs: int32(30 + rand.Intn(60)), UptimeS: uint32(i * 5),
				SocTempC: 48 + rand.Float32()*14, PowerW: 3 + rand.Float32()*3, MemUsedMb: uint32(4200 + rand.Intn(1500)),
				SafetyLatencyP99Ms: uint32(40 + rand.Intn(40))})
			now := time.Now().UnixMilli()
			send(pb.PayloadType_PAYLOAD_TYPE_LOG_BATCH, &pb.LogBatch{Entries: []*pb.LogEntry{
				{TsMs: now, Level: pb.LogLevel_LOG_LEVEL_DEBUG, Service: "perception", Message: "frame batch ok"},
				{TsMs: now, Level: pb.LogLevel_LOG_LEVEL_INFO, Service: "agent", Message: "brain=" + brain.String()},
			}})
			if safety != pb.SafetyState_SAFETY_STATE_OK {
				send(pb.PayloadType_PAYLOAD_TYPE_EVENT, &pb.Event{TsMs: now, Kind: "service_restart", Summary: "safety restarted by supervisor"})
			}
			if i%6 == 5 {
				batt--
			}
			time.Sleep(5 * time.Second)
		}
	}
}
