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

SOLFA_ST = {
    'd': 0, 'de': 1, 'r': 2, 'me': 3, 'm': 4, 'f': 5,
    'fe': 6, 's': 7, 'si': 8, 'l': 9, 'ta': 10, 't': 11
}

KEY_ROOTS = {
    'C': 0, 'C#/Db': 1, 'D': 2, 'D#/Eb': 3, 'E': 4, 'F': 5,
    'F#/Gb': 6, 'G': 7, 'G#/Ab': 8, 'A': 9, 'A#/Bb': 10, 'B': 11
}

PART_OCTAVE = {'S': 4, 'A': 4, 'T': 3, 'B': 3}
CHROMATIC_NAMES = {'de', 'me', 'fe', 'si', 'ta'}


def parse_note_atom(atom: str) -> Tuple[Optional[str], bool, int]:
    """
    Parse a single note atom like "d", "de", "d'", "d₁", "-", " ", "".
    Returns: (note_name_or_None, octave_up, subscript)
    """
    atom = atom.strip()
    if not atom or atom == ' ':
        return (None, False, 0)  # rest
    if atom == '-':
        return (None, False, 0)  # sustain (handled at beat level)

    up = False
    sub = 0

    if atom.endswith("'"):
        up = True
        atom = atom[:-1]
    elif atom.endswith('₁') or atom.endswith("1"):
        sub = 1
        atom = atom[:-1]
    elif atom.endswith('₂') or atom.endswith("2"):
        sub = 2
        atom = atom[:-1]

    return (atom, up, sub)


def note_to_freq(note_name: str, up: bool, sub: int, key: str, part: str) -> float:
    """
    Convert a solfa note to frequency in Hz.

    Uses MIDI arithmetic so octave boundaries are exact, then applies
    the same tonic-floor correction as the JS frontend:
      if the raw MIDI pitch falls below the tonic 'd' in the same octave,
      bump it up by 12 semitones so every scale degree always sits
      above 'd' — matching how tonic solfa notation works.
    """
    semitone = SOLFA_ST.get(note_name)
    if semitone is None:
        return 0.0

    root     = KEY_ROOTS.get(key, 0)
    base_oct = PART_OCTAVE.get(part, 4)

    octv = base_oct
    if up:
        octv = base_oct + 1
    elif sub:
        octv = base_oct - sub

    # MIDI note of the tonic 'd' in this octave — the reference floor.
    # MIDI middle C = 60 = C4, formula: (octave + 1) * 12 + chromatic_position
    tonic_midi = (octv + 1) * 12 + root

    # Raw MIDI note of the requested scale degree
    note_midi  = (octv + 1) * 12 + ((root + semitone) % 12)

    # If the chromatic wrap pushed the note below the tonic, raise one octave.
    # e.g. key of A (root=9), note s (semitone=7):
    #   tonic_midi = 69 (A4), note_midi = 64 (E4) → 64 < 69 → raise to 76 (E5)
    if note_midi < tonic_midi:
        note_midi += 12

    # Convert MIDI to Hz: A4 = MIDI 69 = 440 Hz
    return 440.0 * (2.0 ** ((note_midi - 69) / 12.0))


def parse_beat(beat_str: str) -> List[Tuple[Optional[str], float]]:
    """
    Parse one beat string into list of (note_atom, duration_in_beats).
    """
    beat_str = beat_str.strip()
    if not beat_str:
        return [(None, 1.0)]

    if '.' not in beat_str:
        return [(beat_str, 1.0)]

    halves = beat_str.split('.')
    if len(halves) != 2:
        return [(None, 1.0)]

    result = []
    for half in halves:
        half = half.strip()
        if not half:
            result.append((None, 0.5))
            continue

        if ',' in half:
            parts = half.split(',')
            if len(parts) == 2:
                result.append((parts[0].strip(), 0.25))
                result.append((parts[1].strip(), 0.25))
            else:
                result.append((half, 0.5))
        else:
            result.append((half, 0.5))

    return result


def parse_measure(raw_string: str) -> List[Tuple[Optional[str], float]]:
    if not raw_string:
        return []
    beats = raw_string.split(':')
    result = []
    for beat in beats:
        result.extend(parse_beat(beat))
    return result


def parse_measures(raw_string: str) -> List[Tuple[Optional[str], float]]:
    if not raw_string:
        return []
    measures = raw_string.split('|')
    result = []
    for measure in measures:
        result.extend(parse_measure(measure))
    return result


