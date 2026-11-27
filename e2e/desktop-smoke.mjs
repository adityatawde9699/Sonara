// End-to-end smoke test of the real desktop app through WebDriver.
//
// Starts `tauri-driver` (which drives WebKitWebDriver on Linux), launches a
// debug build of Sonara against an isolated data directory, and checks the
// whole path that unit tests cannot: a document reopened from the backend
// library, real Piper synthesis by the Python worker, the session reaching
// the player, passage audio loading from the loopback audio server, and the
// reading view highlighting the passage being spoken.
//
// The native file picker cannot be automated, so the test seeds the library
// with a document instead; reopening by hash goes through the same backend
// validation the picker uses.
//
// Usage (Linux, after `npm run build` in ui-react and `cargo build` in
// src-tauri; needs tauri-driver, WebKitWebDriver, a Piper voice and Xvfb or
// a display):
//   xvfb-run -a node e2e/desktop-smoke.mjs [path/to/sonara-desktop]
// No npm dependencies: it speaks the W3C WebDriver protocol with fetch.

import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, mkdirSync, readdirSync, rmSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const ROOT = resolve(import.meta.dirname, "..");
const APPLICATION = resolve(process.argv[2] ?? join(ROOT, "src-tauri/target/debug/sonara-desktop"));
const DRIVER_PORT = 4444;
const DRIVER = `http://127.0.0.1:${DRIVER_PORT}`;
const IDENTIFIER = JSON.parse(readFileSync(join(ROOT, "src-tauri/tauri.conf.json"), "utf8")).identifier;
const STEP_TIMEOUT_MS = 30_000;
const SYNTHESIS_TIMEOUT_MS = 240_000;

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

