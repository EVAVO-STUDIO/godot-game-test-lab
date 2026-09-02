import {
  generateKeyPairSync,
  sign,
} from "node:crypto";
import {
  chmod,
  mkdir,
  readFile,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import { createInterface } from "node:readline";
import { dirname, resolve } from "node:path";

const playerId = requiredEnv("EVAVO_TEST_PLAYER_ID", 96);
const displayName = requiredEnv("EVAVO_TEST_DISPLAY_NAME", 96);
const deviceId = requiredEnv("EVAVO_TEST_DEVICE_ID", 128);
const gameId = requiredEnv("EVAVO_TEST_GAME_ID", 80);
const buildHash = requiredEnv("EVAVO_TEST_BUILD_HASH", 128);
const protocolVersion = boundedInteger(process.env.EVAVO_TEST_PROTOCOL_VERSION ?? "1", 1, 1_000_000, "EVAVO_TEST_PROTOCOL_VERSION");
const identityBaseUrl = normalizedOrigin(requiredEnv("EVAVO_TEST_IDENTITY_URL", 2_048), "EVAVO_TEST_IDENTITY_URL");
const gatewayBaseUrl = normalizedOrigin(requiredEnv("EVAVO_TEST_GATEWAY_URL", 2_048), "EVAVO_TEST_GATEWAY_URL");
const privateKeyPath = resolve(requiredEnv("EVAVO_TEST_PRIVATE_KEY_PATH", 32_768));
const credentialPath = resolve(requiredEnv("EVAVO_TEST_CREDENTIAL_PATH", 32_768));
const timeoutMs = boundedInteger(process.env.EVAVO_TEST_HTTP_TIMEOUT_MS ?? "5000", 100, 60_000, "EVAVO_TEST_HTTP_TIMEOUT_MS");
const maximumResponseBytes = boundedInteger(process.env.EVAVO_TEST_MAX_RESPONSE_BYTES ?? String(4 * 1024 * 1024), 1024, 16 * 1024 * 1024, "EVAVO_TEST_MAX_RESPONSE_BYTES");

const keys = await loadOrCreateKeys(privateKeyPath);
let credentials = await loadCredentials(credentialPath);
let previousRefreshToken;
let commandTail = Promise.resolve();

emit({
  event: "ready",
  playerId,
  displayName,
  deviceId,
  gameId,
  buildHash,
  protocolVersion,
  publicKeyPem: keys.publicKeyPem,
  credentialsLoaded: credentials !== undefined,
});

const input = createInterface({ input: process.stdin, terminal: false, crlfDelay: Infinity });
for await (const line of input) {
  if (!line.trim()) continue;
  commandTail = commandTail.then(() => handleLine(line)).catch((error) => {
    emit({ event: "fatal", error: safeError(error) });
  });
}
await commandTail;

async function handleLine(line) {
  let command;
  try { command = JSON.parse(line); }
  catch {
    emit({ id: null, ok: false, error: "invalid_command_json" });
    return;
  }
  const id = typeof command.id === "string" || typeof command.id === "number" ? command.id : null;
  try {
    if (command.command === "login") {
      const result = await login();
      emit({ id, ok: true, result });
      return;
    }
    if (command.command === "refresh") {
      const result = await refresh();
      emit({ id, ok: true, result });
      return;
    }
    if (command.command === "replay_previous_refresh") {
      const result = await replayPreviousRefresh();
      emit({ id, ok: true, result });
      return;
    }
    if (command.command === "gateway") {
      const method = normalizedMethod(command.method);
      const path = normalizedRelativePath(command.path);
      const result = await gatewayRequest(method, path, command.body);
      emit({ id, ok: true, result });
      return;
    }
    if (command.command === "me") {
      const result = await identityRequest("GET", "/v1/me", undefined, requireCredentials().sessionToken);
      emit({ id, ok: true, result: publicHttpResult(result) });
      return;
    }
    if (command.command === "credential_summary") {
      emit({ id, ok: true, result: credentialSummary() });
      return;
    }
    if (command.command === "clear") {
      credentials = undefined;
      previousRefreshToken = undefined;
      await rm(credentialPath, { force: true });
      emit({ id, ok: true, result: { cleared: true } });
      return;
    }
    if (command.command === "exit") {
      emit({ id, ok: true, result: { exiting: true } });
      input.close();
      setTimeout(() => process.exit(0), 10).unref();
      return;
    }
    throw new Error("unknown_command");
  } catch (error) {
    emit({ id, ok: false, error: safeError(error) });
  }
}

async function login() {
  const challengeResponse = await identityRequest("POST", "/v1/device-login/challenges", {
    playerId,
    deviceId,
    gameId,
    buildHash,
    protocolVersion,
  });
  if (challengeResponse.status !== 201) throw new Error(`challenge_failed:${challengeResponse.status}`);
  const challenge = requireObject(challengeResponse.payload, "challenge");
  if (challenge.playerId !== playerId || challenge.deviceId !== deviceId || challenge.gameId !== gameId) {
    throw new Error("challenge_identity_mismatch");
  }
  const payload = challengePayload(challenge);
  const signature = sign(null, Buffer.from(payload, "utf8"), keys.privateKeyPem).toString("base64url");
  const completion = await identityRequest(
    "POST",
    `/v1/device-login/challenges/${encodeURIComponent(requiredString(challenge, "challengeId"))}/complete`,
    { signature },
  );
  if (completion.status !== 200) throw new Error(`login_failed:${completion.status}`);
  const parsed = parseCredentials(completion.payload);
  previousRefreshToken = undefined;
  await saveCredentials(credentialPath, parsed);
  credentials = parsed;
  return {
    authenticated: true,
    playerId: parsed.sessionClaims.playerId,
    gameId: parsed.sessionClaims.gameId,
    sessionId: parsed.sessionClaims.sessionId,
    refreshFamilyId: parsed.refreshFamilyId,
    sessionExpiresAt: parsed.sessionClaims.expiresAt,
    refreshExpiresAt: parsed.refreshExpiresAt,
  };
}

async function refresh() {
  const current = requireCredentials();
  const response = await identityRequest("POST", "/v1/device-login/refresh", {
    refreshToken: current.refreshToken,
  });
  if (response.status !== 200) {
    if (response.status === 401) await clearCredentials();
    throw new Error(`refresh_failed:${response.status}`);
  }
  const parsed = parseCredentials(response.payload);
  if (parsed.refreshFamilyId !== current.refreshFamilyId) {
    await clearCredentials();
    throw new Error("refresh_family_mismatch");
  }
  previousRefreshToken = current.refreshToken;
  await saveCredentials(credentialPath, parsed);
  credentials = parsed;
  return {
    refreshed: true,
    playerId: parsed.sessionClaims.playerId,
    sessionId: parsed.sessionClaims.sessionId,
    refreshFamilyId: parsed.refreshFamilyId,
    tokenChanged: parsed.refreshToken !== current.refreshToken,
  };
}

async function replayPreviousRefresh() {
  if (previousRefreshToken === undefined) throw new Error("previous_refresh_token_unavailable");
  const response = await identityRequest("POST", "/v1/device-login/refresh", {
    refreshToken: previousRefreshToken,
  });
  if (response.status === 401) await clearCredentials();
  return {
    status: response.status,
    rejected: response.status === 401,
    credentialsCleared: credentials === undefined,
  };
}

async function gatewayRequest(method, path, body) {
  const current = requireCredentials();
  const result = await request(gatewayBaseUrl, method, path, body, current.sessionToken);
  return publicHttpResult(result);
}

async function identityRequest(method, path, body, token) {
  return request(identityBaseUrl, method, path, body, token);
}

async function request(baseUrl, method, path, body, token) {
  const headers = { accept: "application/json" };
  if (body !== undefined) headers["content-type"] = "application/json";
  if (token !== undefined) headers.authorization = `Bearer ${token}`;
  const response = await fetch(`${baseUrl}${normalizedRelativePath(path)}`, {
    method,
    headers,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    redirect: "manual",
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (response.status >= 300 && response.status < 400) throw new Error(`redirect_rejected:${response.status}`);
  const bytes = await readBounded(response, maximumResponseBytes);
  let payload;
  try { payload = bytes.byteLength === 0 ? undefined : JSON.parse(new TextDecoder().decode(bytes)); }
  catch { throw new Error("invalid_json_response"); }
  return { status: response.status, payload };
}

function publicHttpResult(result) {
  return {
    status: result.status,
    payload: redactPayload(result.payload),
  };
}

function credentialSummary() {
  if (credentials === undefined) return { authenticated: false };
  return {
    authenticated: true,
    playerId: credentials.sessionClaims.playerId,
    gameId: credentials.sessionClaims.gameId,
    sessionId: credentials.sessionClaims.sessionId,
    refreshFamilyId: credentials.refreshFamilyId,
    sessionExpiresAt: credentials.sessionClaims.expiresAt,
    refreshExpiresAt: credentials.refreshExpiresAt,
  };
}

async function clearCredentials() {
  credentials = undefined;
  previousRefreshToken = undefined;
  await rm(credentialPath, { force: true });
}

function requireCredentials() {
  if (credentials === undefined) throw new Error("credentials_missing");
  return credentials;
}

async function loadOrCreateKeys(path) {
  try {
    const privateKeyPem = await readFile(path, "utf8");
    const publicKeyPath = `${path}.pub`;
    const publicKeyPem = await readFile(publicKeyPath, "utf8");
    return { privateKeyPem, publicKeyPem };
  } catch (error) {
    if (!isNodeError(error) || error.code !== "ENOENT") throw error;
  }
  const generated = generateKeyPairSync("ed25519");
  const privateKeyPem = generated.privateKey.export({ type: "pkcs8", format: "pem" }).toString();
  const publicKeyPem = generated.publicKey.export({ type: "spki", format: "pem" }).toString();
  await writeSecret(path, privateKeyPem);
  await writeSecret(`${path}.pub`, publicKeyPem);
  return { privateKeyPem, publicKeyPem };
}

async function loadCredentials(path) {
  try {
    return parseCredentials(JSON.parse(await readFile(path, "utf8")));
  } catch (error) {
    if (isNodeError(error) && error.code === "ENOENT") return undefined;
    throw error;
  }
}

async function saveCredentials(path, value) {
  await mkdir(dirname(path), { recursive: true });
  const temporary = `${path}.${process.pid}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(value)}\n`, { encoding: "utf8", mode: 0o600, flag: "wx" });
    await rename(temporary, path);
    await chmod(path, 0o600).catch(() => undefined);
  } catch (error) {
    await rm(temporary, { force: true }).catch(() => undefined);
    throw error;
  }
}

async function writeSecret(path, value) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, value, { encoding: "utf8", mode: 0o600, flag: "wx" });
  await chmod(path, 0o600).catch(() => undefined);
}

