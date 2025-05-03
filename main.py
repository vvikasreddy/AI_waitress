import pyaudio
import numpy as np
import queue
import threading
import time
import torch
import whisper  # OpenAI Whisper

# Audio parameters
SAMPLE_RATE = 16000  # 16kHz
CHUNK_DURATION = 0.5  # 500ms chunks
CHUNK_SIZE = int(SAMPLE_RATE * CHUNK_DURATION)  # Samples per chunk
OVERLAP_DURATION = 0  # No overlap (adjust if needed)
OVERLAP_SIZE = int(SAMPLE_RATE * OVERLAP_DURATION)
ACCUMULATION_DURATION = 5  # Reduced from 15 seconds to 5 seconds for lower latency
ACCUMULATION_SIZE = int(SAMPLE_RATE * ACCUMULATION_DURATION)

# Queues for inter-thread communication
audio_queue = queue.Queue()        # Raw audio chunks
vad_queue = queue.Queue()          # VAD-processed chunks
transcription_queue = queue.Queue()  # Transcription text output

# Load models
# Silero VAD model and its utilities (assumes the model supports batch processing)
vad_model, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad', model='silero_vad', force_reload=True)
# Load Whisper model to GPU for faster processing
whisper_model = whisper.load_model("base").to('cuda')


def audio_capture(audio_file_path):
    """
    Audio capture thread using PyAudio.
    (The audio_file_path parameter is kept for compatibility, though currently unused.)
    """
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paFloat32,
                    channels=1,
                    rate=SAMPLE_RATE,
                    input=True,
                    frames_per_buffer=CHUNK_SIZE)
    
    print("Recording...")
    while True:
        data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
        audio_chunk = np.frombuffer(data, dtype=np.float32)
        audio_queue.put(audio_chunk)


def vad_processing():
    """
    VAD processing thread that accumulates audio segments where speech is detected.
    This version batches the processing of 512-sample segments for performance.
    """
    accumulated_audio = np.array([], dtype=np.float32)
    last_change_time = time.time()  # Track last time accumulation changed

    num_samples_per_segment = 512

    while True:
        try:
            chunk = audio_queue.get(timeout=2.0)  # Wait for a chunk up to 2 seconds
        except Exception as e:
            print(f"Timeout waiting for audio chunk: {e}")
            # If timeout and accumulated audio exists, send it downstream.
            if accumulated_audio.size > 0:
                print(f"Timeout: Sending {accumulated_audio.shape[0]} samples to vad_queue")
                vad_queue.put(accumulated_audio)
                accumulated_audio = np.array([], dtype=np.float32)
            continue

        chunk_tensor = torch.from_numpy(chunk).float()
        segment_count = len(chunk_tensor) // num_samples_per_segment
        if segment_count > 0:
            # Batch process segments
            segments = chunk_tensor[:segment_count * num_samples_per_segment].reshape(segment_count, num_samples_per_segment)
            # Call the VAD model on the batch of segments
            speech_flags = vad_model(segments, SAMPLE_RATE)
            # Convert to numpy array if needed
            if isinstance(speech_flags, torch.Tensor):
                speech_flags = speech_flags.cpu().numpy()
            # Check which segments contain speech and accumulate them
            speech_detected = False
            for flag, segment in zip(speech_flags, segments):
                if flag:
                    accumulated_audio = np.concatenate((accumulated_audio, segment.numpy()))
                    speech_detected = True
        else:
            speech_detected = False

        if speech_detected:
            last_change_time = time.time()

        current_time = time.time()
        if accumulated_audio.size > 0:
            # If we've reached the accumulation size or enough time has passed without change, send the chunk
            if accumulated_audio.shape[0] >= ACCUMULATION_SIZE:
                vad_queue.put(accumulated_audio[:ACCUMULATION_SIZE])
                # Retain any overlap if desired (currently OVERLAP_SIZE is zero)
                accumulated_audio = accumulated_audio[ACCUMULATION_SIZE - OVERLAP_SIZE:]
                last_change_time = current_time
            elif (current_time - last_change_time) >= 1.0:  # Reduced timeout from 4.0 to 1.0 sec
                print(f"Sending partial chunk after idle period: {accumulated_audio.shape[0]} samples")
                vad_queue.put(accumulated_audio)
                accumulated_audio = np.array([], dtype=np.float32)
                last_change_time = current_time

        audio_queue.task_done()


def transcription_processing():
    """
    Transcription thread using Whisper.
    Transcribes audio chunks from vad_queue and pushes the text to transcription_queue.
    """
    while True:
        audio_data = vad_queue.get()
        # Ensure audio_data is a 1D NumPy array of float32
        if not (isinstance(audio_data, np.ndarray) and audio_data.dtype == np.float32 and audio_data.ndim == 1):
            audio_data = np.array(audio_data, dtype=np.float32).flatten()

        try:
            # Whisper's transcribe expects an audio array; adjust parameters as needed.
            result = whisper_model.transcribe(audio_data, language="en")
            text = result.get("text", "")
            transcription_queue.put(text)
        except Exception as e:
            print(f"Whisper transcription error: {e}")
        vad_queue.task_done()


def openai_processing():
    """
    Placeholder for OpenAI processing. Currently prints the transcribed text.
    """
    while True:
        text = transcription_queue.get()
        print("Transcribed Text:", text)
        transcription_queue.task_done()


# Start threads
audio_file_path = "interactions/vikas.wav"  # Replace with your audio file if needed
threads = [
    threading.Thread(target=audio_capture, args=(audio_file_path,), daemon=True),
    threading.Thread(target=vad_processing, daemon=True),
    threading.Thread(target=transcription_processing, daemon=True),
    threading.Thread(target=openai_processing, daemon=True)
]

for t in threads:
    t.start()

# Keep the main thread alive
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Shutting down...")
