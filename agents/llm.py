"""
LLM factory - tries Groq → Anthropic Claude → OpenAI in order.
Returns the first available LangChain chat model, or None if none configured.

Environment variables:
  GROQ_API_KEY       - enables llama-3.3-70b-versatile via Groq (fastest, free tier)
  ANTHROPIC_API_KEY  - enables claude-haiku-4-5 via Anthropic
  OPENAI_API_KEY     - enables gpt-4o-mini via OpenAI
"""
from __future__ import annotations

import os
from typing import Optional


def get_llm(prefer: str = "groq"):
    """
    Return the best available LangChain chat model.
    `prefer` sets provider priority: 'groq' | 'anthropic' | 'openai'
    Returns None if no API keys are set.
    """
    order = _build_order(prefer)
    for provider in order:
        llm = _try(provider)
        if llm is not None:
            return llm
    return None


def available_provider() -> str:
    """Return name of first available LLM provider, or 'none'."""
    for provider, key in [
        ("groq", "GROQ_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
    ]:
        if os.getenv(key):
            return provider
    return "none"


# ─── Internal ─────────────────────────────────────────────────────────────────

def _build_order(prefer: str) -> list[str]:
    all_providers = ["groq", "anthropic", "openai"]
    if prefer in all_providers:
        ordered = [prefer] + [p for p in all_providers if p != prefer]
    else:
        ordered = all_providers
    return ordered


def _try(provider: str):
    try:
        if provider == "groq":
            key = os.getenv("GROQ_API_KEY")
            if not key:
                return None
            from langchain_groq import ChatGroq
            return ChatGroq(
                model="llama-3.3-70b-versatile",
                temperature=0,
                max_tokens=1024,
                api_key=key,
            )

        if provider == "anthropic":
            key = os.getenv("ANTHROPIC_API_KEY")
            if not key:
                return None
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model="claude-haiku-4-5-20251001",
                temperature=0,
                max_tokens=1024,
                api_key=key,
            )

        if provider == "openai":
            key = os.getenv("OPENAI_API_KEY")
            if not key:
                return None
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model="gpt-4o-mini",
                temperature=0,
                max_tokens=1024,
                api_key=key,
            )

    except ImportError:
        pass
    except Exception:
        pass

    return None
