"""DistilBERT-based text anomaly scorer for Layer 5.

Computes pseudo-perplexity of a merchant-name string using DistilBERT's
masked language model. High perplexity means "surprising to a model trained
on English text" — a strong signal for bot-generated / typosquatted /
random-string merchant identities that pure tabular features miss.

Algorithm (masked pseudo-perplexity):
    1. Tokenize input string
    2. For each non-special token position i:
       - Replace token i with [MASK]
       - Run DistilBertForMaskedLM
       - Get log P(true_token) at position i
    3. avg_log_prob = mean over all positions
    4. perplexity = exp(-avg_log_prob)
    5. log_perplexity = -avg_log_prob   # more convenient scale
    6. score = sigmoid((log_perplexity - threshold) * slope)   # [0, 1]
    7. label = SUSPICIOUS if log_perplexity >= threshold else NORMAL

The first call downloads ~250 MB of DistilBERT weights (cached by HF Hub).
Subsequent calls reuse the cache and take ~50-200ms per merchant string on
CPU.

Usage:
    from velocityfraud.text_anomaly import score_merchant

    result = score_merchant("W-MERCHANT-XJ8K2-zzz9.com")
    print(result.label, result.score, result.perplexity)

Smoke test (runs a curated demo battery):
    uv run python -m velocityfraud.text_anomaly
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from functools import lru_cache

from loguru import logger


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODEL_NAME = os.getenv("TEXT_MODEL", "distilbert-base-uncased")

# Log-perplexity above this = SUSPICIOUS. Empirical calibration: normal
# English domain-like strings (gmail.com, yahoo.com) have log-perplexity
# ~2-5. Random gibberish (XJ8K2-zzz9.com) hits 8-15. 6.0 is a reasonable
# middle-ground default.
SUSPICIOUS_THRESHOLD_LOG_PPL = float(os.getenv("TEXT_SUSPICIOUS_THRESHOLD", "6.0"))

# Slope for sigmoid normalization. Larger = sharper transition around threshold.
SIGMOID_SLOPE = float(os.getenv("TEXT_SIGMOID_SLOPE", "0.5"))

# Token cap: merchant strings are short; 32 tokens is plenty (~100 chars).
MAX_LENGTH = int(os.getenv("TEXT_MAX_LENGTH", "32"))


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------
@dataclass
class TextAnomalyResult:
    """One anomaly-scoring result for a single input string."""
    text: str            # what was actually scored (after any preprocessing)
    perplexity: float    # exp(-avg_log_prob)
    log_perplexity: float  # -avg_log_prob (more convenient scale)
    score: float         # normalized to [0.0, 1.0]
    label: str           # "NORMAL" | "SUSPICIOUS"


# ---------------------------------------------------------------------------
# Model loading (lazy, cached)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _get_model():
    """Load DistilBERT tokenizer + masked-LM model. Cached after first call."""
    logger.info("Loading DistilBERT '{}' (downloads ~250MB on first call)...",
                MODEL_NAME)
    import torch
    from transformers import DistilBertForMaskedLM, DistilBertTokenizerFast

    tokenizer = DistilBertTokenizerFast.from_pretrained(MODEL_NAME)
    model = DistilBertForMaskedLM.from_pretrained(MODEL_NAME)
    model.eval()  # inference mode: no dropout, no gradient tracking
    logger.info("DistilBERT ready. Vocab size: {}", tokenizer.vocab_size)
    return tokenizer, model, torch


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------
def _extract_domain(merchant_name: str) -> str:
    """The replayer encodes merchant_name as '{ProductCD}-MERCHANT-{email_domain}'.

    The interesting anomaly signal is the domain part, not the fixed prefix.
    Example: 'W-MERCHANT-gmail.com' -> 'gmail.com'.
    """
    if not merchant_name or "-MERCHANT-" not in merchant_name:
        return merchant_name or ""
    parts = merchant_name.split("-MERCHANT-", 1)
    return parts[1].strip() if len(parts) == 2 else merchant_name


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------
def score_text(text: str) -> TextAnomalyResult:
    """Compute pseudo-perplexity + label for one raw string."""
    if not text:
        return TextAnomalyResult(
            text="", perplexity=1.0, log_perplexity=0.0,
            score=0.0, label="NORMAL",
        )

    tokenizer, model, torch = _get_model()

    inputs = tokenizer(text, return_tensors="pt",
                       truncation=True, max_length=MAX_LENGTH)
    input_ids = inputs["input_ids"][0]
    n_tokens = input_ids.shape[0]

    # n <= 2 means only special tokens ([CLS], [SEP]) — nothing to score
    if n_tokens <= 2:
        return TextAnomalyResult(
            text=text, perplexity=1.0, log_perplexity=0.0,
            score=0.0, label="NORMAL",
        )

    total_log_prob = 0.0
    scored_positions = 0

    with torch.no_grad():
        for i in range(1, n_tokens - 1):  # skip [CLS] at index 0 and [SEP] at end
            masked = input_ids.clone()
            true_token_id = int(masked[i].item())
            masked[i] = tokenizer.mask_token_id
            outputs = model(input_ids=masked.unsqueeze(0))
            logits = outputs.logits[0, i]  # (vocab_size,)
            log_probs = torch.log_softmax(logits, dim=-1)
            total_log_prob += float(log_probs[true_token_id].item())
            scored_positions += 1

    avg_log_prob = total_log_prob / scored_positions
    log_perplexity = -avg_log_prob
    # Clamp perplexity to a sane max to avoid overflow on truly bizarre inputs
    log_perplexity = min(log_perplexity, 30.0)
    perplexity = math.exp(log_perplexity)

    # Normalize log_perplexity -> [0, 1] via shifted sigmoid.
    #   score=0.5 at log_perplexity == threshold
    #   score rises sharply above threshold
    z = (log_perplexity - SUSPICIOUS_THRESHOLD_LOG_PPL) * SIGMOID_SLOPE
    # sigmoid, guarded against overflow
    if z >= 0:
        score = 1.0 / (1.0 + math.exp(-z))
    else:
        e_z = math.exp(z)
        score = e_z / (1.0 + e_z)

    label = "SUSPICIOUS" if log_perplexity >= SUSPICIOUS_THRESHOLD_LOG_PPL else "NORMAL"

    return TextAnomalyResult(
        text=text,
        perplexity=perplexity,
        log_perplexity=log_perplexity,
        score=score,
        label=label,
    )


def score_merchant(merchant_name: str) -> TextAnomalyResult:
    """Public entry point: extract domain from merchant_name and score it."""
    domain = _extract_domain(merchant_name)
    return score_text(domain)


# ---------------------------------------------------------------------------
# Smoke test — battery of curated examples
# ---------------------------------------------------------------------------
def _demo() -> int:
    logger.info("=" * 82)
    logger.info("TEXT ANOMALY SCORER DEMO")
    logger.info("=" * 82)
    logger.info("Threshold log_perplexity >= {} -> SUSPICIOUS",
                SUSPICIOUS_THRESHOLD_LOG_PPL)
    logger.info("")

    # Curated test cases: normal (common), suspicious (bot / phish / gibberish)
    test_cases = [
        # Common legit domains
        "gmail.com",
        "yahoo.com",
        "hotmail.com",
        "outlook.com",
        "aol.com",
        # Missing / anonymous placeholder
        "anonymous.com",
        # Fraud-ring style patterns
        "XJ8K2-zzz9.com",
        "Q7wLm2xR3.top",
        # Typosquatting attempts
        "paypaI-secure.net",
        "verify-account-now.info",
    ]

    logger.info("{:35s} {:>12s} {:>10s} {:>8s}  {}",
                "text", "perplexity", "log_ppl", "score", "label")
    logger.info("-" * 82)

    for text in test_cases:
        r = score_text(text)
        marker = "!" if r.label == "SUSPICIOUS" else " "
        logger.info("{:35s} {:>12.2f} {:>10.4f} {:>8.4f}  {} {}",
                    r.text, r.perplexity, r.log_perplexity, r.score, r.label, marker)

    logger.info("=" * 82)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_demo())
