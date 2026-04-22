import asyncio
import json
import logging
import threading
import sys
import queue
import httpx
import numpy as np
import sounddevice as sd
import websockets
from faster_whisper import WhisperModel
import torch

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("mock_wearhf")

# Configurations
WEBSOCKET_URL = "ws://localhost:8001"
MIDDLEWARE_URL = "http://localhost:8000"
WORKER_ID = "WORKER_01"
SAMPLE_RATE = 16000

# Whisper Model
# initial_prompt using sentence-form fake transcript to provide contextual vocabulary
INITIAL_PROMPT = (
    "The worker says: Pick 5. Pick 10. Pick 8. Pick 15. Confirm. Skip. "
    "Camera. Task overview. Next. Cancel. Quantity three. Bin location AL-09 rack 12."
)
whisper_model = WhisperModel("base.en", device="cpu", compute_type="int8")

# Silero VAD Model
vad_model, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad', model='silero_vad', force_reload=False)
(get_speech_timestamps, save_audio, read_audio, VADIterator, collect_chunks) = utils

# Audio queue
audio_q = queue.Queue()
audio_buffer = []
is_recording = False
silence_frames = 0
noise_capture_mode = False # Simulated by 'n' key

def audio_callback(indata, frames, time, status):
    """This is called for each audio block."""
    if status:
        print(status, file=sys.stderr)
    
    if noise_capture_mode:
        return # Ignore audio if in noise capture mode (Action Button pressed)

    audio_q.put(indata.copy())

async def process_audio():
    global is_recording, audio_buffer, silence_frames
    
    logger.info("Starting audio processing...")
    
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='float32', blocksize=512, callback=audio_callback):
        while True:
            if not audio_q.empty():
                chunk = audio_q.get()
                audio_tensor = torch.from_numpy(chunk.flatten())
                
                # VAD Prediction
                speech_prob = vad_model(audio_tensor, SAMPLE_RATE).item()
                
                if speech_prob > 0.5:
                    if not is_recording:
                        logger.info("Speech detected. Starting recording...")
                        is_recording = True
                    audio_buffer.append(chunk)
                    silence_frames = 0
                else:
                    if is_recording:
                        audio_buffer.append(chunk)
                        silence_frames += 1
                        
                        # Stop if silence is around 1 second (16000 samples / chunk size)
                        # Let's say chunk size is approx 1024 or whatever sounddevice gives
                        # Silence threshold logic: wait for 5 consecutive chunks of silence
                        if silence_frames > 15:
                            logger.info("Silence detected. Stopping recording and running STT...")
                            audio_data = np.concatenate(audio_buffer).flatten()
                            
                            is_recording = False
                            audio_buffer = []
                            silence_frames = 0
                            
                            # Run async task to process transcription so it doesn't block audio loop
                            asyncio.create_task(run_transcription(audio_data))
            
            await asyncio.sleep(0.01)

def scale_confidence(prob: float) -> int:
    """Scale 0.0-1.0 Whisper probability to WearHF 4000-8000 integer range."""
    scaled = int(4000 + (prob * 4000))
    return max(4000, min(8000, scaled))

async def simulate_ux_feedback(signal_type: str, message: str = ""):
    """Simulate audio/visual RealWear feedback"""
    try:
        async with websockets.connect(WEBSOCKET_URL) as ws:
            payload = {
                "stage": "ux_signal",
                "type": signal_type,
                "message": message
            }
            await ws.send(json.dumps(payload))
    except Exception as e:
        logger.error(f"UX Feedback error: {e}")

