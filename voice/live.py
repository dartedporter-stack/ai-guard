import asyncio
import os
import queue
import select
import sys
import termios
import tty

import sounddevice as sd

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, LIVE_MODEL
from guard.service import analyze_and_format


# ============================================================
# GEMINI
# ============================================================

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY не найден")

client = genai.Client(
    api_key=GEMINI_API_KEY
)


# ============================================================
# AUDIO
# ============================================================

SAMPLE_RATE = 16000
CHANNELS = 1
BLOCKSIZE = 1600


# ============================================================
# KEYBOARD
# ============================================================

class Keyboard:

    def __init__(self):
        self.old_settings = None

    def start(self):
        self.old_settings = termios.tcgetattr(
            sys.stdin
        )

        tty.setcbreak(
            sys.stdin.fileno()
        )

    def stop(self):
        if self.old_settings is not None:
            termios.tcsetattr(
                sys.stdin,
                termios.TCSADRAIN,
                self.old_settings
            )

    def read_key(self):

        ready, _, _ = select.select(
            [sys.stdin],
            [],
            [],
            0
        )

        if not ready:
            return None

        return sys.stdin.read(1).lower()


# ============================================================
# ONE LIVE PHRASE
# ============================================================

async def transcribe_phrase():

    audio_queue = queue.Queue()
    transcript_parts = []

    recording = True

    config = {
        "response_modalities": [
            "AUDIO"
        ],

        "input_audio_transcription": {},

        "realtime_input_config": {
            "automatic_activity_detection": {
                "disabled": True
            }
        },

        "system_instruction": {
            "parts": [
                {
                    "text": (
                        "Распознавай только входящую речь. "
                        "Не веди диалог и не отвечай пользователю."
                    )
                }
            ]
        }
    }

    print("\n🔌 Новая Live-сессия...")

    async with client.aio.live.connect(
        model=LIVE_MODEL,
        config=config
    ) as session:

        print("✅ Live API подключён.")

        # ====================================================
        # MICROPHONE
        # ====================================================

        def audio_callback(
            indata,
            frames,
            time_info,
            status
        ):

            if status:

                print(
                    "🎙️ Audio status:",
                    status,
                    file=sys.stderr
                )

            if recording:

                audio_queue.put(
                    bytes(indata)
                )

        stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCKSIZE,
            channels=CHANNELS,
            dtype="int16",
            callback=audio_callback
        )

        stream.start()

        # ====================================================
        # ACTIVITY START
        # ====================================================

        await session.send_realtime_input(
            activity_start=types.ActivityStart()
        )

        print("\n🎙️ ГОВОРИ...")
        print("Нажми S, когда закончишь.")

        # ====================================================
        # SEND AUDIO
        # ====================================================

        async def send_audio():

            while recording:

                try:

                    chunk = await asyncio.wait_for(
                        asyncio.to_thread(
                            audio_queue.get
                        ),
                        timeout=0.2
                    )

                except asyncio.TimeoutError:

                    continue

                await session.send_realtime_input(
                    audio=types.Blob(
                        data=chunk,
                        mime_type="audio/pcm;rate=16000"
                    )
                )

        # ====================================================
        # RECEIVE TRANSCRIPTION
        # ====================================================

        async def receive_transcript():

            try:

                async for response in session.receive():

                    if response.server_content is None:
                        continue

                    content = response.server_content

                    if content.input_transcription:

                        text = (
                            content
                            .input_transcription
                            .text
                        )

                        if text:

                            clean = text.strip()

                            if clean:

                                print(
                                    f"\n👤 Ты: {clean}",
                                    flush=True
                                )

                                transcript_parts.append(
                                    clean
                                )

                    if content.turn_complete:

                        break

            except Exception as exc:

                print(
                    "\n⚠️ Ошибка транскрипции:",
                    repr(exc)
                )

        sender_task = asyncio.create_task(
            send_audio()
        )

        receiver_task = asyncio.create_task(
            receive_transcript()
        )

        # ====================================================
        # KEYBOARD
        # ====================================================

        keyboard = Keyboard()
        keyboard.start()

        try:

            while True:

                key = keyboard.read_key()

                if key == "s":
                    break

                if key == "q":

                    recording = False

                    sender_task.cancel()
                    receiver_task.cancel()

                    return None

                await asyncio.sleep(0.03)

        finally:

            keyboard.stop()

        # ====================================================
        # STOP RECORDING
        # ====================================================

        recording = False

        print("\n⏹️ Останавливаю фразу...")

        await session.send_realtime_input(
            activity_end=types.ActivityEnd()
        )

        try:

            await asyncio.wait_for(
                sender_task,
                timeout=2.0
            )

        except asyncio.TimeoutError:

            sender_task.cancel()

        try:

            await asyncio.wait_for(
                receiver_task,
                timeout=5.0
            )

        except asyncio.TimeoutError:

            receiver_task.cancel()

        stream.stop()
        stream.close()

    return " ".join(
        transcript_parts
    ).strip()


# ============================================================
# MAIN LIVE LOOP
# ============================================================

async def run_live_voice():

    print()
    print("=" * 60)
    print("🛡️ AI GUARD LIVE VOICE")
    print("=" * 60)

    print()
    print("R → начать фразу")
    print("S → закончить фразу")
    print("Q → выйти")
    print()

    keyboard = Keyboard()
    keyboard.start()

    try:

        while True:

            print("▶️ Нажми R...")

            while True:

                key = keyboard.read_key()

                if key == "q":
                    return

                if key == "r":
                    break

                await asyncio.sleep(0.03)

            transcript = await transcribe_phrase()

            if transcript is None:
                return

            if not transcript:

                print(
                    "⚠️ Речь не распознана."
                )

                continue

            print()
            print("📝 ТРАНСКРИПЦИЯ:")
            print(transcript)

            # =================================================
            # GUARD CORE
            # =================================================

            print()
            print("🧠 GUARD анализирует...")

            result = await asyncio.to_thread(
                analyze_and_format,
                transcript,
                False
            )

            print()
            print(result)
            print()

    finally:

        keyboard.stop()