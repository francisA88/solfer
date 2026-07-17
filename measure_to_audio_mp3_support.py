#!/usr/bin/env python3
"""
Solfer WAV Generator — Backend-Optimized
========================================
Parses a solfa notation string and writes a mono 44.1kHz WAV file.

String format (same as frontend):
  "d:d:d:d"         → four quarter notes
  "d.d:d:d:-. "     → two eighth d, quarter d, quarter d sustained + rest
  "d,de.r:m'"       → sixteenth d, eighth de, quarter r, m with octave up
  "-"               → sustain (extends previous note)
  " "               → rest (silence)

Usage:
  from solfer_wav import generate_wav
  generate_wav("d:d:d:d", "C", "4/4", "S", 100, "output.wav")
"""

import wave
import struct
import numpy as np
from typing import List, Tuple, Optional

# ── Constants ──
SAMPLE_RATE = 44100
MAX_16BIT = 32767

# Solfa to semitone (relative to do)
SOLFA_ST = {
    'd': 0, 'de': 1, 'r': 2, 'me': 3, 'm': 4, 'f': 5,
    'fe': 6, 's': 7, 'si': 8, 'l': 9, 'ta': 10, 't': 11
}

# Key roots
KEY_ROOTS = {
    'C': 0, 'C#/Db': 1, 'D': 2, 'D#/Eb': 3, 'E': 4, 'F': 5,
    'F#/Gb': 6, 'G': 7, 'G#/Ab': 8, 'A': 9, 'A#/Bb': 10, 'B': 11
}

# Part default octaves
PART_OCTAVE = {'S': 4, 'A': 4, 'T': 3, 'B': 3}

# Two-character note names (must be checked before single-char)
CHROMATIC_NAMES = {'de', 'me', 'fe', 'si', 'ta'}


def parse_note_atom(atom: str) -> Tuple[Optional[str], bool, int]:
    """
    Parse a single note atom like "d", "de", "d'", "d₁", "-", " ", "".
    Returns: (note_name_or_None, octave_up, subscript)
    For rests/sustains: note_name is None, returns (None, False, 0).
    """
    atom = atom.strip()
    if not atom or atom == ' ':
        return (None, False, 0)  # rest
    if atom == '-':
        return (None, False, 0)  # sustain (handled at beat level)

    up = False
    sub = 0

    # Check trailing octave modifiers
    if atom.endswith("'"):
        up = True
        atom = atom[:-1]
    elif atom.endswith('₁'):
        sub = 1
        atom = atom[:-1]
    elif atom.endswith('₂'):
        sub = 2
        atom = atom[:-1]

    return (atom, up, sub)


def note_to_freq(note_name: str, up: bool, sub: int, key: str, part: str) -> float:
    """Convert solfa note to frequency in Hz."""
    semitone = SOLFA_ST.get(note_name)
    if semitone is None:
        return 0.0

    root = KEY_ROOTS.get(key, 0)
    base_oct = PART_OCTAVE.get(part, 4)
    octv = base_oct
    if up:
        octv = base_oct + 1
    elif sub:
        octv = base_oct - sub

    midi_note = (octv + 1) * 12 + ((root + semitone) % 12)
    return 440.0 * (2.0 ** ((midi_note - 69) / 12.0))


def parse_beat(beat_str: str) -> List[Tuple[Optional[str], float]]:
    """
    Parse one beat string into list of (note_atom, duration_in_beats).

    Format: A,B(.)C,D where:
      no dot  → one quarter note/rest/sustain (dur=1.0)
      dot     → two eighth halves (dur=0.5 each)
      comma   → two sixteenths within a half (dur=0.25 each)

    Returns list of (atom, duration) tuples.
    atom is None for rest/sustain.
    """
    beat_str = beat_str.strip()
    if not beat_str:
        return [(None, 1.0)]  # empty = quarter rest

    # No dot = single quarter
    if '.' not in beat_str:
        return [(beat_str, 1.0)]

    halves = beat_str.split('.')
    if len(halves) != 2:
        return [(None, 1.0)]  # malformed, treat as rest

    result = []
    for half in halves:
        half = half.strip()
        if not half:
            result.append((None, 0.5))  # empty half = eighth rest
            continue

        if ',' in half:
            parts = half.split(',')
            if len(parts) == 2:
                result.append((parts[0].strip(), 0.25))
                result.append((parts[1].strip(), 0.25))
            else:
                result.append((half, 0.5))  # malformed comma
        else:
            result.append((half, 0.5))

    return result


def parse_measure(raw_string: str) -> List[Tuple[Optional[str], float]]:
    """
    Parse full measure string into flat list of (atom, duration_in_beats).
    Splits by ':' then parses each beat.
    """
    if not raw_string:
        return []

    beats = raw_string.split(':')
    result = []
    for beat in beats:
        result.extend(parse_beat(beat))
    return result


