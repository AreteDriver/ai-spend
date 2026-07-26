"""Ollama local inference provider for ai-spend.

Reads Claude Code transcript files to extract token usage from Ollama-backed
sessions. Ollama itself does not expose per-request token counts via API, but
Claude Code transcripts record usage blocks for every assistant response.

Cost defaults to $0 (local inference) but users can configure a custom rate
in metadata to account for electricity/depreciation.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from ai_spend.log import get_logger
from ai_spend.models import ProviderType, UsageRecord
from ai_spend.providers.base import BaseProvider
from ai_spend.providers.registry import register_provider

logger = get_logger(__name__)

# Known Ollama model name prefixes/slugs that appear in Claude Code transcripts.
_OLLAMA_MODEL_HINTS = (
    "phi4",
    "qwen2.5",
    "qwen2.5-coder",
    "llama3",
    "llama3.1",
    "llama3.3",
    "hermes3",
    "deepseek-coder",
    "codellama",
    "huihui_ai",
    "hf.co",
)

# Default paths scanned for transcripts.
_TRANSCRIPT_BASE = Path.home() / ".claude" / "projects"


def _is_ollama_model(model: str) -> bool:
    """Heuristic: does this model name look like an Ollama model?"""
    lower = model.lower()
    return any(lower.startswith(h) or h in lower for h in _OLLAMA_MODEL_HINTS)


class OllamaProvider(BaseProvider):
    """Fetch usage data from Claude Code transcripts for Ollama sessions."""

    def __init__(self, name: str, api_key: str = "") -> None:
        super().__init__(name, api_key)
        # Users can set a custom cost-per-million-tokens in metadata to account
        # for electricity / GPU depreciation. Defaults to $0.
        self._cost_per_million_input = Decimal("0.00")
        self._cost_per_million_output = Decimal("0.00")
        if api_key:
            # api_key repurposed as "cost_per_million" string: "input:output"
            # e.g. "0.50:1.50" means $0.50/1M input, $1.50/1M output
            try:
                parts = api_key.split(":")
                if len(parts) == 2:
                    self._cost_per_million_input = Decimal(parts[0])
                    self._cost_per_million_output = Decimal(parts[1])
            except Exception:
                pass

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.OLLAMA

    def fetch_usage(self, start: date, end: date) -> list[UsageRecord]:
        """Scan transcripts for Ollama model usage in the date range.

        Aggregates by (date, model) to avoid duplicate records when a session
        spans multiple transcript files.
        """
        aggregated: dict[tuple[date, str], tuple[int, int]] = defaultdict(
            lambda: (0, 0)
        )

        if not _TRANSCRIPT_BASE.exists():
            logger.warning("transcript_base_missing", extra={"extra_fields": {"path": str(_TRANSCRIPT_BASE)}})
            return []

        for jsonl_path in _TRANSCRIPT_BASE.rglob("*.jsonl"):
            # Skip sidechain / subagent transcripts
            if "subagents" in jsonl_path.parts:
                continue

            # Only consider files modified within the range (heuristic)
            mtime = date.fromtimestamp(jsonl_path.stat().st_mtime)
            if mtime < start or mtime > end:
                continue

            try:
                with jsonl_path.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        if entry.get("type") != "assistant":
                            continue

                        msg = entry.get("message", {})
                        model = msg.get("model", "")
                        if not _is_ollama_model(model):
                            continue

                        usage = msg.get("usage", {})
                        inp = usage.get("input_tokens", 0)
                        out = usage.get("output_tokens", 0)

                        # Use file mtime as the usage date (best available)
                        d = mtime
                        key = (d, model)
                        prev_inp, prev_out = aggregated[key]
                        aggregated[key] = (prev_inp + inp, prev_out + out)
            except OSError:
                continue

        records: list[UsageRecord] = []
        for (d, model), (inp, out) in aggregated.items():
            cost = (
                Decimal(inp) * self._cost_per_million_input / Decimal("1_000_000")
                + Decimal(out) * self._cost_per_million_output / Decimal("1_000_000")
            )
            records.append(
                UsageRecord(
                    provider_id=self.name,
                    provider_type=ProviderType.OLLAMA,
                    date=d,
                    model=model,
                    input_tokens=inp,
                    output_tokens=out,
                    cost_usd=cost.quantize(Decimal("0.0001")),
                    metadata={
                        "source": "transcript",
                        "cost_per_million_input": str(self._cost_per_million_input),
                        "cost_per_million_output": str(self._cost_per_million_output),
                    },
                )
            )

        logger.info(
            "ollama_sync_complete",
            extra={"extra_fields": {"records": len(records), "date_range": f"{start} to {end}"}},
        )
        return records

    def validate_credentials(self) -> bool:
        """Check that Ollama is running on localhost:11434."""
        import urllib.request

        try:
            with urllib.request.urlopen(
                "http://localhost:11434/api/tags", timeout=5
            ) as resp:
                return resp.status == 200
        except Exception:
            return False


register_provider(ProviderType.OLLAMA, OllamaProvider)
