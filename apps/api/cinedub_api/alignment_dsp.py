"""Bounded CTC Viterbi alignment, without timestamps invented for missing symbols."""

import re
import unicodedata

import numpy as np


def english_tokens(text, vocab):
    text = unicodedata.normalize("NFKC", text).upper().replace("’", "'").replace("‘", "'")
    # Punctuation separates words; numbers/foreign letters are not silently deleted or guessed.
    text = re.sub(r"[.,!?;:\"()\[\]{}\-—–…/\\]", " ", text)
    text = " ".join(text.split())
    if not text or len(text) > 1000:
        raise ValueError("Use a non-empty English phrase of at most 1000 characters")
    unsupported = sorted({char for char in text if char != " " and char not in vocab})
    if unsupported:
        raise ValueError("Unsupported characters: " + " ".join(unsupported) + "; spell numbers out")
    return text, [vocab[char if char != " " else "|"] for char in text]


def text_error_ratio(actual, expected):
    actual, expected = actual.replace(" ", ""), expected.replace(" ", "")
    previous = list(range(len(expected) + 1))
    for index, char in enumerate(actual, 1):
        current = [index]
        for position, other in enumerate(expected, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[position] + 1,
                    previous[position - 1] + (char != other),
                )
            )
        previous = current
    return previous[-1] / max(1, len(actual), len(expected))


def force_align(logits, tokens, normalized, vocab, *, offset_ms, duration_ms):
    """Standard CTC blank/interleaved states, including repeated-letter blank transitions.

    The 16 kHz wav2vec2 convolution stride is 320 samples (20 ms). Scores are acoustic
    emission scores, NOT calibrated probabilities that the words/timings are correct.
    """
    logits = np.asarray(logits, dtype=np.float64)
    if logits.ndim != 2 or not np.isfinite(logits).all() or not len(tokens):
        raise ValueError("Invalid CTC emissions or transcript")
    if logits.shape[0] > 1100 or len(tokens) > 1000:
        raise ValueError("Alignment window exceeds the bounded laptop profile")
    if logits.shape[1] != len(vocab) or any(token >= logits.shape[1] for token in tokens):
        raise ValueError("CTC vocabulary does not match emissions")
    logits -= np.max(logits, axis=1, keepdims=True)
    logp = logits - np.log(np.exp(logits).sum(axis=1, keepdims=True))
    blank = vocab["<pad>"]
    labels = np.full(2 * len(tokens) + 1, blank, dtype=np.int32)
    labels[1::2] = tokens
    skip = np.zeros(len(labels), dtype=bool)
    skip[2:] = (labels[2:] != blank) & (labels[2:] != labels[:-2])
    scores = np.full(len(labels), -np.inf)
    scores[0] = 0
    parents = np.zeros((len(logp), len(labels)), dtype=np.uint8)
    for frame, emission in enumerate(logp):
        advance = np.r_[-np.inf, scores[:-1]]
        jump = np.r_[-np.inf, -np.inf, scores[:-2]]
        jump[~skip] = -np.inf
        choices = np.stack((scores, advance, jump))
        step = choices.argmax(axis=0)
        parents[frame] = step
        scores = choices[step, np.arange(len(labels))] + emission[labels]
    state = len(labels) - (1 if scores[-1] >= scores[-2] else 2)
    if not np.isfinite(scores[state]):
        raise ValueError("Transcript cannot fit the available acoustic frames")
    token_frames = [[] for _ in tokens]
    for frame in range(len(logp) - 1, -1, -1):
        if state % 2:
            token_frames[state // 2].append(frame)
        state -= int(parents[frame, state])
    if state != 0 or any(not frames for frames in token_frames):
        raise ValueError("Incomplete CTC path")
    words, position = [], 0
    for word in normalized.split():
        frames = [
            frame for group in token_frames[position : position + len(word)] for frame in group
        ]
        emissions = [
            logp[frame, tokens[index]]
            for index in range(position, position + len(word))
            for frame in token_frames[index]
        ]
        start = offset_ms + min(frames) * 20
        end = min(duration_ms, offset_ms + (max(frames) + 1) * 20)
        if end <= start:
            raise ValueError("Word lies outside the audio window")
        words.append(
            {
                "text": word,
                "start_ms": start,
                "end_ms": end,
                "acoustic_score": round(float(np.exp(np.mean(emissions))), 4),
            }
        )
        position += len(word) + 1
    ids = logits.argmax(axis=1)
    inverse = {value: key for key, value in vocab.items()}
    collapsed = [
        int(token)
        for index, token in enumerate(ids)
        if token != blank and (index == 0 or token != ids[index - 1])
    ]
    greedy = "".join(inverse[token] for token in collapsed).replace("|", " ").strip()
    return {
        "words": words,
        "acoustic_score": round(float(np.mean([word["acoustic_score"] for word in words])), 4),
        "greedy_text": greedy,
        "text_error_ratio": round(text_error_ratio(greedy, normalized), 4),
    }
