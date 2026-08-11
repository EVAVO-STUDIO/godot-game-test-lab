from __future__ import annotations

import binascii
import hashlib
import json
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

from godot_game_test_lab.game_asset_delivery_admission import (
    AUTHORITY,
    admit_game_asset_delivery,
    hash_object,
    write_report_create_only,
)


def png(width: int, height: int, rgba=(255, 255, 255, 255)) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + bytes(rgba) * width for _ in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class GameAssetDeliveryAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="evavo-test-lab-game-assets-")
        self.root = Path(self.temp.name)
        self.game = self.root / "game"
        self.game.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.game, check=True)
        subprocess.run(["git", "config", "user.name", "EVAVO Test"], cwd=self.game, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.game, check=True)
        (self.game / "project.godot").write_text('[application]\nconfig/name="Fixture"\n', encoding="utf-8")
        subprocess.run(["git", "add", "project.godot"], cwd=self.game, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=self.game, check=True)
        self.head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.game, check=True, capture_output=True, text=True
        ).stdout.strip()
        self.contract_path = Path(__file__).resolve().parents[1] / "config" / "game-asset-delivery-admission.v1.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def documents(self, *, approved: bool = True, native: bool = False) -> tuple[Path, Path, Path | None]:
        assets = self.game / "assets" / "generated"
        assets.mkdir(parents=True, exist_ok=True)
        atlas = png(8, 8)
        screenshot = png(320, 180, (17, 17, 17, 255))
        font = (
            'info face="EVAVO" size=8 bold=0 italic=0 charset="" unicode=1 stretchH=100 smooth=0 aa=1 padding=0,0,0,0 spacing=1,1\n'
            'common lineHeight=8 base=7 scaleW=8 scaleH=8 pages=1 packed=0\n'
            'page id=0 file="atlas.png"\n'
            'chars count=1\n'
            'char id=65 x=0 y=0 width=4 height=7 xoffset=0 yoffset=0 xadvance=5 page=0 chnl=15\n'
        ).encode()
        scene = b'[gd_resource type="FontVariation" load_steps=2 format=3]\n\n[ext_resource type="FontFile" path="res://assets/generated/font.fnt" id="1"]\n\n[resource]\nbase_font = ExtResource("1")\n'
        files = {
            "atlas": ("pixel-font-atlas", "pixel-font", "assets/generated/atlas.png", atlas),
            "font": ("pixel-font-descriptor", "pixel-font", "assets/generated/font.fnt", font),
            "resource": ("godot-resource", "title", "assets/generated/font.tres", scene),
        }
        items = []
        stored = []
        for asset_id, (kind, role, target, data) in files.items():
            path = self.game / target
            path.write_bytes(data)
            items.append(
                {
                    "assetId": asset_id,
                    "kind": kind,
                    "role": role,
                    "targetPath": target,
                    "sha256": sha(data),
                    "bytes": len(data),
                }
            )
            stored.append(
                {
                    "assetId": asset_id,
                    "targetPath": target,
                    "logicalPath": f"Projects/brass-brine/GameAssets/run/{target}",
                    "sha256": sha(data),
                    "bytes": len(data),
                    "documentId": f"doc-{asset_id}",
                    "versionId": f"version-{asset_id}",
                }
            )
        delivery = {
            "schema": "evavo.game-asset-delivery-bundle.v2",
            "status": "approved" if approved else "review-required",
            "projectId": "brass-brine",
            "gameRepository": "EVAVO-STUDIO/Brass_Brine",
            "gameHead": self.head,
            "requiredRoles": ["body", "pixel-font", "title"],
            "items": items,
            "summary": {"itemCount": len(items)},
            "creativeApproval": approved,
            "historicalApproval": approved,
            "provenanceApproval": approved,
            "nativeCompositionApproval": False,
            "publicationAuthority": False,
            "authority": {
                "automaticApproval": False,
                "candidatePromotion": False,
                "gameRepositoryMutation": False,
                "gitCommit": False,
                "gitPush": False,
                "providerExecution": False,
                "publication": False,
                "sourceDeletion": False,
                "storageWrite": False,
                "forcePush": False,
            },
        }
        delivery["bundleSha256"] = hash_object(delivery)
        delivery["runId"] = delivery["bundleSha256"][:20]
        storage = {
            "schema": "evavo.storage-game-asset-admission.v1",
            "status": "stored" if approved else "review-required",
            "gameHead": self.head,
            "delivery": {"bundleSha256": delivery["bundleSha256"]},
            "items": stored,
            "summary": {"itemCount": len(stored)},
            "authority": {
                "automaticApproval": False,
                "candidatePromotion": False,
                "gameRepositoryMutation": False,
                "gitCommit": False,
                "gitPush": False,
                "providerExecution": False,
                "publication": False,
                "sourceDeletion": False,
                "physicalPurge": False,
                "forcePush": False,
            },
        }
        storage["admissionSha256"] = hash_object(storage)
        storage["runId"] = storage["admissionSha256"][:20]
        delivery_path = write_json(self.root / "delivery.json", delivery)
        storage_path = write_json(self.root / "storage.json", storage)
        native_path = None
        if native:
            screenshots = self.root / "screenshots"
            screenshots.mkdir()
            screenshot_records = []
            for role in ["animation", "atlas", "body", "pixel-font", "title"]:
                path = screenshots / f"{role}.png"
                path.write_bytes(screenshot)
                screenshot_records.append(
                    {"role": role, "path": str(path), "sha256": sha(screenshot), "bytes": len(screenshot)}
                )
            evidence = {
                "schema": "evavo.godot-game-asset-native-evidence.v1",
                "status": "passed",
                "gameHead": self.head,
                "godotVersion": "4.6.2.stable.mono",
                "renderer": "gl_compatibility",
                "importErrors": [],
                "consoleErrors": [],
                "renderedRoles": ["animation", "atlas", "body", "pixel-font", "title"],
                "screenshots": screenshot_records,
            }
            evidence["evidenceSha256"] = hash_object(evidence)
            evidence["runId"] = evidence["evidenceSha256"][:20]
            native_path = write_json(self.root / "native.json", evidence)
        return delivery_path, storage_path, native_path

    def admit(self, approved: bool = True, native: bool = False) -> dict:
        delivery, storage, native_path = self.documents(approved=approved, native=native)
        return admit_game_asset_delivery(
            self.game, self.head, delivery, storage, self.contract_path, native_path
        )

    def test_approved_source_is_native_pending(self) -> None:
        report = self.admit()
        self.assertEqual(report["status"], "source-passed-native-pending")
        self.assertFalse(report["nativeCompositionApproval"])
        self.assertFalse(report["nativeEvidencePassed"])
        self.assertTrue(all(value is False for value in report["authority"].values()))

    def test_native_evidence_produces_technical_pass_without_approval(self) -> None:
        report = self.admit(native=True)
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["nativeEvidencePassed"])
        self.assertFalse(report["nativeCompositionApproval"])
        self.assertFalse(report["publicationAuthority"])

    def test_review_required_cannot_be_promoted_by_native_evidence(self) -> None:
        report = self.admit(approved=False, native=True)
        self.assertEqual(report["status"], "review-required")
        self.assertFalse(report["nativeCompositionApproval"])

    def test_installed_byte_tamper_is_rejected(self) -> None:
        delivery, storage, _ = self.documents()
        (self.game / "assets/generated/atlas.png").write_bytes(png(9, 8))
        with self.assertRaisesRegex(ValueError, "installed asset identity differs"):
            admit_game_asset_delivery(self.game, self.head, delivery, storage, self.contract_path)

    def test_bad_bmfont_smoothing_is_rejected(self) -> None:
        delivery, storage, _ = self.documents()
        path = self.game / "assets/generated/font.fnt"
        path.write_text(path.read_text().replace("smooth=0", "smooth=1"), encoding="utf-8")
        delivery_value = json.loads(delivery.read_text())
        data = path.read_bytes()
        font = next(item for item in delivery_value["items"] if item["assetId"] == "font")
        font["sha256"], font["bytes"] = sha(data), len(data)
        delivery_value.pop("bundleSha256")
        delivery_value.pop("runId")
        delivery_value["bundleSha256"] = hash_object(delivery_value)
        delivery_value["runId"] = delivery_value["bundleSha256"][:20]
        write_json(delivery, delivery_value)
        storage_value = json.loads(storage.read_text())
        stored = next(item for item in storage_value["items"] if item["assetId"] == "font")
        stored["sha256"], stored["bytes"] = sha(data), len(data)
        storage_value["delivery"]["bundleSha256"] = delivery_value["bundleSha256"]
        storage_value.pop("admissionSha256")
        storage_value.pop("runId")
        storage_value["admissionSha256"] = hash_object(storage_value)
        storage_value["runId"] = storage_value["admissionSha256"][:20]
        write_json(storage, storage_value)
        with self.assertRaisesRegex(ValueError, "smooth=0"):
            admit_game_asset_delivery(self.game, self.head, delivery, storage, self.contract_path)

    def test_create_only_report(self) -> None:
        report = self.admit()
        output = self.root / "report.json"
        write_report_create_only(output, report)
        self.assertTrue(output.is_file())
        with self.assertRaises(FileExistsError):
            write_report_create_only(output, report)


if __name__ == "__main__":
    unittest.main()
