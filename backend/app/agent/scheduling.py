"""Calendar intent detection and LLM based meeting detail extraction."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re

import httpx


_SCHEDULE_INTENT = re.compile(
    r"\b(?:schedule|book|set up|arrange|create)\b.{0,80}\b(?:meeting|call|event|appointment)\b|"
    r"\b(?:meeting|call|appointment)\b.{0,50}\b(?:schedule|book|set up)\b", re.I)


def is_scheduling_request(message: str) -> bool:
    structured_details = (re.search(r"\bdate\s*:", message, re.I)
                          and re.search(r"\btime\s*:", message, re.I)
                          and re.search(r"\b(?:length|duration)\s*:", message, re.I))
    return bool(_SCHEDULE_INTENT.search(message) or structured_details)


def extract_meeting_details(message: str, history: list[dict[str, str]], api_key: str,
                            model: str, provider: str = "gemini") -> dict:
    """Parse a request into a safe draft; never create an event here."""
    kolkata = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
    now = datetime.now(kolkata).isoformat(timespec="minutes")
    context = "\n".join(f"{item['role']}: {item['content'][:1000]}" for item in history[-6:]
                        if item.get("role") in {"user", "assistant"})
    prompt = f"""Extract a Google Calendar meeting draft from the conversation and the latest message.
Current local date and time: {now} (Asia/Kolkata). Resolve relative dates from this timestamp.
Return JSON only with keys: summary, start, end, description, attendeeEmails, attendeeNames.
Use RFC3339 timestamps with +05:30 timezone. Never guess a date, start time, or duration.
If a start time is given without duration, use 30 minutes. If no title is given, use a concise title from context.
Only include attendeeEmails when actual email addresses were provided. Put mentioned people without an email in attendeeNames.
Conversation:
{context}
Latest message: {message}
"""
    if provider == "gemini":
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": api_key}, timeout=25,
            json={"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                  "generationConfig": {"temperature": 0, "maxOutputTokens": 400,
                                       "responseMimeType": "application/json"}})
        response.raise_for_status()
        text = "".join(part.get("text", "") for part in
                       response.json()["candidates"][0]["content"]["parts"])
    else:
        response = httpx.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"}, timeout=25,
            json={"model": model, "temperature": 0,
                  "response_format": {"type": "json_object"},
                  "messages": [{"role": "user", "content": prompt}]})
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
    details = json.loads(text)
    summary = str(details.get("summary") or "Meeting").strip()[:200]
    start = str(details.get("start") or "").strip()
    end = str(details.get("end") or "").strip()
    attendees = [str(email).strip() for email in details.get("attendeeEmails", []) if str(email).strip()]
    names = [str(name).strip() for name in details.get("attendeeNames", []) if str(name).strip()]
    if not start or not end:
        missing = "What date and start time should I use, and how long should the meeting be?"
        return {"complete": False, "question": missing}
    try:
        starts_at, ends_at = datetime.fromisoformat(start), datetime.fromisoformat(end)
        if starts_at.tzinfo is None or ends_at.tzinfo is None or ends_at <= starts_at:
            raise ValueError("invalid event interval")
    except ValueError:
        return {"complete": False, "question": "Please give me a valid date, start time, and duration for the meeting."}
    if names and not attendees:
        return {"complete": False,
                "question": f"What email address should I invite for {', '.join(names)}?"}
    return {"complete": True, "draft": {"summary": summary, "start": start, "end": end,
            "description": str(details.get("description") or "")[:4000], "attendeeEmails": attendees}}
