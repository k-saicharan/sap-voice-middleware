# SAP Voice Middleware Prototype

An offline-first, high-fidelity simulation of **RealWear Navigator 520 + TeamViewer Frontline xPick + SAP EWM** voice-picking. This repository validates a custom middleware that sits **between WearHF and SAP EWM**, intercepting, fuzzy-matching, and normalizing headset voice commands before they reach the warehouse system.

<details>
<summary>🧠 <b>What is this project and why does it exist?</b></summary>

- **What this is:** A complete, standalone replica of a hardware-to-backend voice-picking workflow — from microphone capture to SAP confirmation.
- **Why it exists:** To have a safe sandbox for testing voice normalization without needing physical hardware or live SAP staging servers.
- **What problem it solves:** It lets you test how the middleware handles messy transcripts once the audio has been turned into text — for example, mapping "pick ate" or "Trick 8" back to the intended `PICK 8`.
- **What real system it simulates:** The interaction between a RealWear Navigator 520 headset running WearHF, TeamViewer Frontline (xPick) as the picking UI, and SAP EWM (Extended Warehouse Management) as the backend.
</details>

---

## Problem Being Solved

In a warehouse, the RealWear headset uses a grammar-constrained engine called WearHF. If the worker says "PICK 8" but the onboard STT outputs "Trick 8", the `SPEECH_EVENT` intent either never fires or fires with the wrong command string. The worker is stuck, repeating themselves on a noisy floor.

This prototype validates a middleware layer that catches these incorrect transcripts and tries to correct them using fuzzy matching — for example, mapping "Trick 8" back to the intended "PICK 8" — before forwarding the result to SAP EWM.

<details>
<summary>🧠 <b>Understanding the floor pain point</b></summary>

- **What this is:** The core justification for the middleware's existence.
- **Why it matters:** Without this correction layer, every misheard word blocks the entire picking workflow. The worker has to repeat themselves, remove the headset, or call a supervisor — all of which cost time and money.
- **What real system it connects to:** On the real device, WearHF fires a `SPEECH_EVENT` Android broadcast. If WearHF rejects the audio entirely, nothing reaches SAP at all. This middleware intercepts the text output from STT and corrects it before it is lost. It does not hear audio that WearHF discarded — it only works with text that has already come out of the STT engine.
</details>

---

## Architecture / Flow

The prototype is split into three decoupled layers:

1. **Edge Client (`mock_wearhf.py`):** Captures local audio, transcribes it via offline Whisper STT, and emits simulated RealWear `SPEECH_EVENT` intents (with `COMMAND` and `CONFIDENCE` fields).
2. **Middleware API (`app/`):** Uses the existing EnrollmentService, RecognitionService, and CommandService to fuzzy-match and normalize the command, including optional speaker verification (voice fingerprint).
3. **Backend Mock (`mock_its_mobile.py`):** An ITS Mobile-style state machine simulating SAP EWM scanning and picking loops.

A fourth component, `telemetry_server.py`, acts as a WebSocket relay that feeds live event data to the browser-based dashboard.

<details>
<summary>🧠 <b>Component deep dive</b></summary>

- **What this is:** The structural blueprint showing how the three layers communicate.
- **Why they are separate processes:** It isolates the middleware (the actual product) from the mocks (the testing environment). Only the `app/` directory would be deployed in a real scenario. The `mock_` files are strictly local simulation tools.
- **What real system each part simulates:**
  - `mock_wearhf.py` simulates **RealWear Navigator 520 / WearHF**. Note: in the real system, if WearHF never fires `SPEECH_EVENT`, nothing downstream sees the command. This mock always sends text to the middleware, which is intentional for testing purposes — it lets us exercise the normalization logic even on inputs a real device might have silently dropped.
  - `app/` is the **custom middleware** — the EnrollmentService, RecognitionService, and CommandService that perform fuzzy matching and speaker verification. This code was not rewritten for the simulation; it is the core product.
  - `mock_its_mobile.py` simulates the rigid browser states of **SAP EWM / ITS Mobile** — the DISPLAY → SCAN → VOICE → ADVANCE state machine that a real SAP system enforces.
- **What would a developer change for production:** Replace the mock edge scripts with an actual Android background service that intercepts real `SPEECH_EVENT` broadcasts and injects normalized results back into the TeamViewer Frontline app. The `app/` middleware API remains identical.
</details>

