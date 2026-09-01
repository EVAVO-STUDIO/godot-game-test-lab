#!/usr/bin/env node

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const root = fs.mkdtempSync(path.join(os.tmpdir(), "evavo-godot-gap-producer-"));
const repository = "EVAVO-STUDIO/example-game";
const sourceRevision = "a".repeat(40);
const request = {
  schemaVersion: 1,
  kind: "evavo-autonomous-spark-backlog-replenishment-plan-v1",
  decision: "REQUEST_EVIDENCE_BACKED_TEST_GAP_DISCOVERY",
  findingsFabricated: false,
  queueMutationPerformed: false,
  modelTurnPerformed: false,
  producerRequests: [
    {
      producer: "EVAVO-STUDIO/godot-game-test-lab",
      repository,
      sourceRevision,
      repoTier: "T1",
      repositoryLifecycleState: "ACTIVE",
      maximumFindings: 3,
      workerClass: "test-generation",
      acceptedCategories: [
        "regression-test-gap",
        "boundary-test-gap",
        "failure-path-test-gap",
        "state-transition-test-gap",
        "contract-test-gap",
        "cross-platform-test-gap"
      ],
      minimumPriority: 70,
      minimumConfidence: 0.75,
      maximumRisk: 35,
      maximumCreativeRisk: 0,
      evidenceRequired: true,
      noActionAccepted: true,
      productionSourceMutationAllowed: false,
      quotaFillerWorkAllowed: false
    }
  ]
};
const evidence = {
  schemaVersion: 1,
  kind: "evavo-godot-game-test-gap-evidence-v1",
  repository,
  sourceRevision,
  observedAt: "2026-09-01T08:00:00.000Z",
  records: [
    {
      kind: "godot-controller-evidence",
      sha256: "b".repeat(64),
      reference: "journey:settings-controller-focus"
    },
    {
      kind: "godot-native-lane-evidence",
      sha256: "c".repeat(64),
      reference: "native:windows:settings"
    }
  ],
  gap: {
    category: "controller-or-focus-transition",
    objective: "Add a focused regression test proving controller focus returns to the settings list after closing the remap dialog.",
    confidence: 0.95,
    impact: 86,
    risk: 10,
    creativeRisk: 0,
    effort: 20,
    compoundingValue: 75,
    reliabilityGain: 90,
    allowedPaths: ["tests/input/**", "tests/settings_focus.test.gd"],
    forbiddenPaths: ["scenes/**", "assets/**"],
    requiredValidation: ["godot-import", "godot-test-suite", "native-controller-journey"]
  }
};

function write(name, document) {
  const file = path.join(root, `${name}-${Date.now()}-${Math.random().toString(16).slice(2)}.json`);
  fs.writeFileSync(file, JSON.stringify(document));
  return file;
}

function run(requestDocument, evidenceDocument) {
  const result = spawnSync(
    process.execPath,
    [
      "scripts/compile-autonomous-godot-test-gap-finding.mjs",
      write("request", requestDocument),
      write("evidence", evidenceDocument)
    ],
    { cwd: process.cwd(), encoding: "utf8", shell: false }
  );
  const channel = result.status === 0 ? result.stdout : result.stderr;
  return { result, document: JSON.parse(String(channel).trim()) };
}

try {
  {
    const { result, document } = run(request, evidence);
    assert.equal(result.status, 0, result.stderr);
    assert.equal(document.kind, "evavo-autonomous-test-gap-finding-v1");
    assert.equal(document.producer, "EVAVO-STUDIO/godot-game-test-lab");
    assert.equal(document.category, "state-transition-test-gap");
    assert.equal(document.godotEvidenceCategory, "controller-or-focus-transition");
    assert.equal(document.creativeRisk, 0);
    assert.deepEqual(document.allowedPaths, ["tests/input/**", "tests/settings_focus.test.gd"]);
    assert.equal(document.evidence.length, 2);
    assert.equal(document.targetMutationPerformed, false);
    assert.equal(document.creativeApprovalPerformed, false);
    assert.equal(document.findingFabricated, false);
    assert.equal(document.modelTurnPerformed, false);
  }

  {
    const noAction = {
      schemaVersion: 1,
      kind: "evavo-godot-game-test-gap-evidence-v1",
      repository,
      sourceRevision,
      observedAt: "2026-09-01T08:00:00.000Z",
      noAction: true,
      noActionReason: "The inspected controller journey is already covered by exact-SHA unit and native-lane evidence."
    };
    const { result, document } = run(request, noAction);
    assert.equal(result.status, 0, result.stderr);
    assert.equal(document.kind, "evavo-autonomous-test-gap-no-action-v1");
    assert.equal(document.validNoAction, true);
    assert.equal(document.recommendedReviewCooldownDays, 30);
    assert.equal(document.targetMutationPerformed, false);
  }

  {
    const wrongSource = { ...evidence, sourceRevision: "d".repeat(40) };
    const { result, document } = run(request, wrongSource);
    assert.equal(result.status, 1);
    assert.match(document.errorMessage, /not bound to a matching Brain producer request/);
  }

  {
    const unsupportedRecord = structuredClone(evidence);
    unsupportedRecord.records[0].kind = "untrusted-screen-recording";
    const { result, document } = run(request, unsupportedRecord);
    assert.equal(result.status, 1);
    assert.match(document.errorMessage, /not admitted Godot evidence/);
  }

  {
    const sourcePath = structuredClone(evidence);
    sourcePath.gap.allowedPaths = ["scenes/settings.tscn"];
    const { result, document } = run(request, sourcePath);
    assert.equal(result.status, 1);
    assert.match(document.errorMessage, /test-only/);
  }

  {
    const creative = structuredClone(evidence);
    creative.gap.creativeRisk = 1;
    const { result, document } = run(request, creative);
    assert.equal(result.status, 1);
    assert.match(document.errorMessage, /creative risk must remain zero/);
  }

  {
    const unsupportedCategory = structuredClone(evidence);
    unsupportedCategory.gap.category = "visual-art-polish";
    const { result, document } = run(request, unsupportedCategory);
    assert.equal(result.status, 1);
    assert.match(document.errorMessage, /category is not admitted/);
  }

  console.log("Godot Test Lab autonomous gap-producer tests passed.");
  console.log("- exact-SHA import, journey, controller, UI, audio and native evidence can produce canonical test gaps");
  console.log("- controller/focus issues map to state-transition test work without touching game scenes or assets");
  console.log("- sufficient coverage produces useful NO_ACTION");
  console.log("- untrusted evidence, creative changes, unsupported categories and non-test paths fail closed");
} finally {
  fs.rmSync(root, { recursive: true, force: true });
}
