#!/usr/bin/env node

import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const [requestInput, evidenceInput] = process.argv.slice(2);
if (!requestInput || !evidenceInput) {
  console.error("Usage: node scripts/compile-autonomous-godot-test-gap-finding.mjs <brain-replenishment-plan.json> <godot-gap-evidence.json>");
  process.exit(2);
}

const SHA1 = /^[0-9a-f]{40}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const CATEGORY_MAP = new Map([
  ["import-or-boot-regression", "regression-test-gap"],
  ["controller-or-focus-transition", "state-transition-test-gap"],
  ["viewport-or-safe-area-boundary", "boundary-test-gap"],
  ["native-vs-sandbox-divergence", "cross-platform-test-gap"],
  ["failure-recovery-path", "failure-path-test-gap"],
  ["runtime-contract", "contract-test-gap"],
]);
const EVIDENCE_KINDS = new Set([
  "godot-import-evidence",
  "godot-boot-evidence",
  "godot-journey-evidence",
  "godot-controller-evidence",
  "godot-ui-state-evidence",
  "godot-visual-evidence",
  "godot-audio-evidence",
  "godot-native-lane-evidence",
]);

function regularJson(value, label, maximum = 16 * 1024 * 1024) {
  const file = fs.realpathSync.native(path.resolve(value));
  const stat = fs.lstatSync(file);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`${label} must be a regular non-symlink file.`);
  const bytes = fs.readFileSync(file);
  if (bytes.length === 0 || bytes.length > maximum) throw new Error(`${label} has an invalid byte length.`);
  let document;
  try {
    document = JSON.parse(bytes.toString("utf8"));
  } catch (error) {
    throw new Error(`${label} is not valid UTF-8 JSON: ${error?.message ?? error}`);
  }
  if (!document || typeof document !== "object" || Array.isArray(document)) throw new Error(`${label} must contain a JSON object.`);
  return { document, sha256: createHash("sha256").update(bytes).digest("hex") };
}

function string(value, label, maximum = 4096) {
  if (typeof value !== "string" || !value.trim() || value.length > maximum) throw new Error(`${label} is invalid.`);
  return value.trim();
}

function score(value, label, minimum = 0, maximum = 100) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < minimum || value > maximum) {
    throw new Error(`${label} must be between ${minimum} and ${maximum}.`);
  }
  return value;
}

function safePath(value, label) {
  const text = string(value, label, 512).replaceAll("\\", "/");
  if (text.startsWith("/") || /^[A-Za-z]:\//.test(text) || /(^|\/)\.\.?(\/|$)/.test(text) || /(^|\/)\.git(\/|$)/i.test(text)) {
    throw new Error(`${label} must be a safe repository-relative path or glob.`);
  }
  return text;
}

function testOnly(value) {
  const normalized = value.toLowerCase();
  const segments = normalized.split("/");
  return (
    segments.some((segment) => ["test", "tests", "__tests__", "spec", "specs"].includes(segment)) ||
    /(?:^|\/)[^/]+\.(?:test|spec)\.[a-z0-9*{}._-]+$/.test(normalized)
  );
}

