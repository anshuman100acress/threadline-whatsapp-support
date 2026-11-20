# Threadline WhatsApp Support

A fashion retail support prototype for a software developer application to Stylox Fashion. The browser demo uses fictional orders and policies and runs without credentials.

## Run locally

Requires Python 3.11 or later.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload
```

Open http://127.0.0.1:8000 for the chat or http://127.0.0.1:8000/docs for the REST API.

| Try this message | Expected result |
| --- | --- |
| `Track TL-1042` | Shipped, with a demo delivery estimate |
| `Track TL-9999` | Order not found |
| `What is your return policy?` | Sample 14-day return policy |
| `What tee size should I get?` | Demo size chart |
| `Can I speak to a human?` | Simulated support handoff in the browser |
| `Tell me a joke` | Supported topics |

```bash
curl -s http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Track TL-1042"}'
python -m unittest discover -s tests -v
```

## How it works

- Browser → FastAPI → rule routing → a reply from sample order and policy data. The anonymous browser endpoint makes no paid calls and creates no support cases.
- WhatsApp → Meta Cloud API webhook → verification and signature validation → the same support logic → Graph API reply.
- For signed WhatsApp events, Meta’s optional Muse Spark integration classifies messages the rules cannot match. The model returns a permitted intent label. The Python code chooses the reply from known data, and it can answer with the supported topics if model routing is unavailable.
- Live handoff → authenticated n8n webhook → a support-request record in n8n execution history. Staff can see the message ID and callback number, subject to n8n retention. The prototype sends no staff notification.

See [deployment and integration setup](DEPLOY.md) for Render, WhatsApp Cloud API, Meta Model API, and n8n.

## What to show in the interview

1. Track `TL-1042` and `TL-9999` to show that lookup results come from known records.
2. Try returns, tee sizing, and human handoff. Use `/docs` to show the REST contract and response fields.
3. With live integrations configured, send “I changed my mind after buying it” from an approved WhatsApp test phone to demonstrate optional model classification. Send “human” and show the resulting n8n execution.
4. Explain the next production changes. Connect authenticated order lookup, replace in-memory deduplication with durable processing, and route handoffs to an agent inbox.

Sample project description for a résumé or portfolio:

> Built a Python/FastAPI fashion-support chatbot prototype with a browser demo, Meta WhatsApp webhook integration, optional LLM intent routing, and an n8n human handoff workflow.