def generate_note_samples(freq: float, dur_seconds: float, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Generate sine wave samples with ADSR envelope."""
    n_samples = int(sr * dur_seconds)
    if n_samples <= 0:
        return np.zeros(0, dtype=np.float32)

    t = np.arange(n_samples, dtype=np.float32) / sr
    samples = np.sin(2.0 * np.pi * freq * t, dtype=np.float32)

    attack_samps  = int(n_samples * 0.05)
    decay_samps   = int(n_samples * 0.10)
    release_samps = int(n_samples * 0.15)
    sustain_samps = n_samples - attack_samps - decay_samps - release_samps

    envelope = np.ones(n_samples, dtype=np.float32)
    if attack_samps  > 0: envelope[:attack_samps] = np.linspace(0.0, 1.0, attack_samps)
    if decay_samps   > 0: envelope[attack_samps:attack_samps+decay_samps] = np.linspace(1.0, 0.7, decay_samps)
    if sustain_samps > 0: envelope[attack_samps+decay_samps:attack_samps+decay_samps+sustain_samps] = 0.7
    if release_samps > 0: envelope[-release_samps:] = np.linspace(0.7, 0.0, release_samps)

    return samples * envelope


def generate_measure_audio(
    raw_string: str,
    key: str,
    part: str,
    tempo_bpm: int,
    sr: int = SAMPLE_RATE
) -> np.ndarray:
    """Parse measure string and generate audio as float32 numpy array."""
    events = parse_measures(raw_string)
    if not events:
        return np.zeros(0, dtype=np.float32)

    beat_dur = 60.0 / tempo_bpm
    tones = []
    last_pitched_idx = -1

    for atom, dur_beats in events:
        dur_sec = dur_beats * beat_dur

        if atom == '-':
            if last_pitched_idx >= 0:
                f, d, r = tones[last_pitched_idx]
                tones[last_pitched_idx] = (f, d + dur_sec, r)
        elif not atom or atom.strip() == '':
            tones.append((0.0, dur_sec, True))
            last_pitched_idx = -1
        else:
            note_name, up, sub = parse_note_atom(atom)
            freq = note_to_freq(note_name, up, sub, key, part) if note_name else 0.0
            tones.append((freq, dur_sec, False))
            last_pitched_idx = len(tones) - 1

    total_samples = sum(int(sr * dur) for _, dur, _ in tones)
    audio = np.zeros(total_samples, dtype=np.float32)

    offset = 0
    for freq, dur_sec, is_rest in tones:
        n_samps = int(sr * dur_sec)
        if n_samps <= 0:
            continue
        if not is_rest and freq > 0:
            note_audio = generate_note_samples(freq, dur_sec, sr)
            if len(note_audio) > n_samps:
                note_audio = note_audio[:n_samps]
            elif len(note_audio) < n_samps:
                note_audio = np.pad(note_audio, (0, n_samps - len(note_audio)), 'constant')
            audio[offset:offset + n_samps] = note_audio
        offset += n_samps

    return audio


def write_wav(audio: np.ndarray, filename: str, sr: int = SAMPLE_RATE) -> None:
    """Write float32 audio array to 16-bit mono WAV file."""
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak * 0.95

    audio_int16 = (audio * MAX_16BIT).astype(np.int16)

    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        chunk_size = 4096
        for i in range(0, len(audio_int16), chunk_size):
            wf.writeframes(audio_int16[i:i + chunk_size].tobytes())


def generate_wav(
    raw_string: str,
    key: str,
    time_sig: str,
    part: str,
    tempo_bpm: int,
    output_path: str,
    sr: int = SAMPLE_RATE
) -> str:
    audio = generate_measure_audio(raw_string, key, part, tempo_bpm, sr)
    write_wav(audio, output_path, sr)
    return output_path


def generate_multi_measure_wav(
    measures: List[dict],
    output_path: str,
    sr: int = SAMPLE_RATE
) -> str:
    all_audio = []
    gap_samples = int(sr * 0.05)  # 50ms gap between measures

    for i, m in enumerate(measures):
        audio = generate_measure_audio(
            m['rawString'], m.get('key', 'C'),
            m.get('part', 'S'), m.get('tempo', 100), sr
        )
        all_audio.append(audio)
        if i < len(measures) - 1:
            all_audio.append(np.zeros(gap_samples, dtype=np.float32))

    if not all_audio:
        return output_path

    write_wav(np.concatenate(all_audio), output_path, sr)
    return output_path


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Solfer WAV Generator')
    parser.add_argument('string', help='Solfa notation string')
    parser.add_argument('-k', '--key',   default='C')
    parser.add_argument('-t', '--time',  default='4/4')
    parser.add_argument('-p', '--part',  default='S', choices=['S','A','T','B'])
    parser.add_argument('--tempo', type=int, default=100)
    parser.add_argument('-o', '--output', default='output.wav')

    args = parser.parse_args()
    generate_wav(args.string, args.key, args.time, args.part, args.tempo, args.output)
    print(f"Wrote {args.output}")