function parseCredentials(value) {
  const input = requireObject(value, "credentials");
  const claims = requireObject(input.sessionClaims, "sessionClaims");
  const parsed = {
    sessionToken: requiredString(input, "sessionToken"),
    refreshToken: strictBase64Url(requiredString(input, "refreshToken"), 32, "refreshToken"),
    refreshFamilyId: requiredString(input, "refreshFamilyId"),
    refreshExpiresAt: requiredInteger(input, "refreshExpiresAt"),
    sessionClaims: {
      playerId: requiredString(claims, "playerId"),
      displayName: requiredString(claims, "displayName"),
      gameId: requiredString(claims, "gameId"),
      sessionId: requiredString(claims, "sessionId"),
      protocolVersion: requiredInteger(claims, "protocolVersion"),
      expiresAt: requiredInteger(claims, "expiresAt"),
    },
  };
  if (parsed.sessionClaims.playerId !== playerId || parsed.sessionClaims.gameId !== gameId) {
    throw new Error("credential_scope_mismatch");
  }
  return parsed;
}

function challengePayload(challenge) {
  return [
    "evavo-device-login-v1",
    requiredString(challenge, "challengeId"),
    strictBase64Url(requiredString(challenge, "nonce"), 32, "nonce"),
    requiredString(challenge, "playerId"),
    requiredString(challenge, "deviceId"),
    requiredString(challenge, "gameId"),
    String(requiredInteger(challenge, "issuedAt")),
    String(requiredInteger(challenge, "expiresAt")),
    String(requiredInteger(challenge, "protocolVersion")),
    typeof challenge.buildHash === "string" ? challenge.buildHash : "",
  ].join("\n");
}