def generate_note_samples(freq: float, dur_seconds: float, sr: int = SAMPLE_RATE) -> np.ndarray:
    """
    Generate sine wave samples for one note with ADSR envelope.
    Uses vectorized numpy — no Python loops over samples.
    """
    n_samples = int(sr * dur_seconds)
    if n_samples <= 0:
        return np.zeros(0, dtype=np.float32)

    # Time array (vectorized)
    t = np.arange(n_samples, dtype=np.float32) / sr

    # Sine wave (vectorized)
    phase = 2.0 * np.pi * freq * t
    samples = np.sin(phase, dtype=np.float32)

    # Simple ADSR envelope (vectorized, multiplicative)
    # Attack: 5% | Decay: 10% | Sustain: 70% | Release: 15%
    attack_samps = int(n_samples * 0.05)
    decay_samps = int(n_samples * 0.10)
    release_samps = int(n_samples * 0.15)
    sustain_samps = n_samples - attack_samps - decay_samps - release_samps

    envelope = np.ones(n_samples, dtype=np.float32)

    if attack_samps > 0:
        envelope[:attack_samps] = np.linspace(0.0, 1.0, attack_samps, dtype=np.float32)
    if decay_samps > 0:
        env_decay = np.linspace(1.0, 0.7, decay_samps, dtype=np.float32)
        envelope[attack_samps:attack_samps + decay_samps] = env_decay
    if sustain_samps > 0:
        envelope[attack_samps + decay_samps:attack_samps + decay_samps + sustain_samps] = 0.7
    if release_samps > 0:
        env_release = np.linspace(0.7, 0.0, release_samps, dtype=np.float32)
        envelope[-release_samps:] = env_release

    return samples * envelope


def generate_measure_audio(
    raw_string: str,
    key: str,
    part: str,
    tempo_bpm: int,
    sr: int = SAMPLE_RATE
) -> np.ndarray:
    """
    Parse measure string and generate audio as float32 numpy array.
    Handles sustain merging and rest gaps.
    """
    events = parse_measure(raw_string)
    if not events:
        return np.zeros(0, dtype=np.float32)

    beat_dur = 60.0 / tempo_bpm

    # First pass: resolve sustains into previous note durations
    # Build list of (freq, dur_seconds, is_rest)
    tones = []
    last_pitched_idx = -1

    for atom, dur_beats in events:
        dur_sec = dur_beats * beat_dur

        if atom == '-':
            # Sustain: extend previous pitched note
            if last_pitched_idx >= 0:
                tones[last_pitched_idx] = (
                    tones[last_pitched_idx][0],
                    tones[last_pitched_idx][1] + dur_sec,
                    tones[last_pitched_idx][2]
                )
            # Skip adding sustain as separate event
        elif not atom or atom == ' ':
            # Rest: silence, breaks sustain chain
            tones.append((0.0, dur_sec, True))
            last_pitched_idx = -1
        else:
            # Pitched note
            note_name, up, sub = parse_note_atom(atom)
            if note_name:
                freq = note_to_freq(note_name, up, sub, key, part)
            else:
                freq = 0.0
            tones.append((freq, dur_sec, False))
            last_pitched_idx = len(tones) - 1

    # Second pass: pre-calculate total samples and allocate once
    total_samples = sum(int(sr * dur) for _, dur, _ in tones)
    audio = np.zeros(total_samples, dtype=np.float32)

    # Third pass: generate and copy into pre-allocated array
    offset = 0
    for freq, dur_sec, is_rest in tones:
        n_samps = int(sr * dur_sec)
        if n_samps <= 0:
            continue

        if is_rest or freq <= 0:
            # Silence — array already zero-initialized, just advance offset
            offset += n_samps
        else:
            note_audio = generate_note_samples(freq, dur_sec, sr)
            # Ensure exact length match (rounding differences)
            if len(note_audio) > n_samps:
                note_audio = note_audio[:n_samps]
            elif len(note_audio) < n_samps:
                note_audio = np.pad(note_audio, (0, n_samps - len(note_audio)), 'constant')

            audio[offset:offset + n_samps] = note_audio
            offset += n_samps

    return audio


def write_wav(audio: np.ndarray, filename: str, sr: int = SAMPLE_RATE) -> None:
    """
    Write float32 audio array to 16-bit mono WAV file.
    Uses stdlib wave + struct — no scipy dependency.
    """
    # Normalize to prevent clipping
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak * 0.95  # leave 5% headroom

    # Convert to int16
    audio_int16 = (audio * MAX_16BIT).astype(np.int16)

    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(1)      # mono
        wf.setsampwidth(2)      # 16-bit
        wf.setframerate(sr)     # 44.1kHz

        # Pack and write in chunks for memory efficiency
        chunk_size = 4096
        for i in range(0, len(audio_int16), chunk_size):
            chunk = audio_int16[i:i + chunk_size]
            wf.writeframes(chunk.tobytes())


