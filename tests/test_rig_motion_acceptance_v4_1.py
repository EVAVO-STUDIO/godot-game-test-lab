import unittest

from tools.rig_motion_acceptance_v4_1 import (
    GodotRigAcceptanceError,
    validate_probe_receipt,
)


def receipt():
    return {
        "schemaVersion": 1,
        "kind": "evavo-godot-rig-motion-probe-v4.1",
        "family": "humanoid",
        "loadOk": True,
        "instantiateOk": True,
        "meshInstanceCount": 1,
        "motion": {
            "walk": {
                "sampleCount": 4,
                "maximumTransformDelta": 0.5,
            }
        },
        "authority": {
            "runtimeAdmission": False,
            "targetRepositoryMutation": False,
            "gitMutation": False,
            "deployment": False,
            "publication": False,
        },
    }


class GodotRigMotionTests(unittest.TestCase):
    def test_valid_receipt(self):
        validate_probe_receipt(receipt(), "humanoid")

    def test_zero_motion_rejected(self):
        value = receipt()
        value["motion"]["walk"]["maximumTransformDelta"] = 0
        with self.assertRaises(GodotRigAcceptanceError):
            validate_probe_receipt(value, "humanoid")

    def test_authority_escalation_rejected(self):
        value = receipt()
        value["authority"]["runtimeAdmission"] = True
        with self.assertRaises(GodotRigAcceptanceError):
            validate_probe_receipt(value, "humanoid")

    def test_family_mismatch_rejected(self):
        with self.assertRaises(GodotRigAcceptanceError):
            validate_probe_receipt(receipt(), "quadruped")


if __name__ == "__main__":
    unittest.main()
