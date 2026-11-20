"""Threadline, a fashion retail support prototype."""
import hashlib
import hmac
import os
import re
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()
app = FastAPI(title="Threadline Support")
static = Path(__file__).with_name("static")
app.mount("/static", StaticFiles(directory=static), name="static")

ORDERS = {
    "TL-1042": "Shipped. Estimated delivery in 2 business days.",
    "TL-2075": "Packed. Awaiting carrier pickup.",
}
REPLIES = {
    "returns": "Demo policy: unworn items with tags can be returned within 14 days of delivery.",
    "size": "Demo tee size guide (body chest): S 36 in, M 38 in, L 40 in, XL 42 in. "
            "Between sizes? Choose the larger size for a relaxed fit.",
    "unknown": "I can help with order tracking, returns, and tee sizing. Type “human” for support.",
}
PATTERNS = {
    "handoff": r"\b(human|agent|representative|escalate)\b|talk to (someone|support)",
    "returns": r"\b(return|returns|refund|exchange)\b",
    "tracking": r"\b(order|track|tracking|delivery|shipment|shipped)\b",
    "size": r"\b(size|sizing|fit|chest|measurements)\b",
}
ORDER_ID = re.compile(r"\bTL-\d{4}\b", re.IGNORECASE)
INTENTS = (*PATTERNS, "unknown")
META_KEYS = ("META_APP_SECRET", "META_VERIFY_TOKEN", "META_ACCESS_TOKEN",
             "META_PHONE_NUMBER_ID", "META_GRAPH_VERSION")
# Single-worker prototype. Completed message IDs are bounded and reset on restart.
completed: dict[str, None] = {}
in_flight: set[str] = set()


class Message(BaseModel):
    message: str = Field(min_length=1, max_length=1000, pattern=r"\S")


class Reply(BaseModel):
    intent: str
    reply: str
    routing: str
    handoff: str | None = None


async def respond(
    message: str, client: httpx.AsyncClient, event_id: str | None = None, sender: str | None = None
) -> Reply:
    order = ORDER_ID.search(message)
    intent = next((name for name, pattern in PATTERNS.items()
                   if re.search(pattern, message, re.IGNORECASE)), "unknown")
    if intent == "unknown" and order:
        intent = "tracking"
    routing = "rules"
    api_key = os.getenv("OPENAI_API_KEY")
    if intent == "unknown" and api_key and event_id:
        try:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                    "messages": [
                        {"role": "system", "content": "Classify the customer text. Return only one label: "
                         + ", ".join(INTENTS)},
                        {"role": "user", "content": message},
                    ],
                    "max_completion_tokens": 24,
                },
            )
            response.raise_for_status()
            label = (response.json()["choices"][0]["message"]["content"] or "").strip().lower()
            if label in INTENTS:
                intent, routing = label, "llm"
        except (httpx.HTTPError, ValueError, KeyError, IndexError, AttributeError, TypeError):
            pass

    handoff = None
    if intent == "tracking":
        if order:
            code = order[0].upper()
            reply = f"{code}: {ORDERS[code]}" if code in ORDERS else "I couldn’t find that demo order."
        else:
            reply = "Send a demo order ID such as TL-1042 or TL-2075."
    elif intent == "handoff":
        url, token = os.getenv("N8N_HANDOFF_URL"), os.getenv("N8N_HANDOFF_TOKEN")
        if not event_id:
            handoff, reply = "simulated", "This would create a support request in the live WhatsApp flow."
        elif not url or not token:
            handoff, reply = "unavailable", "Live handoff is currently unavailable."
        else:
            try:
                response = await client.post(
                    url, headers={"X-Handoff-Token": token},
                    json={"event_id": event_id, "intent": intent, "reply_to": sender},
                )
                response.raise_for_status()
                handoff, reply = "acknowledged", "The support workflow received your request."
            except httpx.HTTPError:
                handoff, reply = "unavailable", "Support handoff is temporarily unavailable. Please try again."
    else:
        reply = REPLIES[intent]
    return Reply(intent=intent, reply=reply, routing=routing, handoff=handoff)


@app.get("/", include_in_schema=False)
async def home():
    return FileResponse(static / "index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/chat", response_model=Reply)
async def demo(payload: Message):
    async with httpx.AsyncClient(timeout=8) as client:
        return await respond(payload.message, client)


def meta_config() -> dict[str, str]:
    config = {key: os.getenv(key, "") for key in META_KEYS}
    if not all(config.values()):
        raise HTTPException(503, "WhatsApp integration is disabled")
    return config


@app.get("/webhook", response_class=PlainTextResponse)
async def verify(request: Request):
    config = meta_config()
    query = request.query_params
    if (query.get("hub.mode") != "subscribe"
            or not hmac.compare_digest(query.get("hub.verify_token", "").encode(),
                                       config["META_VERIFY_TOKEN"].encode())):
        raise HTTPException(403, "Invalid verification token")
    return query.get("hub.challenge", "")


def incoming_messages(event: dict, phone_id: str):
    for entry in event.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if (change.get("field") == "messages"
                    and value.get("metadata", {}).get("phone_number_id") == phone_id):
                yield from value.get("messages", [])


@app.post("/webhook")
async def receive(request: Request):
    config = meta_config()
    raw = await request.body()
    signature = "sha256=" + hmac.new(config["META_APP_SECRET"].encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature.encode(), request.headers.get("x-hub-signature-256", "").encode()):
        raise HTTPException(403, "Invalid webhook signature")
    try:
        event = await request.json()
        messages = list(incoming_messages(event, config["META_PHONE_NUMBER_ID"]))
    except (ValueError, AttributeError, TypeError) as error:
        raise HTTPException(400, "Invalid webhook payload") from error

    async with httpx.AsyncClient(timeout=8) as client:
        for item in messages:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            event_id, sender = item.get("id"), item.get("from")
            body = item.get("text", {}).get("body", "")
            if not all(isinstance(part, str) and part.strip() for part in (event_id, sender, body)):
                continue
            if event_id in completed:
                continue
            if event_id in in_flight:
                raise HTTPException(503, "Message already processing")
            in_flight.add(event_id)
            try:
                result = await respond(body[:1000], client, event_id, sender)
                version, phone_id = config["META_GRAPH_VERSION"], config["META_PHONE_NUMBER_ID"]
                response = await client.post(
                    f"https://graph.facebook.com/{version}/{phone_id}/messages",
                    headers={"Authorization": f"Bearer {config['META_ACCESS_TOKEN']}"},
                    json={"messaging_product": "whatsapp", "to": sender, "type": "text",
                          "text": {"body": result.reply}},
                )
                response.raise_for_status()
                completed[event_id] = None
                if len(completed) > 4096:
                    del completed[next(iter(completed))]
            except httpx.HTTPError as error:
                raise HTTPException(502, "WhatsApp delivery failed") from error
            finally:
                in_flight.discard(event_id)
    return {"status": "ok"}
