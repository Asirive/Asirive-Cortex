# Asirive Cortex — Website FAQ

> Navigation-first. Every answer is grounded in what the device actually does.
> Safety is always framed as **the trust layer**, never the product. The cane is always the hero.

---

## A. The core questions (what everyone asks first)

**Q1 · "Is this a safety device or a navigation device?"**

> Navigation. Cortex is built to get you somewhere independently — turn-by-turn, indoor, and on the bus. Safety is the trust layer underneath: it runs fully on-device in <100ms so you can navigate without scanning the ground yourself. The cane stays the ground sensor; Cortex is the guide.

**Q2 · "Does this replace the white cane?"**

> No — and that's the whole point. The cane is the best ground sensor ever made. Cortex is designed around it, not against it. It only speaks for what the cane can't feel — things at head height, stairs going up, and fast-approaching people or vehicles. Cane stays the cane. AI is co-pilot.

**Q3 · "What does it actually do?"**

> Three jobs, hands-free:
> - **Get there** — turn-by-turn voice over GPS, outdoors.
> - **Don't stop** — camera-led guidance indoors where GPS fails.
> - **Ride the bus** — live Singapore bus arrivals, no phone.
> Plus saved places, and a spoken conversation with the device.

**Q4 · "How much does it cost?"**

> **$186 to build (BOM), $250 to buy.** That's roughly **1/10** of the $2,500–$3,000 premium devices (OrCam, eSight). Built on a Raspberry Pi 5 + Hailo-8L edge AI — powerful enough to navigate, cheap enough for the global south, where premium assistive tech never reaches.

---

## B. The technical / "how does it work" questions

**Q5 · "How does it know I'm at a bus stop without me telling it?"**

> It detects automatically. The device reads its GPS and finds the nearest bus stop (from a local bus-stop database). When you're within a few metres, it starts monitoring **live LTA DataMall arrivals** and speaks them — *"Bus 174 in 4 minutes, platform 2."* Then the camera's **YOLO bus detector** confirms visually when the bus actually appears. Two systems checking each other.

**Q6 · "What if there's no internet?"**

> It keeps guiding you. A **ConnectivityMonitor** measures the actual connection every 3 seconds (never guesses) across a 4-level scale — FULL, DEGRADED, INTERMITTENT, OFFLINE. If you go offline it tells you honestly: *"I've lost connection. Don't worry, I'm still guiding you."* Route-following and safety run **on the device**, so losing the internet never stops you moving.

**Q7 · "How does indoor navigation work if GPS can't reach?"**

> Indoors, GPS fails — so Cortex switches to **camera-led Guide Mode**. And it has a trick: because it knows your **saved locations**, you can say *"I'm at home, navigate to North Point"* and it uses your home address as the starting point — no GPS required.

**Q8 · "How does it handle a trip with walking + bus + MRT?"**

> It splits the journey into **legs** (walk / bus / MRT) and tracks which one you're in. So it won't tell you to "turn left in 300 metres" while you're on the bus — it knows you're on the bus, counts the stops, and tells you when to alight.

**Q9 · "Does it need a screen or app?"**

> No screen. It's **audio-first** — everything is spoken through open-ear earbuds, so you still hear the world around you. The white cane stays in your hand the whole time.

**Q10 · "Is my data private?"**

> The safety and navigation brains run **on the device itself**. The conversation layer only connects to the cloud when you ask a question. Detection and guidance data is stored locally and synced to the cloud in batches for your own memory — not streamed continuously.

---

## C. The validation / credibility questions

**Q11 · "Who is this built for, really?"**

> People who use a cane and want to move through the world alone — the clinic, the mosque, the hawker centre, the bus home — without a sighted companion narrating every step. Independence, not assistance.

**Q12 · "Have real users tested it?"**

> Yes. We co-designed Cortex with **SAVH** — the Singapore Association of the Visually Handicapped — across 3 sessions (1 online + 2 physical). The cane-aware design came directly from that feedback. We didn't build this in a garage; we've been in the field.

**Q13 · "What's the story behind the cane-aware design?"**

> A SAVH user was tapping the air above her head with her cane, trying to find a ceiling fan she couldn't see. The cane is brilliant at the ground — but it has a blind spot at head height. That moment showed us exactly where AI belongs: **not replacing the cane, but filling its blind spot.**

**Q14 · "How is this different from Google or Meta shipping AI glasses?"**

> They ship features; we ship a use case. Their glasses are built for sighted people — screens, notifications, cameras in the frame. Cortex is built around how a cane user actually navigates, with cane-aware depth understanding that no feature set can bolt on.

---

## D. The roadmap / "what's next" questions

**Q15 · "What's the long-term vision?"**

> A companion app and an SDK for city-specific integrations (Singapore's LTA is the first). We're working toward a pilot with SAVH volunteers using Cortex in daily life — the real-world test that turns a great demo into a product.

**Q16 · "Are you a real company?"**

> We're a student team building this for the Tan Kah Kee Young Inventors' Award (a finalist) — and we're treating it like a real venture. The product, the code, and the field validation are real. You can see the public repository and the working device.

---

## Two principles behind these FAQs

1. **Honest, not defensive** — every answer owns a real design decision (e.g., "we lose connection, here's what happens"). This builds more trust than a perfect feature list.
2. **Navigation-first, cane-aware throughout** — safety is always framed as *the trust layer*, never the product. The cane is always the hero.
