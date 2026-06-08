"""Google ADK entry point for the travel savings agent.

Run with:
  adk web

The ADK agent intentionally reuses the deterministic pipeline in this project:
- live scraping/API calls
- source status and de-duplication
- card knowledge base and effective-cost math
- verified Markdown tables

The LLM should explain and decide; it should not invent prices or card savings.
"""
from __future__ import annotations

import os

from google.adk import Agent

from adk_travel_agent.tools import (
    analyze_card_savings,
    run_complete_trip_analysis,
    search_flights,
    search_hotels,
)


root_agent = Agent(
    name="travel_savings_agent",
    model=os.getenv("GOOGLE_ADK_MODEL", "gemini-flash-latest"),
    instruction=(
        "You are an effective travel savings agent. Keep the workflow simple: "
        "collect trip details, call the tools for real prices and deterministic card math, "
        "then explain the best booking path clearly. Never invent prices, card benefits, "
        "hotel availability, or source status. If a source returns zero or fails, say so. "
        "Use run_complete_trip_analysis when the user provides a full trip. Use individual "
        "search tools only when the user asks for partial checks."
    ),
    tools=[
        run_complete_trip_analysis,
        search_flights,
        search_hotels,
        analyze_card_savings,
    ],
)
