import io
import unittest
import wave

from guard.audio import (
    MAX_AUDIO_SECONDS,
    PCM_SAMPLE_WIDTH,
    PCM_SAMPLE_RATE,
    pcm16_to_wav,
)


class AudioTest(unittest.TestCase):
    def test_pcm16_to_wav_adds_expected_header(self):
        pcm = bytes(PCM_SAMPLE_RATE * PCM_SAMPLE_WIDTH // 10)

        wav_bytes = pcm16_to_wav(pcm)

        with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.getsampwidth(), 2)
            self.assertEqual(wav_file.getframerate(), PCM_SAMPLE_RATE)
            self.assertEqual(wav_file.readframes(wav_file.getnframes()), pcm)

    def test_rejects_too_short_audio(self):
        with self.assertRaisesRegex(ValueError, "слишком короткая"):
            pcm16_to_wav(bytes(PCM_SAMPLE_RATE * PCM_SAMPLE_WIDTH // 10 - 2))

    def test_rejects_audio_over_sixty_seconds(self):
        with self.assertRaisesRegex(ValueError, "60 секунд"):
            pcm16_to_wav(
                bytes(
                    PCM_SAMPLE_RATE
                    * PCM_SAMPLE_WIDTH
                    * MAX_AUDIO_SECONDS
                    + 2
                )
            )

    def test_uses_actual_sample_rate(self):
        sample_rate = 48_000
        pcm = bytes(sample_rate * PCM_SAMPLE_WIDTH // 10)

        wav_bytes = pcm16_to_wav(pcm, sample_rate)

        with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
            self.assertEqual(wav_file.getframerate(), sample_rate)


if __name__ == "__main__":
    unittest.main()
