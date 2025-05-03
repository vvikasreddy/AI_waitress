# tts_server.py
from kokoro import KPipeline
import soundfile as sf
from IPython.display import Audio, display
from fastapi import FastAPI, Request
import uvicorn
import nest_asyncio
import asyncio
import threading
import numpy as np
import sounddevice as sd
import torch
import time 
from pydantic import BaseModel
import ollama


# Load TTS pipeline
def load_tts_model():
    # 🇬🇧 British English
    pipeline = KPipeline(lang_code='b') 
    return pipeline




# ----------------------------------------------------------------------------------
# GLOBALS
# ----------------------------------------------------------------------------------
# load the TTS pipeline once at startup
pipeline = load_tts_model()

# Global flag that every TTS chunk checks so we can interrupt playback at any moment
stop_tts_event = threading.Event()

# A single shared TTS thread; new text cancels the previous thread before starting
tts_thread: threading.Thread | None = None

# Thread‑safe guard so parallel /speak requests don’t race each other
tts_lock = threading.Lock()

# -------------------------------------------------------------------------
# ❶  TEXT‑TO‑SPEECH (Kokoro) WRAPPER
# -------------------------------------------------------------------------

def tts(text: str, pipeline):
    """Stream TTS audio chunks and play them with sounddevice.

    The function exits early if `stop_tts_event` is set, allowing live interruption
    by VAD or by a newer /speak request.
    """
    if not text:
        text = "Hello!, hello, could you please repeat that?"

    print(f"[TTS] >>> {text}")

    try:
        # Pipeline returns an iterator of (generation_status, phonemes, audio_chunk)
        generator = pipeline(
            text,
            voice="af_sky",  # change to any Kokoro voice you like
            speed=1,
            split_pattern=None,
        )

        for i, (gs, ps, audio) in enumerate(generator):
            if stop_tts_event.is_set():
                print("[TTS] Interrupted – user speaking > 0.75 s")
                break

            print(f"[TTS] Chunk {i}: {gs}")
            chunk = (
                np.frombuffer(audio, dtype=np.int16)
                if isinstance(audio, (bytes, bytearray))
                else audio
            )
            sd.play(chunk, samplerate=24000)
            sd.wait()
    except Exception as e:
        print(f"[TTS] Error: {e}")


# -------------------------------------------------------------------------
# ❷  FASTAPI ENDPOINT
# -------------------------------------------------------------------------

app = FastAPI()


def start_tts(text: str):
    """Cancel any running TTS thread and start a new one with the latest text."""
    global tts_thread

    with tts_lock:
        # Interrupt previous TTS (if any)
        if tts_thread and tts_thread.is_alive():
            stop_tts_event.set()
            tts_thread.join()

        stop_tts_event.clear()
        tts_thread = threading.Thread(target=tts, args=(text, pipeline), daemon=True)
        tts_thread.start()


# Store conversation history for memory context
conversation_history = []

async def ollama_receptionist(text: str) -> str:
    """
    Handles receptionist-like interactions using Ollama with memory context.
    Uses a low-latency model and maintains conversation history.
    """
    global conversation_history
    
    # Define the receptionist persona prompt
    system_prompt = """
    You are a friendly, professional receptionist for Chick-fil-A. Your role is to assist users politely,
    answer questions, provide information, or direct them appropriately. Maintain a warm
    and helpful tone, and use the previous conversation context to provide coherent responses.
    your responses should be concise and relevant to the user's inquiries.
    responses should be less than 2 sentences please.   
    """
    
    # Append the new user input to the conversation history
    conversation_history.append({"role": "user", "content": text})
    
    # Prepare the messages with system prompt and conversation history
    messages = [
        {"role": "system", "content": system_prompt},
        *conversation_history[-5:]  # Limit to last 5 exchanges for context
    ]
    
    try:
        # Call Ollama with a low-latency model (llama3.2)
        response = ollama.chat(
            model="llama3.2",
            messages=messages,
            options={
                "temperature": 0.3,  # Balanced creativity
                "num_ctx": 2048,    # Context window size
                "num_predict": 100  # Limit response length
            }
        )
        
        # Extract the response content
        assistant_response = response["message"]["content"]
        
        # Append the assistant's response to the conversation history
        conversation_history.append({"role": "assistant", "content": assistant_response})
        
        # Keep only the last 10 exchanges to manage memory
        conversation_history = conversation_history[-10:]
        
        return assistant_response
    
    except Exception as e:
        return f"Error processing request: {str(e)}"


@app.post("/speak")
async def speak(request: Request):
    data = await request.json()
    text = data.get("text", "")
    
    # Call the Ollama receptionist function
    response_text = await ollama_receptionist(text)
    
    # Start TTS with the response
    start_tts(response_text)
    
    return {"status": "started", "text": response_text}



# -------------------------------------------------------------------------
# ❸  VAD  –  Silero real‑time voice activity detection
# -------------------------------------------------------------------------

def run_vad():
    """Continuously listen on the microphone and interrupt TTS
    if human speech lasts longer than `voice_duration_threshold`."""

    print("[VAD] Starting Silero VAD thread…")

    try:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(device)
        torch.set_num_threads(1)

        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            onnx=False,
        )
        model = model.to(device)  # Uncomment if you want GPU

        samplerate = 16000
        chunk_samples = 512  # 32 ms expected by the model
        speech_threshold = 0.5
        voice_duration_threshold = 0.5 # seconds
        voice_start_time: float | None = None

        def audio_callback(indata, frames, time_info, status):
            nonlocal voice_start_time
            if status:
                print(f"[VAD] Audio status: {status}")

            try:
                audio_chunk = indata[:, 0].astype(np.float32) / 32768.0
                if len(audio_chunk) != chunk_samples:
                    return  # Skip malformed chunk

                speech_prob = model(torch.tensor(audio_chunk).unsqueeze(0).to(device), samplerate).item()

                if speech_prob > speech_threshold:
                    if voice_start_time is None:
                        voice_start_time = time.time()
                    elif time.time() - voice_start_time >= voice_duration_threshold:
                        # Human has been speaking long enough – stop current TTS
                        sd.stop()
                        stop_tts_event.set()
                        
                else:
                    voice_start_time = None
            except Exception as e:
                print(f"[VAD] Error: {e}")

        with sd.InputStream(
            samplerate=samplerate,
            channels=1,
            dtype="int16",
            blocksize=chunk_samples,
            callback=audio_callback,
            latency="low",
        ):
            print("[VAD] Microphone stream open – monitoring…")
            threading.Event().wait()  # Keep thread alive forever
    except Exception as e:
        print(f"[VAD] Fatal error: {e}")

# -------------------------------------------------------------------------
# ❹  MAIN ENTRY POINT
# -------------------------------------------------------------------------

def start():
    
    # Allow nested event loops in notebooks
    nest_asyncio.apply()

    # Launch VAD listener
    threading.Thread(target=run_vad, daemon=True, name="VAD-Thread").start()

    # Run FastAPI server (blocks main thread)
    uvicorn.run(app, host="0.0.0.0", port=5002, log_level="info")

    