try {
  const requestSource = regularJson(requestInput, "Brain backlog replenishment plan");
  const evidenceSource = regularJson(evidenceInput, "Godot Test Lab evidence");
  const request = requestSource.document;
  const evidence = evidenceSource.document;
  if (request.schemaVersion !== 1 || request.kind !== "evavo-autonomous-spark-backlog-replenishment-plan-v1") {
    throw new Error("Brain backlog replenishment plan kind/schema is invalid.");
  }
  if (request.decision !== "REQUEST_EVIDENCE_BACKED_TEST_GAP_DISCOVERY") {
    throw new Error("Brain plan does not request test-gap discovery.");
  }
  if (request.findingsFabricated !== false || request.queueMutationPerformed !== false || request.modelTurnPerformed !== false) {
    throw new Error("Brain request exceeds planning authority.");
  }
  if (evidence.schemaVersion !== 1 || evidence.kind !== "evavo-godot-game-test-gap-evidence-v1") {
    throw new Error("Godot Test Lab evidence kind/schema is invalid.");
  }
  const repository = string(evidence.repository, "repository", 140);
  const sourceRevision = string(evidence.sourceRevision, "sourceRevision", 40).toLowerCase();
  if (!SHA1.test(sourceRevision)) throw new Error("sourceRevision is invalid.");
  const producerRequest = (request.producerRequests ?? []).find(
    (entry) =>
      entry?.producer === "EVAVO-STUDIO/godot-game-test-lab" &&
      entry?.repository === repository &&
      String(entry?.sourceRevision ?? "").toLowerCase() === sourceRevision,
  );
  if (!producerRequest) throw new Error("Godot evidence is not bound to a matching Brain producer request.");
  if (producerRequest.workerClass !== "test-generation" || producerRequest.evidenceRequired !== true || producerRequest.quotaFillerWorkAllowed !== false) {
    throw new Error("Brain producer request does not preserve Test Builder evidence/no-filler policy.");
  }
  const observedAt = string(evidence.observedAt, "observedAt", 64);
  if (!Number.isFinite(Date.parse(observedAt))) throw new Error("observedAt is invalid.");

  if (evidence.noAction === true) {
    const reason = string(evidence.noActionReason, "noActionReason", 1000);
    console.log(
      JSON.stringify(
        {
          schemaVersion: 1,
          kind: "evavo-autonomous-test-gap-no-action-v1",
          producer: "EVAVO-STUDIO/godot-game-test-lab",
          repository,
          sourceRevision,
          observedAt,
          reason,
          sourceEvidenceSha256: evidenceSource.sha256,
          requestPlanSha256: requestSource.sha256,
          validNoAction: true,
          recommendedReviewCooldownDays: 30,
          findingFabricated: false,
          workItemCompiled: false,
          queueMutationPerformed: false,
          modelTurnPerformed: false,
          targetMutationPerformed: false,
          creativeApprovalPerformed: false,
          publicationPerformed: false,
          truthBoundary:
            "Godot Test Lab found no justified test gap in the requested exact-SHA evidence scope. This useful NO_ACTION outcome suppresses repeat scanning until cooldown or an early trigger.",
        },
        null,
        2,
      ),
    );
    process.exit(0);
  }

  const gap = evidence.gap;
  if (!gap || typeof gap !== "object" || Array.isArray(gap)) throw new Error("Godot evidence requires gap or explicit noAction.");
  const godotCategory = string(gap.category, "gap.category", 80);
  const category = CATEGORY_MAP.get(godotCategory);
  if (!category || !(producerRequest.acceptedCategories ?? []).includes(category)) {
    throw new Error("Godot test-gap category is not admitted by the Brain producer request.");
  }
  const objective = string(gap.objective, "gap.objective", 2000);
  const confidence = score(gap.confidence, "gap.confidence", 0, 1);
  const impact = score(gap.impact, "gap.impact");
  const risk = score(gap.risk, "gap.risk");
  const creativeRisk = score(gap.creativeRisk, "gap.creativeRisk");
  if (confidence < producerRequest.minimumConfidence) throw new Error("Godot test-gap confidence is below threshold.");
  if (risk > producerRequest.maximumRisk) throw new Error("Godot test-gap risk exceeds threshold.");
  if (creativeRisk !== 0 || creativeRisk > producerRequest.maximumCreativeRisk) throw new Error("Godot test-gap creative risk must remain zero.");

  if (!Array.isArray(evidence.records) || evidence.records.length < 1 || evidence.records.length > 32) {
    throw new Error("Godot evidence requires between one and 32 records.");
  }
  const records = evidence.records.map((entry, index) => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) throw new Error(`records[${index}] must be an object.`);
    const kind = string(entry.kind, `records[${index}].kind`, 120);
    if (!EVIDENCE_KINDS.has(kind)) throw new Error(`records[${index}].kind is not admitted Godot evidence.`);
    const digest = string(entry.sha256, `records[${index}].sha256`, 64).toLowerCase();
    if (!SHA256.test(digest)) throw new Error(`records[${index}].sha256 is invalid.`);
    return {
      kind,
      sha256: digest,
      reference: entry.reference == null ? null : string(entry.reference, `records[${index}].reference`, 512),
    };
  });

  if (!Array.isArray(gap.allowedPaths) || gap.allowedPaths.length < 1 || gap.allowedPaths.length > 16) {
    throw new Error("gap.allowedPaths must contain between one and 16 paths.");
  }
  const allowedPaths = gap.allowedPaths.map((value, index) => safePath(value, `gap.allowedPaths[${index}]`));
  if (allowedPaths.some((value) => !testOnly(value))) throw new Error("Godot Test Builder allowed paths must remain test-only.");
  if (!Array.isArray(gap.requiredValidation) || gap.requiredValidation.length < 1 || gap.requiredValidation.length > 16) {
    throw new Error("gap.requiredValidation must contain between one and 16 steps.");
  }

  console.log(
    JSON.stringify(
      {
        schemaVersion: 1,
        kind: "evavo-autonomous-test-gap-finding-v1",
        producer: "EVAVO-STUDIO/godot-game-test-lab",
        repository,
        sourceRevision,
        repoTier: producerRequest.repoTier,
        repositoryLifecycleState: producerRequest.repositoryLifecycleState,
        testGenerationAutonomyAllowed: true,
        category,
        objective,
        confidence,
        impact,
        risk,
        creativeRisk: 0,
        effort: score(gap.effort, "gap.effort", 1, 100),
        compoundingValue: score(gap.compoundingValue ?? 0, "gap.compoundingValue"),
        reliabilityGain: score(gap.reliabilityGain ?? impact, "gap.reliabilityGain"),
        evidence: records,
        allowedPaths,
        forbiddenPaths: Array.isArray(gap.forbiddenPaths)
          ? gap.forbiddenPaths.map((value, index) => safePath(value, `gap.forbiddenPaths[${index}]`))
          : [],
        requiredValidation: gap.requiredValidation,
        observedAt,
        sourceEvidenceSha256: evidenceSource.sha256,
        requestPlanSha256: requestSource.sha256,
        godotEvidenceCategory: godotCategory,
        findingFabricated: false,
        codeGenerated: false,
        workItemCompiled: false,
        queueMutationPerformed: false,
        modelTurnPerformed: false,
        targetMutationPerformed: false,
        creativeApprovalPerformed: false,
        publicationPerformed: false,
        truthBoundary:
          "This finding translates exact-SHA Godot Test Lab evidence into the canonical Development Studio test-gap envelope. It does not generate tests, mutate the game, compile/enqueue work, start Spark, approve creative work or publish.",
      },
      null,
      2,
    ),
  );
} catch (error) {
  console.error(
    JSON.stringify(
      {
        schemaVersion: 1,
        kind: "evavo-godot-autonomous-test-gap-producer-error-v1",
        accepted: false,
        errorType: error?.constructor?.name ?? "Error",
        errorMessage: String(error?.message ?? error).slice(0, 4096),
        findingFabricated: false,
        codeGenerated: false,
        queueMutationPerformed: false,
        modelTurnPerformed: false,
        targetMutationPerformed: false,
        publicationPerformed: false,
      },
      null,
      2,
    ),
  );
  process.exit(1);
}
