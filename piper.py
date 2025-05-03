from piper import PiperVoice

voice = PiperVoice.load("en_US-lessac-medium")      # auto‑downloads on 1st use
audio = voice.synthesize("Streaming TTS straight from Python.")
with open("out.wav", "wb") as f:
    f.write(audio)