async def run_transcription(audio_data):
    start_time = asyncio.get_event_loop().time()
    logger.info("Running local Whisper inference...")
    try:
        def _transcribe():
            segments, info = whisper_model.transcribe(
                audio_data, 
                beam_size=5, 
                initial_prompt=INITIAL_PROMPT,
                vad_filter=True,
                language="en"
            )
            return list(segments)
        
        segments = await asyncio.to_thread(_transcribe)
        transcribe_end = asyncio.get_event_loop().time()
        
        if not segments:
            logger.info("No speech recognized by Whisper.")
            return
            
        transcribed_text = " ".join([seg.text for seg in segments]).strip()
        avg_logprob = segments[0].avg_logprob
        probability = np.exp(avg_logprob)
        wearhf_confidence = scale_confidence(probability)
        
        processing_time_ms = int((transcribe_end - start_time) * 1000)
        
        logger.info(f"Raw Whisper: '{transcribed_text}' (Prob: {probability:.2f}, WearHF Conf: {wearhf_confidence})")
        
        # Broadcast WEARHF_SPEECH_EVENT to telemetry (Always, even if confidence is low)
        # Note: real WearHF is silent on no-match; we always broadcast for demo telemetry visibility.
        intent_payload = {
            "intent": "com.realwear.wearhf.intent.action.SPEECHEVENT",
            "com.realwear.wearhf.intent.extra.COMMAND": transcribed_text.upper(),
            "com.realwear.wearhf.intent.extra.ORIGINALCOMMAND": transcribed_text,
            "com.realwear.wearhf.intent.extra.CONFIDENCE": wearhf_confidence,
            "extra.LOGPROB": round(float(avg_logprob), 4),
            "extra.PROCESS_TIME_MS": processing_time_ms
        }
        
        try:
            async with websockets.connect(WEBSOCKET_URL) as ws:
                await ws.send(json.dumps({
                    "stage": "wearhf_speech_event",
                    "payload": intent_payload
                }))
        except Exception as e:
            logger.error(f"WebSocket send error: {e}")
            
        # Send to Middleware
        logger.info("Sending payload to middleware...")
        async with httpx.AsyncClient() as client:
            middleware_start = asyncio.get_event_loop().time()
            resp = await client.post(
                f"{MIDDLEWARE_URL}/workers/{WORKER_ID}/recognize",
                json={
                    "action": "com.realwear.wearhf.intent.action.SPEECHEVENT",
                    "extras": {
                        "com.realwear.wearhf.intent.extra.ORIGINALCOMMAND": transcribed_text,
                        "com.realwear.wearhf.intent.extra.COMMAND": transcribed_text.upper(),
                        "com.realwear.wearhf.intent.extra.CONFIDENCE": wearhf_confidence
                    }
                }
            )
            middleware_end = asyncio.get_event_loop().time()
            
            if resp.status_code == 200:
                result = resp.json()
                logger.info(f"Middleware Response: {result}")
                
                 # Fetch state from ITS Mobile to see if valid
                state_resp = await client.get("http://localhost:8002/api/state")
                its_state = state_resp.json()
                
                corrected_command = result.get("matched_command", "UNKNOWN")
                if corrected_command.startswith("QUANTITY_"):
                    corrected_command = f"PICK {corrected_command.split('_')[1]}"
                
                # Broadcast corrected command telemetry
                try:
                    async with websockets.connect(WEBSOCKET_URL) as ws:
                        await ws.send(json.dumps({
                            "stage": "corrected_command", 
                            "command": corrected_command,
                            "mapped_value": result.get("mapped_value"),
                            "text_confidence": result.get("text_confidence"),
                            "speaker_confidence": result.get("speaker_confidence"),
                            "middleware_ms": int((middleware_end - middleware_start) * 1000)
                        }))
                except Exception as e:
                    pass

                # Forward to ITS Mobile Mock
                its_resp = await client.post(
                    "http://localhost:8002/api/voice", 
                    json={"command": corrected_command}
                )
                
                if its_resp.status_code == 200:
                    logger.info("ITS Mobile Accepted command.")
                    await simulate_ux_feedback("success", "sapsoundsuc.wav")
                else:
                    logger.error(f"ITS Mobile Rejected: {its_resp.text}")
                    await simulate_ux_feedback("error", "sapsounderr.wav")
            else:
                logger.error(f"Middleware Error: {resp.text}")
                await simulate_ux_feedback("error", "sapsounderr.wav")

    except Exception as e:
        logger.error(f"Transcription Error: {e}", exc_info=True)


def keyboard_listener():
    """Simple thread to listen for 'n' key to toggle noise capture mode."""
    global noise_capture_mode
    import termios
    import tty
    import sys
    import select
    
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        logger.info("Keyboard listener started. Press 'n' to toggle Action Button, 'q' to quit.")
        while True:
            # Use select to check for input without blocking the whole thread forever
            rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
            if rlist:
                key = sys.stdin.read(1)
                if key == 'n':
                    noise_capture_mode = not noise_capture_mode
                    status = "ENABLED" if noise_capture_mode else "DISABLED"
                    print(f"\r\n*** Action Button Toggled: Noise Capture Mode {status} ***\r\n", end="", flush=True)
                elif key == 'q' or key == '\x03': # '\x03' is Ctrl+C in raw mode
                    logger.info("Exit key pressed.")
                    break
    except Exception as e:
        logger.error(f"Keyboard listener error: {e}")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        # Force exit the process since we are in a daemon thread
        logger.info("System Exit.")
        import os
        os._exit(0)

async def main():
    # Run the keyboard listener in a separate thread
    kb_thread = threading.Thread(target=keyboard_listener, daemon=True)
    kb_thread.start()

    logger.info(f"Mock WearHF Started. Worker ID: {WORKER_ID}")
    try:
        await process_audio()
    except asyncio.CancelledError:
        logger.info("Audio processing cancelled.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down via KeyboardInterrupt.")
    except Exception as e:
        logger.error(f"Main loop error: {e}")
    finally:
        logger.info("Goodbye.")

