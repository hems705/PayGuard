# PayGuard

PayGuard is a FastAPI-based financial ledger API with a lightweight web dashboard. It supports double-entry account transfers, balance tracking, idempotent transactions, and voice-driven payments protected by a passcode confirmation step.

## Features

- Create accounts with optional initial balances and passcodes
- Track account credits, debits, balances, and ledger entries
- Execute transfers using double-entry ledger records
- Prevent duplicate transfers with an `Idempotency-Key` header
- Parse voice-style commands such as `Send 500 rs to Rahul`
- Require a passcode before confirming voice transactions
- Enforce a ₹5,000 maximum for voice transfers
- Generate optional ElevenLabs audio prompts
- Serve a browser dashboard at `/`
- Interactive API documentation through FastAPI

## Technology

- Python 3.10+
- FastAPI
- SQLAlchemy
- SQLite by default, with optional PostgreSQL support
- Pydantic
- Uvicorn
- Pytest
- ElevenLabs Text-to-Speech API (optional)

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/hems705/PayGuard.git
cd PayGuard
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Configure environment variables (optional)

Create a `.env` file in the project root when using PostgreSQL or ElevenLabs:

```env
DATABASE_URL=sqlite:///./payguard.db
# Or PostgreSQL:
# DATABASE_URL=postgresql://username:password@localhost/payguard

ELEVENLABS_API_KEY=your_api_key
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM
```

If `DATABASE_URL` is not provided, PayGuard uses a local SQLite database named `payguard.db`. If `ELEVENLABS_API_KEY` is not provided, transactions still work but no audio response is generated.

### 5. Start the API

```bash
uvicorn app.main:app --reload
```

Open:

- Dashboard: <http://127.0.0.1:8000/>
- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc: <http://127.0.0.1:8000/redoc>
- Health check: <http://127.0.0.1:8000/health>

## API Overview

### Accounts

- `POST /accounts/` — Create an account
- `GET /accounts/{account_id}` — Retrieve an account
- `POST /accounts/{account_id}/passcode` — Set or replace a passcode
- `POST /accounts/{account_id}/deposit` — Deposit funds into an account
- `GET /accounts/{account_id}/balance` — Retrieve balance totals
- `GET /accounts/{account_id}/entries` — Retrieve ledger entries

### Transactions

- `POST /transactions/` — Transfer funds between accounts
- `GET /transactions/{reference_id}` — Retrieve entries for a transaction

For safe retries, send an `Idempotency-Key` header with `POST /transactions/`.

### Voice Payments & Queries

1. `POST /voice/command` with a sender account and natural-language command.
2. Supports actions and queries:
   - **Transfers**: `Send 500 rs to Rahul` (returns temporary action token, requires `POST /voice/confirm` with passcode)
   - **Balance Inquiries**: `Show me the current balance`, `What is my balance`
   - **Transaction Inquiries**: `Show me the last transaction I made`

## Running Tests

```bash
pytest
```

The test suite uses an in-memory SQLite database and covers account creation, balances, transfers, insufficient funds, idempotency, and the voice confirmation flow.

## Project Structure

```text
PayGuard/
├── app/
│   ├── main.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   ├── routes/
│   │   ├── accounts.py
│   │   ├── transactions.py
│   │   └── voice.py
│   ├── services/
│   │   └── elevenlabs_service.py
│   └── static/
│       └── index.html
├── tests/
├── demo.py
├── requirements.txt
└── README.md
```

## Security Note

This project is intended for development and demonstration purposes. Before production use, add proper authentication and authorization, secure secret management, stronger passcode hashing, HTTPS, rate limiting, audit logging, and production-grade database migration and transaction controls.

## License

No license has been specified yet.