---

## How to Run

### Prerequisites

- Python 3.10+
- macOS or Linux (Windows untested)
- A working microphone (for the voice client)

### Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Launch

Start each component in a separate terminal tab:

```bash
# Tab 1 — Telemetry relay
python telemetry_server.py

# Tab 2 — SAP EWM mock
python mock_its_mobile.py

# Tab 3 — Middleware API
uvicorn app.main:app --port 8000 --reload

# Tab 4 — Headset simulation (requires microphone)
python mock_wearhf.py
```

Once all four processes are running, open `demo/index.html` in your browser to see the live viewfinder and telemetry dashboard.

<details>
<summary>🧠 <b>Why so many services?</b></summary>

- **What this is:** The startup sequence for the local simulation grid.
- **Why they run as separate processes:** Each server occupies its own port, which mimics the real-world reality where the headset, the application server, and the SAP database are completely different machines on a warehouse network. This also means you can test what happens when one component goes down independently.
- **What real system it connects to:** Terminal 1 is the observability layer. Terminal 2 is the SAP backend. Terminal 3 is the middleware (the product). Terminal 4 is the physical headset on the warehouse floor.
</details>

---

## Demo Explanation

The `demo/index.html` file is a browser UI that imitates the Navigator 520 viewfinder. It is not something that runs on the headset — it is a desktop visualization tool.

Speak voice commands ("CAMERA", "PICK 12") naturally into the `mock_wearhf.py` microphone loop. The left side of the dashboard shows the worker's view: bin location, material, and expected quantity. The right side shows a chronological log of every voice event as it flows through the middleware pipeline.

The dashboard plays a success or failure chime in real time and visually flashes green or red based on whether the middleware successfully normalized the command.

<details>
<summary>🧠 <b>Visualizing the data</b></summary>

- **What this is:** A visual representation of the invisible data flowing through the APIs.
- **Why it is included:** So developers debugging the system (and non-technical stakeholders watching a demo) can see the exact moment a misrecognized word gets corrected by the middleware.
- **What it shows:** The `Raw STT → Normalization → SAP Backend` pipeline, laid out chronologically on screen. You can watch "Trick 8" arrive from the mic, get corrected to "PICK 8" by the middleware, and trigger a green success flash — all within a few hundred milliseconds.
- **What real system it imitates:** The left panel replicates what the worker sees in their TeamViewer xPick HUD on the Navigator 520. The chimes replicate the audio feedback the worker hears on the headset upon success or failure.
</details>

---

## Repo Structure

```text
sap-voice-middleware/
├── app/                  # Core Middleware API (the product)
│   ├── routes/           # HTTP endpoints for recognition and enrollment
│   ├── services/         # CommandService, RecognitionService, EnrollmentService
│   ├── models/           # Database models (WorkerProfile)
│   └── core/             # Config, database setup
├── demo/                 # Browser-based telemetry dashboard
├── mock_its_mobile.py    # SAP EWM / ITS Mobile state machine simulation
├── mock_wearhf.py        # RealWear / WearHF headset simulation
├── telemetry_server.py   # WebSocket relay for live telemetry
├── seed_worker.py        # Creates a default worker profile for testing
├── requirements.txt      # Python dependencies
└── voice_profiles.db     # SQLite database for speaker biometrics
```

<details>
<summary>🧠 <b>Code organization</b></summary>

- **What this is:** The map of files in the project.
- **Why it matters:** It clearly separates what is "production code" from "testing simulation code". Only the `app/` directory would be deployed to cloud infrastructure. Everything prefixed with `mock_` is a local-only tool.
- **What real system it connects to:** This structure follows standard enterprise microservice conventions — the business logic (`app/`) stays agnostic to whatever hardware is transmitting the data. Swap the edge client from a Python mock to a real Android service, and the `app/` directory does not change.
</details>

---

## What this is NOT

This is not a fork or modification of SAP EWM, TeamViewer Frontline, or WearHF. It is a standalone microservice that sits alongside the existing stack without touching any licensed component. It requires no SAP configuration change and no TeamViewer licence modification. It can be deployed as a standalone microservice next to an existing Frontline Connector without changing SAP EWM or xPick configuration.
