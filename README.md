# SAP Voice Profile Middleware

Per-worker `speech_word_mapping` service for the **RealWear + TeamViewer Frontline xPick + SAP EWM** warehouse picking stack.

---

## Problem

Warehouse pickers have different accents and dialects (Portuguese, Hindi, Polish, etc.). RealWear's WearHF voice engine is grammar-constrained and speaker-independent by design — it cannot be acoustically adapted per user. In noisy environments (cold stores, beverage warehouses), this causes misrecognitions that halt workflows and force manual corrections.

SAP EWM cannot help: it only emits grammar strings and receives validated text back. It never sees audio. The fix lives entirely in the middleware layer.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         RealWear Device                              │
│  WearHF (on-device ASR) → grammar match → SPEECH_EVENT broadcast    │
│  Frontline Workplace APK → xPick workflow (speech_word_mapping)      │
└─────────────────────────────┬────────────────────────────────────────┘
                              │ REST (Vision Pick Interface)
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Frontline Connector                               │
│          (Java / Spring Boot — customer-deployed)                   │
│                                                                     │
│  AT QR LOGIN:                                                       │
│  GET http://this-service/workers/{worker_id}/profile                │
│       ↓ injects speech_word_mapping into active xPick workflow      │
└────────────┬──────────────────────────┬────────────────────────────┘
             │                          │
             ▼                          ▼
  ┌──────────────────┐       ┌─────────────────────────────┐
  │   SAP EWM        │       │  SAP Voice Profile          │
  │ (system of       │       │  Middleware (this service)  │
  │  record —        │       │                             │
  │  NEVER touched)  │       │  SQLite · FastAPI · Python  │
  └──────────────────┘       └─────────────────────────────┘
                                         ▲
                                         │ admin CRUD
                                    Warehouse Manager
```

**What the mapping does:**
A Portuguese picker says *"DEZ"* (ten). WearHF hears `DEZ`. The injected mapping converts it to `10` before it reaches SAP EWM. EWM always receives the canonical command string — untouched.

---

## How It Works — Step by Step

1. Worker scans QR code on the RealWear device
2. Keycloak (FCC) authenticates and returns `worker_id`
3. Frontline Connector calls `GET /workers/{worker_id}/profile` on this service
4. Service returns the worker's `speech_word_mapping` list
5. Connector injects it into the active xPick workflow as a `speech_word_mapping` action
6. Worker speaks — WearHF matches the command in grammar, fires `SPEECH_EVENT`
7. xPick workflow applies the mapping (`DEZ` → `10`)
8. Validated string `10` is sent to SAP EWM — no EWM change, ever

---

## API Reference

### Health check
```
GET /health
```
```json
{"status": "ok", "service": "sap-voice-middleware"}
```

### Fetch worker profile (called at QR login)
```
GET /workers/{worker_id}/profile
```
```bash
curl http://localhost:8000/workers/PIC_PT_001/profile
```
```json
{
  "worker_id": "PIC_PT_001",
  "locale": "pt-PT",
  "speech_word_mapping": [
    {"spoken": "DEZ",    "mapped": "10"},
    {"spoken": "QUINZE", "mapped": "15"},
    {"spoken": "UM",     "mapped": "1"}
  ],
  "updated_at": "2026-04-13T10:00:00"
}
```

### Create / update profile
```
POST /workers/{worker_id}/profile
```
```bash
curl -X POST http://localhost:8000/workers/PIC_PT_001/profile \
  -H "Content-Type: application/json" \
  -d '{
    "locale": "pt-PT",
    "mappings": {"DEZ": "10", "QUINZE": "15", "UM": "1", "DOIS": "2"}
  }'
```

### Delete profile
```
DELETE /workers/{worker_id}/profile
```
```bash
curl -X DELETE http://localhost:8000/workers/PIC_PT_001/profile
```

### List all profiles
```
GET /workers/
```
```bash
curl http://localhost:8000/workers/
```

### Seed demo data (3 workers: pt-PT, hi-IN, pl-PL)
```
POST /seed/demo
```
```bash
curl -X POST http://localhost:8000/seed/demo
```

---

## Quick Start

```bash
git clone https://github.com/k-saicharan/sap-voice-middleware
cd sap-voice-middleware

pip install -r requirements.txt

uvicorn app.main:app --reload --port 8000
```

Seed demo workers and test:
```bash
curl -X POST http://localhost:8000/seed/demo
curl http://localhost:8000/workers/PIC_PT_001/profile
```

Interactive API docs: http://localhost:8000/docs

---

## Docker

```bash
docker build -t sap-voice-middleware .
docker run -p 8000:8000 sap-voice-middleware
```

---

## Frontline Connector Integration (Java)

Add this call inside your login success handler, after Keycloak authentication, before the xPick workflow starts:

```java
// In your Frontline Connector login handler
String workerId = keycloakSession.getAttribute("worker_id");

ResponseEntity<Map> profileResponse = restTemplate.getForEntity(
    "http://sap-voice-middleware:8000/workers/{workerId}/profile",
    Map.class,
    workerId
);

if (profileResponse.getStatusCode().is2xxSuccessful()) {
    List<Map<String, String>> mappings =
        (List<Map<String, String>>) profileResponse.getBody()
            .get("speech_word_mapping");

    // Inject into xPick workflow session as speech_word_mapping action
    xPickWorkflow.setSpeechWordMappings(workerId, mappings);
}
```

---

## GDPR Note

This service stores **text strings only** — dialect word variants and their canonical equivalents. It does not store voiceprints, acoustic models, or any biometric data. Under UK/EU GDPR, text-based dialect maps do not constitute biometric data (Article 4) and do not trigger Article 9 special category obligations. No DPIA is required for Path A. This is the architectural reason Path A was chosen as the reference implementation.

---

## Roadmap

| Path | Description | Effort | Status |
|------|-------------|--------|--------|
| A (this repo) | `speech_word_mapping` per-worker dialect profiles | Low | Reference impl |
| B | Parallel cloud ASR (Nuance Mix) with speaker profiles | Medium-high | Planned |
| C | On-device TensorFlow Lite speaker-adapted model | High | Research |
