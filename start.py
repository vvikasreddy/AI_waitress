import sys, requests

sys.path.append(r'D:\Projects\RealtimeSTT')

from RealtimeSTT import AudioToTextRecorder

def process_text(text):
    # inside your STT script after getting the transcription
    transcribed_text = text

    try:
        response = requests.post(
            "http://localhost:5002/speak",
            json={"text": transcribed_text}
        )   
    except Exception as e:
        print(f"Error: {e}")
        print("Error: Unable to send the transcribed text.")
        print(f"Please check if the STT server is running and accessible.")
        return

    print(response.json())

if __name__ == '__main__':
    print("Wait until it says 'speak now'")
    recorder = AudioToTextRecorder()

    while True:
        recorder.text(process_text)