async function readBounded(response, maximum) {
  const length = response.headers.get("content-length");
  if (length !== null && Number(length) > maximum) throw new Error("response_too_large");
  if (!response.body) return new Uint8Array();
  const reader = response.body.getReader();
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value === undefined) continue;
      total += value.byteLength;
      if (total > maximum) {
        await reader.cancel("response_too_large").catch(() => undefined);
        throw new Error("response_too_large");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const output = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    output.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return output;
}

function redactPayload(value, depth = 0) {
  if (depth > 16) return "[depth-redacted]";
  if (Array.isArray(value)) return value.slice(0, 1_000).map((item) => redactPayload(item, depth + 1));
  if (value && typeof value === "object") {
    const output = {};
    for (const [key, item] of Object.entries(value)) {
      if (/(token|signature|private.?key|secret|authorization)/iu.test(key)) output[key] = "[redacted]";
      else output[key] = redactPayload(item, depth + 1);
    }
    return output;
  }
  return value;
}

function normalizedMethod(value) {
  const method = String(value ?? "").toUpperCase();
  if (!["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"].includes(method)) throw new Error("invalid_method");
  return method;
}

function normalizedOrigin(value, name) {
  const url = new URL(value);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash || (url.pathname !== "/" && url.pathname !== "")) {
    throw new Error(`${name}_invalid`);
  }
  return url.origin;
}

