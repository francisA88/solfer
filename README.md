# Solfer

**Tonic solfa notation editor with audio playback and MP3 export.**

> 🔗 **Live app:** _https://solfer.wasmer.app_

Solfer is a web-based music tool that lets musicians type bits of compositions in tonic solfa notation using a dedicated on-screen keyboard, hear each note as it is entered, and export the result as a WAV/MP3 (MP3 to be added in later versions) audio file. It supports all 12 keys, four vocal parts (SATB), three time signatures, and full subdivision (quarter, eighth, sixteenth notes) with sustain and rest notation. Triplet notation is not yet supported.

---

## Features

- **On-screen solfa keyboard** — all 12 chromatic notes (d, de, r, me, m, f, fe, s, si, l, ta, t) with octave modifiers and subdivision controls
- **Real-time audio feedback** — each note plays through the browser via Tone.js the moment it is entered
- **Correct pitch resolution** — `d` is always the tonic reference floor; all other scale degrees sit strictly above it regardless of key
- **Measure validation** — beat length and subdivision rules are enforced before a measure can be committed
- **Measure playback** — individual measures can be played back with correct sustain merging and rest handling
- **WAV export** — server-side audio generation via NumPy/wave (no external audio codec required for WAV)
- **User accounts** — email/password registration
- **Payment-gated export** — audio export is available to paid users only; one-time payment via Flutterwave (card and bank transfer)
- **Persistent compositions** — measures are saved to the database per user and restored on next login
- **Password reset** — HMAC-signed token flow with email delivery via SMTP
- **Rate limiting** — brute-force protection on auth endpoints via Flask-Limiter + in-memory storage (to be relaced with Redis later)

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Vanilla JS, HTML5, CSS3 |
| Audio (browser) | Tone.js 14.7 |
| Audio (server) | Python `wave` + NumPy |
| Backend | Flask 3.x |
| Database | PostgreSQL |
| ORM | Flask-SQLAlchemy 3.x |
| Auth | Flask-Login, Werkzeug password hashing |
| Payments | Flutterwave (inline JS + custom transfer polling) |
| Background jobs | APScheduler (in-process, transfer payment polling) |
| Rate limiting | Flask-Limiter + Redis |
| Email | Python `smtplib` (STARTTLS) |
| Session security | Flask-WTF CSRF tokens |

---

## Project structure

```
solfer_project/
├── core/
│   ├── db_api.py                         # Database helper functions
│   ├── flutterwave_services.py           # Flutterwave API client functions
│   ├── helpers.py                        # Shared helper functions
│   ├── mailer.py                         # Email utilities (reset, receipt)
│   ├── measure_to_audio.py               # Server-side WAV generator
│   └── models.py                         # SQLAlchemy models (User, Measure)
├── ui/
│   ├── static/
│   │   ├── img/
│   │   │   └── logo.png
│   │   ├── scripts/
│   │   │   ├── auth.js                   # Auth helpers
│   │   │   ├── helpers.js                # JS helpers. Pretty much just csrfToken stuff for now
│   │   │   ├── main.js                   # Editor logic, notation parser, playback
│   │   │   ├── payment.js                # Payment page logic
│   │   │   └── Tone.min.js               # Tone.js audio engine (served locally)
│   │   └── styles/
│   │       ├── auth.css
│   │       ├── forgot_password.css
│   │       └── main.css
│   └── templates/
│       ├── auth.html                     # Login / signup page
│       ├── forgot_password.html
│       ├── index.html                    # Main editor page
│       ├── payment.html                  # Payment page (card + transfer)
│       ├── reset_password.html
│       └── thank_you.html                # Payment confirmation page
├── .env                                  # Local secrets (not committed. Alright then...keep your secrets)
├── .gitignore
├── app.py                                # Flask application factory + all routes
├── pyproject.toml
├── README.md
└── requirements.txt
```
---

## Notation format

Solfer uses a compact string format to represent music:

```
d:m:s:d'            → four quarter notes (do, mi, sol, do-above)
d.m:s:d:-           → eighth-d + eighth-m as one beat, quarter-s, quarter-d sustained
d,de.r:m            → sixteenth-d + sixteenth-de as first eighth, eighth-r, quarter-m
```

**Rules:**
- `:` separates beats. The number of beats must match the time signature numerator.
- `.` splits a beat into two eighths.
- `,` splits an eighth into two sixteenths.
- `-` sustains the previous note for one beat (or one subdivision slot).
- A space ` ` is a rest.
- Octave up: append `'` to a note (e.g. `d'`).
- Octave down: append `₁` or `₂` (e.g. `d₁`).

---

## Environment variables reference

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | ✓ | Flask session signing key — use a long random string in production |
| `DATABASE_URL` | ✓ | SQLite (`sqlite:///solfer.db`) or PostgreSQL (`postgresql://...`) |
| `FLASK_ENV` | | Set to `production` on your server |
| `SMTP_HOST` | ✓ | SMTP server hostname (e.g. `smtp.gmail.com`) |
| `SMTP_PORT` | ✓ | SMTP port (587 for STARTTLS) |
| `SMTP_USER` | ✓ | SMTP login username (your sending address) |
| `SMTP_KEY` | ✓ | SMTP API key or app password |
| `SMTP_CUST_SERVICE_MAIL` | ✓ | Address shown in the `From` field of outgoing emails |
| `GOOGLE_CLIENT_ID` | | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | | Google OAuth client secret |
| `FLW_PUBLIC_KEY` | | Flutterwave public key |
| `FLW_SECRET_KEY` | | Flutterwave secret key |
| `PAYMENT_AMOUNT` | | Payment amount (numeric, e.g. `5.00`) |
| `PAYMENT_CURRENCY` | | Currency code (e.g. `NGN`, `USD`) |
| `ACCESS_DURATION_DAYS` | | Days of access granted per payment (default `14`) |

---

## Migrating from SQLite to PostgreSQL

When ready for production, switch the database without losing data:

**1.** Install pgloader:
```bash
sudo apt install pgloader        # Ubuntu
brew install pgloader            # macOS
```

**2.** Run the migration:
```bash
pgloader sqlite:///solfer.db postgresql://user:password@host:5432/solfer
```

**3.** Update `.env`:
```
DATABASE_URL=postgresql://user:password@host:5432/solfer
```

**4.** Restart Flask. All users, measures, and payment records transfer intact.

---

## Payment flow

**Bank transfer:** The frontend calls `/payment/transfer/generate` which creates a virtual account via Flutterwave. An APScheduler job then polls Flutterwave every 15 seconds server-side. The frontend simultaneously polls `/payment/status/<tx_ref>` every 8 seconds and redirects automatically when the server confirms the transfer.

Access is time-limited (see `ACCESS_DURATION_DAYS`). Users must return to the payment page to renew.

---

## Audio export

WAV export is handled entirely server-side by `measure_to_audio.py` using Python's built-in `wave` module and NumPy. No FFmpeg or external codec is required for WAV output.

The export endpoint (`POST /convert-audio`) receives the full composition as a JSON string, generates a WAV file in a temporary directory, streams it back to the browser, and deletes the temp file. Export is only available to users with active paid access.

---

## Security notes

- All passwords are hashed with Werkzeug's `generate_password_hash` (PBKDF2-SHA256).
- Password reset tokens are HMAC-SHA256 signed and expire after 1 hour.
- CSRF tokens (Flask-WTF) are required on all state-changing requests.
- Rate limiting is applied to authentication and password reset endpoints via Flask-Limiter + Redis.
- Session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` in production.

---

## License

Copyright © 2025. All rights reserved. Unauthorised copying, distribution, or use of this software is strictly prohibited.
