# Never Miss a Call — Deployment Guide

## Architecture

```
Netlify (static)                          Render (Flask + SQLite + SignalWire)
────────────────                          ─────────────────────────────────────
index.html  ──────── HTTPS ──────────→   app.py  (port 5000, gunicorn)
  JS API calls                           /api/*         — account, billing,
                                                   config, number provisioning
                                                   /call/<user_id> — SignalWire webhook
```

- **Netlify**: hosts the static `index.html` + JS. Free tier.
- **Render**: hosts the Flask backend with SQLite. Free tier (web service).
- **SignalWire**: sits behind the Render backend — bought/managed via SignalWire API from the backend. SignalWire supports Pakistan numbers and international numbers.

---

## Step 1: Deploy the backend to Render

1. Push the repo to GitHub.
2. Go to [render.com](https://render.com/) → New → Web Service.
3. Connect your repo.
4. Set these as **Environment Variables** in the Render dashboard:

   | Variable | Value |
   |---|---|
   | `SIGNALWIRE_SPACE` | Your SignalWire Space URL, e.g. `https://your-space.signalwire.com` |
   | `SIGNALWIRE_PROJECT_ID` | Your SignalWire Project ID |
   | `SIGNALWIRE_API_TOKEN` | Your SignalWire API Token (create one in the SignalWire dashboard) |
   | `SIGNALWIRE_AREA_CODE` | Preferred area code, e.g. `212` (for US numbers). Omit for any available number. |
   | `SECRET_KEY` | A random string (generate with `python -c "import secrets; print(secrets.token_hex(32))"`) |
   | `SERVER_URL` | Your Render app URL (e.g. `https://your-app.onrender.com`) |

5. Render auto-detects the `Procfile` and `requirements.txt`. Use Python 3.11+ runtime.
6. Deploy. On the free tier it spins down after 15 min of inactivity — first request after spin-down takes ~30s.

---

## Step 2: Deploy the frontend to Netlify

1. Go to [netlify.com](https://netlify.com/) → New site from Git (or drag-and-drop the `netlify/public/` folder).
2. Build command: leave empty (static site, no build step).
3. Publish directory: `public` (or `netlify/public/` if deploying the whole repo).
4. Once deployed, copy the Netlify URL.

---

## Step 3: Point the frontend at the backend

In `netlify/public/index.html`, find this line near the top of the `<script>` block:

```js
const API = 'https://your-app.onrender.com';  // ← change to your Render URL
```

Replace `https://your-app.onrender.com` with your actual Render app URL. Then redeploy Netlify.

---

## Step 4: Connect SignalWire numbers to the webhook

For each user who provisions a number, the backend sets the `voice_url` on that SignalWire number automatically:

```python
num.update(voice_url=f'{SERVER_URL}/call/{user_id}')
```

This means: when someone calls that SignalWire number, SignalWire POSTs to `/call/<user_id>` on your Render backend, which handles the working-hours check and routing.

**No manual SignalWire dashboard work needed per user** — the backend does it.

---

## Step 5: Test locally (before deploying)

```bash
cd render-backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# Set env vars
set SIGNALWIRE_SPACE=https://your-space.signalwire.com
set SIGNALWIRE_PROJECT_ID=your_project_id
set SIGNALWIRE_API_TOKEN=your_api_token
set SIGNALWIRE_AREA_CODE=212
set SECRET_KEY=dev-secret
set SERVER_URL=http://localhost:5000

python app.py
```

Then in another terminal:

```bash
cd netlify
python -m http.server 8080 -d public
```

Open `http://localhost:8080` — sign up, pay (fake), configure, and verify the flow.

---

## Environment variables summary

| Variable | Where | Required |
|---|---|---|
| `SIGNALWIRE_SPACE` | Render | Yes |
| `SIGNALWIRE_PROJECT_ID` | Render | Yes |
| `SIGNALWIRE_API_TOKEN` | Render | Yes |
| `SIGNALWIRE_AREA_CODE` | Render | No (any available number if omitted) |
| `SECRET_KEY` | Render | Yes (session signing) |
| `SERVER_URL` | Render | Yes (used to set SignalWire voice_url) |
| `API` (in index.html) | Netlify | Yes (points front-end to back-end) |

---

## SignalWire setup (quick)

1. Sign up at [signalwire.com](https://signalwire.com/)
2. Create a Space — your tenant is `https://<space>.signalwire.com`
3. Go to **API Keys** — create a Project + API Token
4. The Space URL goes in `SIGNALWIRE_SPACE`, the Project ID in `SIGNALWIRE_PROJECT_ID`, the Token in `SIGNALWIRE_API_TOKEN`

---

## Free-tier notes

- **Render free tier**: web service spins down after 15 min of inactivity. First request wakes it up (~30s cold start). For a 5-client service this is fine.
- **SQLite on Render**: the filesystem is ephemeral on the free tier — app.db persists between requests but is lost on deploy/redeploy. For a few clients this is fine. For persistence across deploys, use Render's PostgreSQL addon instead.

---

## Future improvements (when you scale past 5 clients)

- Replace SQLite with PostgreSQL (Render has a free tier).
- Replace fake Stripe with real Stripe (Stripe Checkout for payment, webhook for subscription status).
- Replace session-based auth with a JWT or a proper session store that survives redeploy.
- Add a real SignalWire SMS webhook (`/sms/<user_id>`) to handle replies from customers.
- Add call logging to the dashboard.