def generate_wav(
    raw_string: str,
    key: str,
    time_sig: str,
    part: str,
    tempo_bpm: int,
    output_path: str,
    sr: int = SAMPLE_RATE
) -> str:
    """
    High-level API: parse string and write WAV file.

    Args:
        raw_string: Solfa notation string (e.g. "d:d:d:d")
        key: Key signature (e.g. "C", "G")
        time_sig: Time signature (e.g. "4/4") — informational only
        part: Voice part ("S", "A", "T", "B")
        tempo_bpm: Tempo in beats per minute
        output_path: Output WAV file path
        sr: Sample rate (default 44100)

    Returns:
        output_path on success
    """
    audio = generate_measure_audio(raw_string, key, part, tempo_bpm, sr)
    write_wav(audio, output_path, sr)
    return output_path


# ── Batch / multi-measure support ──

def generate_multi_measure_wav(
    measures: List[dict],
    output_path: str,
    sr: int = SAMPLE_RATE
) -> str:
    """
    Generate WAV from multiple measures with gaps between them.

    measures: list of dicts with keys:
      rawString, key, time, part, tempo
    """
    all_audio = []
    gap_seconds = 0.5  # half-second gap between measures
    gap_samples = int(sr * gap_seconds)

    for i, m in enumerate(measures):
        audio = generate_measure_audio(
            m['rawString'],
            m.get('key', 'C'),
            m.get('part', 'S'),
            m.get('tempo', 100),
            sr
        )
        all_audio.append(audio)

        # Add gap between measures (not after last)
        if i < len(measures) - 1:
            all_audio.append(np.zeros(gap_samples, dtype=np.float32))

    if not all_audio:
        return output_path

    combined = np.concatenate(all_audio)
    write_wav(combined, output_path, sr)
    return output_path


# ── CLI entry point ──
if __name__ == '__main__':
    import sys
    import argparse

    parser = argparse.ArgumentParser(description='Solfer WAV Generator')
    parser.add_argument('string', help='Solfa notation string')
    parser.add_argument('-k', '--key', default='C', help='Key signature')
    parser.add_argument('-t', '--time', default='4/4', help='Time signature')
    parser.add_argument('-p', '--part', default='S', choices=['S','A','T','B'], help='Voice part')
    parser.add_argument('--tempo', type=int, default=100, help='Tempo BPM')
    parser.add_argument('-o', '--output', default='output.wav', help='Output file')

    args = parser.parse_args()

    generate_wav(args.string, args.key, args.time, args.part, args.tempo, args.output)
    print(f"Wrote {args.output}")


# ── MP3 Generation (fast path) ──

def write_mp3(audio: np.ndarray, filename: str, sr: int = SAMPLE_RATE, bitrate: str = "192k") -> None:
    """
    Write float32 audio to MP3 using ffmpeg (libmp3lame).
    Requires ffmpeg installed on the server. Falls back to WAV + pydub if unavailable.

    For maximum speed on backend, ensure ffmpeg is installed:
      apt-get install ffmpeg  (Ubuntu/Debian)
      brew install ffmpeg     (macOS)
    """
    import subprocess
    import os
    import tempfile

    # Normalize like WAV
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak * 0.95
    audio_int16 = (audio * MAX_16BIT).astype(np.int16)

    # Write temporary WAV, then convert to MP3 via ffmpeg
    # This is faster than pure-Python MP3 encoders by 50-100x
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
        tmp_path = tmp.name
        with wave.open(tmp_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(audio_int16.tobytes())

    try:
        # ffmpeg: fastest MP3 encoder available
        # -y: overwrite, -i: input, -codec:a libmp3lame, -q:a quality (0=best, 9=worst)
        # Using CBR bitrate for predictable file size, VBR for speed
        cmd = [
            'ffmpeg', '-y', '-i', tmp_path,
            '-codec:a', 'libmp3lame',
            '-b:a', bitrate,
            '-f', 'mp3',
            filename
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fallback: pydub (slower, pure-ish Python wrapper)
        try:
            from pydub import AudioSegment
            seg = AudioSegment(
                audio_int16.tobytes(),
                frame_rate=sr,
                sample_width=2,
                channels=1
            )
            seg.export(filename, format="mp3", bitrate=bitrate)
        except ImportError:
            raise RuntimeError(
                "MP3 encoding requires ffmpeg (fast) or pydub (fallback). "
                "Install: apt-get install ffmpeg OR pip install pydub"
            )
    finally:
        os.unlink(tmp_path)


def generate_mp3(
    raw_string: str,
    key: str,
    time_sig: str,
    part: str,
    tempo_bpm: int,
    output_path: str,
    bitrate: str = "192k",
    sr: int = SAMPLE_RATE
) -> str:
    """
    High-level API: parse string and write MP3 file via ffmpeg.
    """
    audio = generate_measure_audio(raw_string, key, part, tempo_bpm, sr)
    write_mp3(audio, output_path, sr, bitrate)
    return output_path
