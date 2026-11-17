# Ubuntu Line

SMS AI for feature phones, built with Flask, Twilio-compatible SMS webhooks, SQLite, and the Google Gemini API. Canned commands work without an LLM key; free-form questions are cached by language and normalized text.

## Setup

Requires Python 3.10+ and a Gemini API key (free from aistudio.google.com) for AI answers.

```bash
python -m venv .venv
source .venv/bin/activate
pip install Flask
cp .env.example .env   # then paste your Gemini key into .env
python app.py
```

Open `http://127.0.0.1:5000` for the phone simulator and live usage log. SQLite data is stored in `ubuntu_line.db` beside `app.py`; set `DB_PATH` to change it. The model defaults to `gemini-3.5-flash-lite` and can be overridden with `LLM_MODEL`.

## Test the six SMS scenarios

```bash
python simulate.py
```

The simulator uses a temporary database and checks first-contact language selection, HELP, the SRD appeal flow, job-ad scam flags, an AI/fallback question, and a repeated cached question with zero tokens.

## Twilio and ngrok

1. Start the Flask server: `python app.py`.
2. In another terminal, expose it: `ngrok http 5000`.
3. In the Twilio phone number's **Messaging** configuration, set **A message comes in** to `https://YOUR-NGROK-DOMAIN/incoming` with method **HTTP POST**.
4. Send an SMS to the Twilio number. The `/incoming` route reads Twilio's `From` and `Body` fields and returns TwiML.

`POST /sim` accepts JSON `{ "phone": "+27...", "body": "..." }` or form fields `phone` and `body`, and returns `{ "reply": "..." }`. `GET /log` returns recent exchanges and token/zero-token totals for the dashboard.

## Real phone number (SA SIM via Android phone)

**Quick way:** fill in `.env`, then run `powershell -ExecutionPolicy Bypass -File setup_gateway.ps1 -TestNumber +27XXXXXXXXX`. It runs the tests, starts the app and ngrok, and registers the webhook. Manual steps below.

Uses the free **SMS Gateway for Android** app (sms-gate.app) so any normal South African SIM becomes the Ubuntu Line number.

1. Install the app on a spare Android phone with an SA SIM (with SMS bundle). Turn on **Cloud Server**; copy the username/password from the Home tab into `.env` as `SMSGATE_USER` / `SMSGATE_PASS`.
2. Run `python app.py` and `ngrok http 5000` (webhooks must be HTTPS).
3. Register the webhook once:
```bash
curl -X POST -u USER:PASS -H "Content-Type: application/json" \
  -d '{"url":"https://YOUR-NGROK-DOMAIN/sms-gate","event":"sms:received"}' \
  https://api.sms-gate.app/3rdparty/v1/webhooks
```
4. SMS that phone's number from any phone. The reply comes back as a normal SMS.

## Africa's Talking (sandbox or live shortcode)

1. In `.env` set `AT_USERNAME` (`sandbox` for testing), `AT_API_KEY`, and `AT_SHORTCODE` (your 2-way shortcode).
2. Run `python app.py` and `ngrok http 5000`.
3. In the Africa's Talking dashboard, set the SMS **Inbox callback URL** to `https://YOUR-NGROK-DOMAIN/at-sms`.
4. Sandbox: create a free shortcode, open the simulator, and SMS it. Live: SMS the shortcode from any phone.
