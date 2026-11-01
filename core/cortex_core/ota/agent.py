"""OTA agent: verify -> stage -> switch, and post-boot confirm. Transport (app/gateway) is out of scope."""
import time
from typing import Callable

from cortex_core.contracts import ota_pb2
from cortex_core.ota.slots import Slots
from cortex_core.ota.verify import OtaError, verify_artifact, verify_manifest


class OtaAgent:
    def __init__(self, slots: Slots, pubkey: bytes, ring: int, self_test: Callable[[], bool],
                 clock: Callable[[], float] = time.time):
        self.slots, self.pub, self.ring, self.self_test, self.clock = slots, pubkey, ring, self_test, clock

    def apply(self, m: ota_pb2.Manifest, fetch: Callable[[ota_pb2.Artifact], bytes]) -> ota_pb2.OtaResult:
        """Install the compute-firmware artifact of a manifest. Nothing is downloaded before the signature checks out."""
        res = ota_pb2.OtaResult(release_id=m.release_id)
        try:
            verify_manifest(m, self.pub, self.ring, self.slots.counter, int(self.clock() * 1000))
            if m.version_counter <= self.slots.counter:
                raise OtaError("already at or beyond this release")
            art = next((a for a in m.artifacts if a.kind == ota_pb2.ARTIFACT_KIND_COMPUTE_FIRMWARE), None)
            if art is None:
                raise OtaError("no compute firmware in this release")
            data = fetch(art)
            verify_artifact(art, data)
            self.slots.stage(art.version, m.version_counter, m.release_id, data, art.sha256)
            self.slots.switch(m.release_id, m.version_counter)
            res.outcome, res.detail = ota_pb2.OTA_OUTCOME_UNSPECIFIED, "staged; reboot to try"
        except OtaError as e:
            res.outcome, res.detail = e.outcome, str(e)
        return res

    def after_boot(self, release_id: str) -> ota_pb2.OtaResult:
        """Run by the freshly booted slot: commit only if the safety self-test passes, else stay pending so trials run out."""
        res = ota_pb2.OtaResult(release_id=release_id)
        if self.self_test() and self.slots.confirm(release_id):
            res.outcome = ota_pb2.OTA_OUTCOME_COMMITTED
            res.running_version = self.slots.s["slots"][self.slots.active]["version"]
        else:
            res.outcome, res.detail = ota_pb2.OTA_OUTCOME_ROLLED_BACK, "self-test failed; will roll back"
        return res