async function webdriver(method, path, body) {
  const response = await fetch(`${DRIVER}${path}`, {
    method,
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(`${method} ${path}: ${payload.value?.message ?? response.status}`);
  }
  return payload.value;
}

async function waitFor(description, check, timeoutMs = STEP_TIMEOUT_MS) {
  const deadline = Date.now() + timeoutMs;
  let last;
  while (Date.now() < deadline) {
    try {
      last = await check();
      if (last) return last;
    } catch (error) {
      last = error;
    }
    await sleep(250);
  }
  throw new Error(`Timed out waiting for ${description} (last: ${last instanceof Error ? last.message : JSON.stringify(last)})`);
}

/** Seed Sonara 1.x data: a version 1 library and a 1.x audio cache. */
function seedLibrary(dataHome) {
  const documents = join(dataHome, "documents");
  mkdirSync(documents, { recursive: true });
  const documentPath = join(documents, "smoke-notes.txt");
  const text = "Sonara end-to-end check.\n\nThe library reopened this file, and Piper read it aloud on this device.\n";
  writeFileSync(documentPath, text);
  const appData = join(dataHome, IDENTIFIER);
  mkdirSync(appData, { recursive: true });
  writeFileSync(join(appData, "library.json"), JSON.stringify({
    version: 1,
    entries: [{
      sourceSha256: createHash("sha256").update(text).digest("hex"),
      sourceName: "smoke-notes.txt",
      sourcePath: documentPath,
      voice: "en_US-ryan-medium",
      engine: "Piper",
      chunksCount: 2,
      totalDurationSeconds: 6,
      lastListenedAt: Date.now(),
    }],
  }));
  // A 1.x cache, which the version 2 migration moves to audio-cache/.
  const legacyCache = join(appData, "reader-output", ".sonara-audio-cache");
  mkdirSync(legacyCache, { recursive: true });
  writeFileSync(join(legacyCache, "seeded.wav"), "cached");
  return appData;
}

/** The version 2 layout the app should leave behind after one finished run. */
function checkDataLayout(appData) {
  const expect = (condition, message) => {
    if (!condition) throw new Error(`data layout: ${message}`);
  };
  expect(readFileSync(join(appData, "data-version"), "utf8").trim() === "2", "data-version is not 2");
  expect(JSON.parse(readFileSync(join(appData, "library.json"), "utf8")).version === 2, "library.json is not version 2");
  expect(existsSync(join(appData, "library.json.v1.bak")), "the version 1 library was not backed up");
  expect(!existsSync(join(appData, "reader-output")), "reader-output/ was not removed");
  expect(existsSync(join(appData, "audio-cache", "seeded.wav")), "the 1.x cache was not moved");
  const runs = readdirSync(join(appData, "sessions"));
  expect(runs.length === 1, `expected one session run, found ${runs.length}`);
  const run = join(appData, "sessions", runs[0]);
  expect(readFileSync(join(appData, "current-session"), "utf8").trim() === runs[0], "current-session does not name the run");
  expect(JSON.parse(readFileSync(join(run, "session.json"), "utf8")).version === 2, "session.json is not version 2");
  expect(!existsSync(join(run, "speech.wav")), "the desktop run wrote a combined speech.wav");
}

async function main() {
  const dataHome = mkdtempSync(join(tmpdir(), "sonara-e2e-"));
  const appData = seedLibrary(dataHome);
  // The app inherits this environment through tauri-driver and
  // WebKitWebDriver, so its app-local data lands in the temporary directory.
  const driver = spawn("tauri-driver", ["--port", String(DRIVER_PORT)], {
    env: { ...process.env, XDG_DATA_HOME: dataHome },
    stdio: ["ignore", "inherit", "inherit"],
  });
  let session;
  const step = (name) => console.log(`• ${name}`);
  try {
    await waitFor("tauri-driver", async () => (await fetch(`${DRIVER}/status`)).ok);
    step("launching Sonara");
    session = (await webdriver("POST", "/session", {
      capabilities: { alwaysMatch: { "tauri:options": { application: APPLICATION } } },
    })).sessionId;
    const run = (script, args = []) => webdriver("POST", `/session/${session}/execute/sync`, { script, args });
    const click = async (selector) => {
      const element = await waitFor(`element ${selector}`, () =>
        webdriver("POST", `/session/${session}/element`, { using: "css selector", value: selector }));
      await webdriver("POST", `/session/${session}/element/${Object.values(element)[0]}/click`, {});
    };
    const bodyText = () => run("return document.body.innerText");

    step("opening the library seeded by the backend");
    await waitFor("the main window", async () => (await bodyText()).includes("Listen to your documents"));
    await click("button[title='Library']");
    await waitFor("the library row", async () => (await bodyText()).includes("smoke-notes.txt"));

    step("reopening the document by hash");
    await click("button[aria-label='Listen again: smoke-notes.txt']");
    await waitFor("the document to be selected", async () =>
      (await bodyText()).includes("Selected from your library"));

    step("preparing speech with the local Python worker and Piper");
    await click("#start-synthesis");
    const ready = await waitFor("synthesis to finish", async () => {
      const text = await bodyText();
      if (/Speech generation failed|could not|is not installed/i.test(text) && !text.includes("Synthesizing")) {
        throw new Error(text.slice(0, 400));
      }
      return text.match(/Ready to listen · (\d+) passages/);
    }, SYNTHESIS_TIMEOUT_MS);
    console.log(`  ${ready[0]}`);

    step("loading the first passage from the loopback audio server");
    let mediaState = null;
    const audio = await waitFor("audio metadata", async () => {
      // On a timeout the error shows the last state, so a failure says
      // whether the element was missing, stuck loading, or reported an error.
      mediaState = await run(`
        const audio = document.querySelector("audio");
        const status = document.querySelector(".player-status, [role='status']");
        return {
          present: Boolean(audio),
          readyState: audio?.readyState ?? null,
          networkState: audio?.networkState ?? null,
          error: audio?.error ? audio.error.code : null,
          duration: Number.isFinite(audio?.duration) ? audio.duration : null,
          src: audio?.currentSrc ?? "",
          status: status?.textContent?.trim() ?? "",
        };
      `);
      return mediaState.readyState >= 1 && mediaState.duration > 0 ? mediaState : null;
    }).catch((error) => {
      throw new Error(`${error.message}; media state ${JSON.stringify(mediaState)}`);
    });
    if (!/^http:\/\/127\.0\.0\.1:\d+\/v1\/[0-9a-f]{64}\/[0-9a-f]{64}\/0$/.test(audio.src)) {
      throw new Error(`unexpected audio source ${audio.src}`);
    }
    console.log(`  passage 1: ${audio.duration.toFixed(2)} s`);

    step("highlighting the spoken passage in the reading view");
    await click("button[title='Reading view']");
    const spoken = await waitFor("the highlighted passage", async () =>
      run(`const mark = document.querySelector("mark.reader-spoken"); return mark && mark.textContent;`));
    if (!spoken.startsWith("Sonara end-to-end check")) {
      throw new Error(`the first passage should be highlighted, got ${JSON.stringify(spoken)}`);
    }
    console.log(`  highlighted: "${spoken.trim()}"`);
    await click("button[aria-label='Listen from paragraph 2']");
    await waitFor("the second passage to be highlighted", async () =>
      (await run(`return document.querySelector("mark.reader-spoken")?.textContent ?? ""`)).startsWith("The library reopened"));
    await click("button[title='Home']");

    step("checking the library recorded the finished document");
    await click("button[title='Library']");
    await waitFor("the reader action", async () => (await bodyText()).includes("Open reader"));

    step("checking the version 2 data layout on disk");
    checkDataLayout(appData);
    console.log("Desktop smoke test passed.");
  } finally {
    if (session) await webdriver("DELETE", `/session/${session}`).catch(() => {});
    driver.kill();
    rmSync(dataHome, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(`Desktop smoke test failed: ${error.message}`);
  process.exit(1);
});