function normalizedRelativePath(value) {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//") || value.length > 2_048 || value.includes("\\") || value.includes("\0")) throw new Error("invalid_relative_path");
  const url = new URL(value, "https://evavo.invalid");
  if (url.origin !== "https://evavo.invalid") throw new Error("invalid_relative_path");
  for (const segment of url.pathname.split("/")) {
    const decoded = decodeURIComponent(segment);
    if (decoded === "." || decoded === ".." || decoded.includes("/") || decoded.includes("\\")) throw new Error("invalid_relative_path");
  }
  return `${url.pathname}${url.search}`;
}

function strictBase64Url(value, exactBytes, name) {
  if (!/^[A-Za-z0-9_-]+$/u.test(value)) throw new Error(`${name}_invalid`);
  const bytes = Buffer.from(value, "base64url");
  if (bytes.byteLength !== exactBytes || bytes.toString("base64url") !== value) throw new Error(`${name}_invalid`);
  return value;
}

function requiredEnv(name, maximum) {
  const value = process.env[name]?.trim();
  if (!value || value.length > maximum) throw new Error(`${name}_required`);
  return value;
}

function boundedInteger(value, minimum, maximum, name) {
  const number = Number(value);
  if (!Number.isSafeInteger(number) || number < minimum || number > maximum) throw new Error(`${name}_invalid`);
  return number;
}

function requireObject(value, name) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`${name}_object_required`);
  return value;
}

function requiredString(value, key) {
  const field = value[key];
  if (typeof field !== "string" || !field) throw new Error(`${key}_required`);
  return field;
}

function requiredInteger(value, key) {
  const field = value[key];
  if (typeof field !== "number" || !Number.isSafeInteger(field)) throw new Error(`${key}_integer_required`);
  return field;
}

function emit(value) {
  process.stdout.write(`${JSON.stringify(value)}\n`);
}

function safeError(error) {
  const message = error instanceof Error ? error.message : String(error);
  return message.replace(/[A-Za-z0-9_-]{32,}/gu, "[redacted]").slice(0, 512);
}

function isNodeError(error) {
  return error instanceof Error && "code" in error;
}
