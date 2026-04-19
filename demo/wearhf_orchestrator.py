"""
Mock WearHF Layer — orchestration script.

Flow per iteration:
  1) GET  {ITS_URL}/instruction                       -> picking task prompt
  2) Capture mic @ 16kHz/16-bit/mono with sounddevice
  3) Silero VAD: detect speech onset + offset, no fixed windows
  4) Flush bounded audio to a temp .wav
  5) Run whisper.cpp locally with base.en + warehouse initial_prompt
  6) Wrap into the exact WearHF Android intent JSON schema
  7) Broadcast raw_intent telemetry (asyncio.create_task — non-blocking)
  8) POST the intent JSON to middleware /workers/{worker_id}/recognize
  9) Broadcast corrected_command telemetry
 10) POST corrected command to {ITS_URL}/command for validation

Pre-flight: upsert a worker profile via middleware EnrollmentService route
(POST /workers/{worker_id}/profile) so the worker row exists before any
/recognize call (satisfies the 404 guard and acts as the "session" handshake
for this biometric-free demo).

Run:
  python demo/wearhf_orchestrator.py --whisper-bin /path/to/whisper-cli \\
                                     --whisper-model /path/to/ggml-base.en.bin
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import queue
import subprocess
import sys
import tempfile
import time
import uuid
import wave
from dataclasses import dataclass
from typing import List, Optional

import httpx
import numpy as np

try:
    import sounddevice as sd
except Exception as e:  # pragma: no cover
    sd = None
    _SD_IMPORT_ERROR = e
else:
    _SD_IMPORT_ERROR = None

try:
    import torch
except Exception:  # pragma: no cover
    torch = None


# --- Configuration ------------------------------------------------------------

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2  # 16-bit
CHANNELS = 1
FRAME_MS = 32  # Silero VAD window size in ms at 16 kHz -> 512 samples
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000)  # 512

VAD_THRESHOLD = 0.5
SILENCE_HANG_MS = 700        # silence duration before closing an utterance
MAX_UTTERANCE_SEC = 12
MIN_UTTERANCE_MS = 250

WAREHOUSE_PROMPT = (
    "Pick, confirm, skip, cancel, bin, units, pallets, quantity, location, rack"
)

WEARHF_INTENT_ACTION = "com.realwear.wearhf.intent.action.DICTATION_RESULT"


@dataclass
class Config:
    middleware_url: str
    its_url: str
    worker_id: str
    whisper_bin: str
    whisper_model: str
    loop_forever: bool
    once_text: Optional[str]


# --- Silero VAD loader --------------------------------------------------------

def load_silero_vad():
    if torch is None:
        raise RuntimeError(
            "torch is required for Silero VAD. Install with: pip install torch"
        )
    model, _utils = torch.hub.load(
        repo_or_dir="snakers4/silero-vad",
        model="silero_vad",
        force_reload=False,
        trust_repo=True,
    )
    model.eval()
    return model


# --- Audio capture + VAD gating ----------------------------------------------

def record_utterance(vad_model) -> Optional[bytes]:
    """Block on the mic until one VAD-bounded utterance is captured.
    Returns raw 16-bit PCM bytes (mono, 16 kHz), or None if stopped clean."""
    if sd is None:
        raise RuntimeError(f"sounddevice import failed: {_SD_IMPORT_ERROR}")

    q: queue.Queue[np.ndarray] = queue.Queue()

    def callback(indata, frames, time_info, status):  # noqa: ARG001
        # indata shape: (frames, channels) int16
        q.put(indata.copy())

    utterance: List[np.ndarray] = []
    in_speech = False
    silence_ms = 0
    speech_ms = 0
    hang_frames_needed = SILENCE_HANG_MS // FRAME_MS

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        blocksize=FRAME_SAMPLES,
        callback=callback,
    ):
        print("[wearhf] Listening — speak your warehouse command...", flush=True)
        start = time.monotonic()
        while True:
            try:
                block = q.get(timeout=0.5)
            except queue.Empty:
                continue

            # Silero expects float32 in [-1, 1].
            pcm_f32 = (block[:, 0].astype(np.float32)) / 32768.0
            if pcm_f32.shape[0] != FRAME_SAMPLES:
                # Pad/trim to 512 samples.
                if pcm_f32.shape[0] < FRAME_SAMPLES:
                    pcm_f32 = np.pad(pcm_f32, (0, FRAME_SAMPLES - pcm_f32.shape[0]))
                else:
                    pcm_f32 = pcm_f32[:FRAME_SAMPLES]

            tensor = torch.from_numpy(pcm_f32)
            with torch.no_grad():
                prob = float(vad_model(tensor, SAMPLE_RATE).item())

            is_speech = prob >= VAD_THRESHOLD

            if is_speech:
                if not in_speech:
                    print(f"[wearhf] Speech onset (p={prob:.2f})", flush=True)
                in_speech = True
                silence_ms = 0
                speech_ms += FRAME_MS
                utterance.append(block[:, 0].copy())
            else:
                if in_speech:
                    silence_ms += FRAME_MS
                    utterance.append(block[:, 0].copy())
                    if silence_ms >= SILENCE_HANG_MS:
                        print(
                            f"[wearhf] Speech offset after {silence_ms}ms silence",
                            flush=True,
                        )
                        break
                # else: idle — drop frame.

            if speech_ms >= MAX_UTTERANCE_SEC * 1000:
                print("[wearhf] Max utterance length hit, cutting.", flush=True)
                break
            if time.monotonic() - start > 120 and not in_speech:
                # Two minutes of total silence — abort gracefully.
                print("[wearhf] No speech for 120s, aborting.", flush=True)
                return None

    if speech_ms < MIN_UTTERANCE_MS:
        print("[wearhf] Utterance too short, discarding.", flush=True)
        return None

    audio = np.concatenate(utterance) if utterance else np.zeros(0, dtype=np.int16)
    return audio.astype(np.int16).tobytes()


def write_wav(pcm_bytes: bytes, path: str) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm_bytes)


# --- Whisper.cpp runner -------------------------------------------------------

def run_whisper_cpp(whisper_bin: str, model_path: str, wav_path: str) -> str:
    """Invoke whisper.cpp CLI. Supports both the legacy `main` and new
    `whisper-cli` binaries. Returns stripped transcription text."""
    if not os.path.exists(whisper_bin):
        raise FileNotFoundError(f"whisper binary not found: {whisper_bin}")
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"whisper model not found: {model_path}")

    cmd = [
        whisper_bin,
        "-m", model_path,
        "-f", wav_path,
        "-l", "en",
        "-otxt",
        "--no-prints",
        "--prompt", WAREHOUSE_PROMPT,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"whisper.cpp failed (rc={proc.returncode}): {proc.stderr[:400]}"
        )

    txt_path = wav_path + ".txt"
    if os.path.exists(txt_path):
        with open(txt_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return (proc.stdout or "").strip()


# --- WearHF intent builder ----------------------------------------------------

def build_wearhf_intent(raw_text: str) -> dict:
    stripped = raw_text.strip()
    return {
        "action": WEARHF_INTENT_ACTION,
        "extras": {
            "com.realwear.wearhf.intent.extra.TEXT": stripped,
            "com.realwear.wearhf.intent.extra.ORIGINAL_COMMAND": raw_text,
            "com.realwear.wearhf.intent.extra.SOURCE_PACKAGE": "com.mock.sap.terminal",
            "com.realwear.wearhf.intent.extra.CONFIDENCE": 7850,
        },
    }


# --- Telemetry push (non-blocking fire-and-forget) ----------------------------

async def publish_telemetry(client: httpx.AsyncClient, its_url: str, payload: dict):
    try:
        await client.post(f"{its_url}/telemetry/publish", json=payload, timeout=5.0)
    except Exception as e:
        print(f"[wearhf] telemetry publish failed: {e}", flush=True)


# --- Pre-flight: create/ensure worker profile (the "auth" handshake) ---------

async def preflight_enrollment(client: httpx.AsyncClient, middleware_url: str, worker_id: str):
    url = f"{middleware_url}/workers/{worker_id}/profile"
    body = {
        "locale": "en-GB",
        "mappings": {},
        "gdpr_consent": True,
    }
    r = await client.post(url, json=body, timeout=10.0)
    r.raise_for_status()
    print(f"[wearhf] Pre-flight enrollment OK for worker_id={worker_id}", flush=True)


# --- Single iteration ---------------------------------------------------------

async def _flush_pending():
    # Let fire-and-forget telemetry tasks finish before returning.
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def run_once(cfg: Config, vad_model, client: httpx.AsyncClient) -> bool:
    # 1) fetch the ITS picking instruction
    instr = await client.get(f"{cfg.its_url}/instruction", timeout=10.0)
    instr.raise_for_status()
    task = instr.json()
    print(f"\n[wearhf] ITS prompt: {task['prompt']}", flush=True)
    print(f"[wearhf] Expected grammar: {task['expected_grammar']}", flush=True)

    # 2–4) capture + VAD + write wav  (or use injected text for --once)
    raw_text: str
    if cfg.once_text is not None:
        raw_text = cfg.once_text
        print(f"[wearhf] (synthetic) whisper output: {raw_text!r}", flush=True)
    else:
        pcm = record_utterance(vad_model)
        if pcm is None:
            print("[wearhf] No utterance captured; skipping.", flush=True)
            return False
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        try:
            write_wav(pcm, tmp.name)
            # 5) whisper.cpp
            raw_text = run_whisper_cpp(cfg.whisper_bin, cfg.whisper_model, tmp.name)
        finally:
            try:
                os.remove(tmp.name)
                txt = tmp.name + ".txt"
                if os.path.exists(txt):
                    os.remove(txt)
            except OSError:
                pass
        print(f"[wearhf] whisper.cpp output: {raw_text!r}", flush=True)

    # 6) WearHF intent JSON
    intent = build_wearhf_intent(raw_text)

    # 7) raw_intent telemetry — non-blocking
    asyncio.create_task(
        publish_telemetry(
            client, cfg.its_url,
            {"stage": "raw_intent", "text": raw_text, "prompt": task["prompt"]},
        )
    )

    # 8) POST intent JSON to middleware /workers/{id}/recognize
    recognize_url = f"{cfg.middleware_url}/workers/{cfg.worker_id}/recognize"
    r = await client.post(recognize_url, json=intent, timeout=15.0)
    if r.status_code != 200:
        print(f"[wearhf] middleware error {r.status_code}: {r.text}", flush=True)
        return False
    result = r.json()
    corrected = result.get("matched_command") or result.get("mapped_value") or ""
    mapped = result.get("mapped_value") or ""
    print(
        f"[wearhf] middleware -> matched={corrected} mapped={mapped} "
        f"conf={result.get('overall_confidence')}",
        flush=True,
    )

    # 9) corrected_command telemetry
    asyncio.create_task(
        publish_telemetry(
            client, cfg.its_url,
            {
                "stage": "corrected_command",
                "text": mapped or corrected,
                "matched_command": corrected,
                "mapped_value": mapped,
                "transcribed_text": result.get("transcribed_text", ""),
                "confidence": result.get("overall_confidence"),
            },
        )
    )

    # 10) POST corrected command to ITS /command
    cmd_payload = {
        "matched_command": corrected,
        "mapped_value": mapped,
        "transcribed_text": result.get("transcribed_text", ""),
    }
    r2 = await client.post(f"{cfg.its_url}/command", json=cmd_payload, timeout=10.0)
    if r2.status_code == 200:
        validated = r2.json()
        print(f"[wearhf] ITS validation: {validated}", flush=True)
    else:
        print(f"[wearhf] ITS /command error {r2.status_code}: {r2.text}", flush=True)

    await _flush_pending()
    return True


# --- Main ---------------------------------------------------------------------

async def amain(cfg: Config) -> int:
    vad_model = None
    if cfg.once_text is None:
        vad_model = load_silero_vad()

    async with httpx.AsyncClient() as client:
        await preflight_enrollment(client, cfg.middleware_url, cfg.worker_id)

        if cfg.loop_forever:
            while True:
                try:
                    await run_once(cfg, vad_model, client)
                except KeyboardInterrupt:
                    return 0
                except Exception as e:
                    print(f"[wearhf] iteration error: {e}", flush=True)
                    await asyncio.sleep(1.0)
        else:
            ok = await run_once(cfg, vad_model, client)
            return 0 if ok else 2

    return 0


def parse_args() -> Config:
    p = argparse.ArgumentParser(description="Mock WearHF orchestrator")
    p.add_argument("--middleware-url", default=os.environ.get("MIDDLEWARE_URL", "http://localhost:8000"))
    p.add_argument("--its-url", default=os.environ.get("ITS_URL", "http://localhost:8001"))
    p.add_argument("--worker-id", default=os.environ.get("WORKER_ID", f"DEMO_{uuid.uuid4().hex[:8].upper()}"))
    p.add_argument("--whisper-bin", default=os.environ.get("WHISPER_BIN", "whisper-cli"))
    p.add_argument("--whisper-model", default=os.environ.get("WHISPER_MODEL", "models/ggml-base.en.bin"))
    p.add_argument("--loop", action="store_true", help="keep listening after each utterance")
    p.add_argument("--once-text", default=None,
                   help="skip mic+whisper, use this string as the 'whisper output' (for CI/smoke)")
    a = p.parse_args()
    return Config(
        middleware_url=a.middleware_url.rstrip("/"),
        its_url=a.its_url.rstrip("/"),
        worker_id=a.worker_id,
        whisper_bin=a.whisper_bin,
        whisper_model=a.whisper_model,
        loop_forever=a.loop,
        once_text=a.once_text,
    )


if __name__ == "__main__":
    cfg = parse_args()
    try:
        sys.exit(asyncio.run(amain(cfg)))
    except KeyboardInterrupt:
        sys.exit(0)
