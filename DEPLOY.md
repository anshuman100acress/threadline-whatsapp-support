# Deploy Threadline

## 1. Publish the browser demo on Render

1. In the [Render dashboard](https://dashboard.render.com/), choose **New → Web Service** and connect the GitHub repository.
2. Select branch `main` and runtime **Python 3**. Keep Root Directory empty.
3. Set Build Command to `pip install -r requirements.txt`.
4. Set Start Command to `uvicorn app:app --host 0.0.0.0 --port $PORT`.
5. Set the health check path to `/health`. Choose an instance plan and deploy.
6. Visit the generated HTTPS URL and try **Track order** and **Human support**. Share this URL in your application once it works.

The browser demo needs no environment variables. Render's free web service can sleep during inactivity, so open the demo before your interview. [Render FastAPI setup](https://render.com/docs/deploy-fastapi) · [Render free plan](https://render.com/docs/free)

## 2. Connect a WhatsApp test number

1. Set up a Meta developer app with WhatsApp and use the test number in **WhatsApp → API Setup**. Add your own phone as a test recipient.
2. In Render, add `META_APP_SECRET` from the Meta app settings, `META_ACCESS_TOKEN` and `META_PHONE_NUMBER_ID` from WhatsApp API setup, and `META_GRAPH_VERSION` from the API request shown there (for example, a value shaped like `vNN.0`). Create a random `META_VERIFY_TOKEN` using `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
3. Redeploy and configure Meta's WhatsApp webhook callback as `https://YOUR-SERVICE.onrender.com/webhook`. Enter the same verify token and subscribe to the `messages` field. Make sure the app is subscribed to the test WhatsApp Business Account.
4. Send `Track TL-1042` from the approved phone to the test number. Use the Meta dashboard to check webhook delivery if no reply arrives. Renew the temporary token if it expires.

For local setup, copy `.env.example` to `.env` and set the same values. Meta needs a publicly reachable HTTPS callback. [Meta WhatsApp Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api/)

## 3. Enable Meta Model API (optional)

1. In the [Meta developer console](https://dev.meta.ai/), select the project that has your Meta Model API credits and create an API key for that project.
2. Set `META_MODEL_API_KEY` in Render (or your local `.env`). The default model is `muse-spark-1.3`. Set `META_MODEL` if you want to use another supported reasoning model available to your project.
3. If you previously configured `OPENAI_API_KEY` or `OPENAI_MODEL`, remove them from your environment. Redeploy and send “I changed my mind after buying it” from your WhatsApp test phone to exercise model routing.

The model key is separate from the WhatsApp Cloud API token. The browser demo uses rules only. On WhatsApp, only unmatched text goes to Meta Model API, so use sample messages for this demo. Check the project's billing console to confirm available credits and usage. [Meta chat completions quickstart](https://dev.meta.ai/docs/cookbook/quickstart-chat-completions)

## 4. Enable n8n handoff (optional)

1. Import `n8n/threadline-handoff.json` into n8n.
2. In **Receive handoff**, create a **Header Auth** credential. Use `X-Handoff-Token` for the header name and a fresh random secret for the value.
3. Save and publish or activate the workflow. Copy its **Production URL**.
4. Set `N8N_HANDOFF_URL` to that HTTPS URL and `N8N_HANDOFF_TOKEN` to the same secret in Render. Redeploy.
5. Send `human` on WhatsApp. Open the successful n8n execution to see the request. Restrict access to the workflow and execution history, which contains the test recipient's phone number.

The workflow uses execution history as its prototype queue. The app keeps recent WhatsApp message IDs in memory for one worker. Retries after a restart or after a downstream failure can repeat delivery or handoffs. Use a persistent queue and idempotent support records before enabling real traffic. [n8n Webhook node](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/)
