# Never Miss a Call — Webhook Service

Small Flask app. Twilio dials the business number → app checks working hours → rings business line during hours, SMS personal number after hours.

## How it works

1. Caller calls the **incoming number** (the Twilio number you bought).
2. Twilio sends a POST to `POST /call/<client_id>` with the caller's number.
3. App checks the client's timezone + working hours.
4. **During working hours** → app replies with TwiML that rings the business line. No SMS.
5. **Outside working hours** → app sends SMS to the personal number (caller ID + time + business line) and plays a short "we'll call you back" voice message. Business line does NOT ring.

## Files

```
never-miss-call/
├── app.py              # Flask webhook service
├── requirements.txt
├── clients/
│   └── <client_id>.yaml   # one file per client
└── README.md
```

## Setup

### 1. Install

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Get Twilio credentials

Sign up at [twilio.com](https://www.twilio.com/) and grab:

- **Account SID** — looks like `ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`
- **Auth Token** — from the dashboard

Set them as environment variables before running:

```bash
set TWILIO_ACCOUNT_SID=ACxxxxxxxx...
set TWILIO_AUTH_TOKEN=your_token_here
set PORT=5000
```

(On Linux/macOS use `export` instead of `set`.)

### 3. Add a client

Copy the sample and fill in your real numbers:

```bash
copy clients\sample-client.yaml clients\acme-corp.yaml
```

Edit `clients/acme-corp.yaml`:

| Key | What it is |
|---|---|
| `business_line` | Client's office phone number (E.164 format, e.g. `+15551234567`) |
| `personal_number` | Personal phone that gets SMS alerts (E.164) |
| `timezone` | IANA timezone, e.g. `America/New_York`, `Europe/London`, `Asia/Dubai` |
| `working_days` | List of weekdays. `0`=Monday … `6`=Sunday. Default `[0,1,2,3,4]` (Mon-Fri) |
| `working_hours_start` | 24-hour format, e.g. `09:00` |
| `working_hours_end` | 24-hour format, e.g. `18:00` |

### 4. Run

```bash
venv\Scripts\activate
python app.py
```

App listens on `http://localhost:5000`. Two routes:

- `POST /call/<client_id>` — Twilio webhook (the real handler)
- `GET /health` — check the service is running

### 5. Hook it up in Twilio

In the Twilio console, go to your phone number → **Voice & Fax** → **A call comes in**.

Set **Configure with** → `Webhook` and enter:

```
http://<your-server>/call/<client_id>
```

Pick `HTTP POST`.

If testing locally, use the [Twilio CLI](https://www.twilio.com/docs/cli) tunnel:

```bash
twilio live-bridge --port 5000
```

or ngrok:

```bash
ngrok http 5000
```

Then point Twilio at the ngrok URL.

## Test it

Send a POST to the webhook directly (without Twilio) to verify the logic:

```bash
# Simulates an inbound call from +15551112222
curl -X POST http://localhost:5000/call/sample-client \
  -d "From=+15551112222" \
  -d "To=+15559876543"
```

You should get TwiML XML back. After-hours calls will also trigger the SMS to the personal number (if Twilio credentials are set).

## Adding more clients

Just drop another `<client_id>.yaml` in `clients/`. The webhook URL is `POST /call/<client_id>` — same app serves all clients. Each client has its own numbers, timezone, and working hours.

## Production

For production use gunicorn behind a reverse proxy (nginx/Caddy) or on a platform like Render/Railway:

```bash
gunicorn app:app -b 0.0.0.0:5000 -w 2
```

Make sure `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` are set in the environment.

## SMS format

After-hours SMS looks like:

> 📞 Call from +15551112222 at 2:34 PM outside working hours. Rang your business line +15551234567. Return call?

The `from` number on the SMS is the Twilio incoming number, so replies go back to Twilio (you'd need a separate SMS webhook to handle those — not built yet).
