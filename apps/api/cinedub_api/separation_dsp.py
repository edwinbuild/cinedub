"""MRX transform contract matching MERL's normalized, centered Hann STFT.

Architecture/transform reference: MERL cocktail-fork-separation, MIT,
Copyright (c) 2023 Mitsubishi Electric Research Laboratories. See
docs/decisions/0005-cinematic-separation.md for provenance and attribution.
"""

import numpy as np

WINDOWS = (1024, 2048, 8192)
HOP = 256
STEMS = ("music", "dialogue", "effects")


def stft(samples, size):
    samples = np.asarray(samples, dtype=np.float32)
    padded = np.pad(samples, (size // 2, size // 2), mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(padded, size)[::HOP]
    window = np.hanning(size + 1)[:-1].astype(np.float32)
    return (np.fft.rfft(frames * window, axis=-1) / np.sqrt(size)).T.astype(np.complex64)


def istft(spectrum, size, length):
    window = np.hanning(size + 1)[:-1].astype(np.float32)
    frames = (np.fft.irfft(spectrum.T, n=size, axis=-1) * np.sqrt(size)).astype(np.float32)
    output = np.zeros((len(frames) - 1) * HOP + size, dtype=np.float32)
    denominator = np.zeros_like(output)
    for index, frame in enumerate(frames):
        start = index * HOP
        output[start : start + size] += frame * window
        denominator[start : start + size] += window * window
    output /= np.maximum(denominator, 1e-10)
    return output[size // 2 : size // 2 + length]


def separate_chunk(samples, session):
    spectra = {size: stft(samples, size) for size in WINDOWS}
    masks = session.run(
        [f"mask_{size}" for size in WINDOWS],
        {f"mag_{size}": np.abs(spectra[size])[None].astype(np.float32) for size in WINDOWS},
    )
    stems = np.zeros((3, len(samples)), dtype=np.float32)
    for size, mask in zip(WINDOWS, masks, strict=True):
        expected = (1, 3, size // 2 + 1, spectra[size].shape[1])
        if mask.shape != expected or not np.isfinite(mask).all():
            raise ValueError("Separator returned invalid masks")
        for index in range(3):
            stems[index] += istft(mask[0, index] * spectra[size], size, len(samples))
    if not np.isfinite(stems).all():
        raise ValueError("Separator produced invalid samples")
    return stems


def separate_channels(samples, session, *, sample_rate=44100, progress=None):
    """20-second windows with two-second context; never downmix stereo input."""
    samples = np.asarray(samples, dtype=np.float32)
    length, channels = samples.shape
    context = sample_rate * 2
    core = sample_rate * 16
    output = np.zeros((3, length, channels), dtype=np.float32)
    completed = 0
    total = channels * ((length + core - 1) // core)
    for channel in range(channels):
        weights = np.zeros(length, dtype=np.float32)
        for start in range(0, length, core):
            end = min(length, start + core)
            left, right = max(0, start - context), min(length, end + context)
            chunk = separate_chunk(samples[left:right, channel], session)
            envelope = np.ones(right - left, dtype=np.float32)
            fade = min(context * 2, right - left)
            if left > 0:
                envelope[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
            if right < length:
                envelope[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
            output[:, left:right, channel] += chunk * envelope
            weights[left:right] += envelope
            completed += 1
            if progress:
                progress(completed, total)
        output[:, :, channel] /= np.maximum(weights, 1e-10)
    return output
