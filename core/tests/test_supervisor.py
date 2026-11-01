from cortex_core.supervisor.supervisor import Spec, Supervisor


class H:
    def __init__(self): self.rc, self.killed = None, False
    def poll(self): return self.rc
    def kill(self): self.killed, self.rc = True, -9


class L:
    def __init__(self): self.started, self.handles = [], {}
    def start(self, spec):
        h = H(); self.started.append(spec.name); self.handles.setdefault(spec.name, []).append(h); return h


class HB:
    def __init__(self): self.t = {}
    def last(self, n): return self.t.get(n)


class WD:
    pets = 0
    def pet(self): WD.pets += 1


class Clock:
    t = 1000.0
    def __call__(self): return Clock.t


def rig():
    WD.pets, Clock.t = 0, 1000.0
    degraded = []
    specs = [Spec("safety", ["s"], 1.0, True), Spec("link", ["l"], 5.0, True), Spec("ota", ["o"], 60.0)]
    l, hb = L(), HB()
    return Supervisor(specs, l, hb, WD(), degraded.append, Clock()), l, hb, degraded


def beat_all(hb):
    for n in ("safety", "link", "ota"): hb.t[n] = Clock.t


def adv(s, hb, dt=0.5, beat=True):
    Clock.t += dt
    if beat: beat_all(hb)
    s.tick()


def test_starts_in_order_and_pets_only_when_safety_and_link_are_healthy():
    s, l, hb, _ = rig()
    s.tick()
    assert l.started == ["safety", "link", "ota"]
    beat_all(hb); adv(s, hb)
    assert WD.pets >= 1
    before = WD.pets
    s.runs["link"].handle.rc = 1       # link crashes
    adv(s, hb)
    assert WD.pets == before            # watchdog starves while link is down


def test_ota_down_does_not_starve_the_watchdog():
    s, l, hb, _ = rig()
    s.tick(); beat_all(hb); adv(s, hb)
    s.runs["ota"].handle.rc = 1
    before = WD.pets
    adv(s, hb)
    assert WD.pets > before


def test_crash_restarts_with_exponential_backoff_capped():
    s, l, hb, _ = rig()
    s.tick(); beat_all(hb)
    gaps = []
    for _ in range(8):
        h = s.runs["ota"].handle
        h.rc = 1
        t_crash = Clock.t
        s.tick()                                    # notices exit, schedules restart
        while s.runs["ota"].handle is None:
            adv(s, hb, 0.25)
        gaps.append(round(Clock.t - t_crash))
    assert gaps[:4] == [1, 2, 4, 8] and max(gaps) <= 31 and gaps == sorted(gaps)


def test_stalled_heartbeat_kills_restarts_and_announces_degraded():
    s, l, hb, degraded = rig()
    s.tick(); beat_all(hb); adv(s, hb)
    first = s.runs["safety"].handle
    for _ in range(4):                               # safety stops beating; others keep going
        Clock.t += 0.5; hb.t["link"] = hb.t["ota"] = Clock.t; s.tick()
    assert first.killed and degraded == ["safety"]
    assert s.status()["safety"]["restarts"] == 1


def test_new_process_gets_a_grace_period_before_stall_detection():
    s, l, hb, degraded = rig()
    s.tick()                                         # nothing has beaten yet
    Clock.t += 0.5; s.tick()
    assert degraded == []


def test_backoff_resets_after_a_stable_run():
    s, l, hb, _ = rig()
    s.tick(); beat_all(hb)
    r = s.runs["ota"]
    r.handle.rc = 1; s.tick()
    while r.handle is None: adv(s, hb, 0.5)
    assert r.backoff == 2.0
    for _ in range(130): adv(s, hb, 1.0)             # runs stably for >60 s
    r.handle.rc = 1; s.tick()
    assert r.next_start - Clock.t <= 1.0


def test_systemd_launcher_drives_units_not_processes():
    from cortex_core.supervisor.supervisor import SystemdLauncher
    calls, active = [], [True]
    def run(a): calls.append(a); return 0 if (a[1] != "is-active" or active[0]) else 3
    h = SystemdLauncher(run).start(Spec("safety", []))
    assert calls[0] == ["systemctl", "restart", "cortex-safety.service"] and h.poll() is None
    active[0] = False
    assert h.poll() == 1
    h.kill()
    assert calls[-1][:2] == ["systemctl", "kill"]
