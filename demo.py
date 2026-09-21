import base64
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db

# Use in-memory SQLite database for instant local demo execution
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

# Create DB tables
Base.metadata.create_all(bind=engine)

client = TestClient(app)

print("=" * 60)
print("🛡️  PAYGUARD VOICE-TO-ACTION PAYMENT DEMO")
print("=" * 60)

# Step 1: Create Account for Sender (David)
print("\n1️⃣  Creating Sender Account 'David' with ₹1,000 balance & passcode '0909'...")
res_david = client.post("/accounts/", json={
    "id": "acc_david",
    "name": "David",
    "initial_balance": "1000.00",
    "passcode": "0909"
})

if res_david.status_code == 201:
    print("   ✅ Created David's Account:", res_david.json())
else:
    print("   ℹ️ David's Account status:", res_david.status_code)

# Step 2: Create Account for Recipient (Bob)
print("\n2️⃣  Creating Recipient Account 'Bob' with ₹0 balance...")
res_bob = client.post("/accounts/", json={
    "id": "acc_bob",
    "name": "Bob",
    "initial_balance": "0.00"
})
if res_bob.status_code == 201:
    print("   ✅ Created Bob's Account:", res_bob.json())
else:
    print("   ℹ️ Bob's Account status:", res_bob.status_code)

# Step 3: Voice Command Input
command = "Send 500 rs to Bob"
print(f"\n3️⃣  Processing Voice Command: \"{command}\"...")
v_res = client.post("/voice/command", json={
    "sender_account_id": "acc_david",
    "command": command
})

if v_res.status_code != 200:
    print("   ❌ Voice command failed:", v_res.json())
    exit(1)

v_data = v_res.json()
print("   🗣️  Prompt Text:", v_data["prompt_text"])
print("   🔑 Action Token Generated:", v_data["action_token"])

if v_data.get("audio_base64"):
    audio_bytes = base64.b64decode(v_data["audio_base64"])
    with open("prompt_speech.mp3", "wb") as f:
        f.write(audio_bytes)
    print("   🔊 Spoken audio prompt saved to: prompt_speech.mp3")

# Step 4: Confirm with Passcode
passcode_input = "0909"
print(f"\n4️⃣  Submitting Passcode Confirmation ('{passcode_input}')...")

c_res = client.post("/voice/confirm", json={
    "action_token": v_data["action_token"],
    "passcode": passcode_input
})

if c_res.status_code != 200:
    print("   ❌ Confirmation failed:", c_res.json())
    exit(1)

c_data = c_res.json()
print("   🎉 Payment Result:", c_data["status"])
print("   📝 Response Text:", c_data["response_text"])
print("   🧾 Transaction Reference ID:", c_data["transaction_reference_id"])

if c_data.get("audio_base64"):
    audio_bytes = base64.b64decode(c_data["audio_base64"])
    with open("confirm_speech.mp3", "wb") as f:
        f.write(audio_bytes)
    print("   🔊 Spoken confirmation audio saved to: confirm_speech.mp3")

# Step 5: Check Final Balances
print("\n5️⃣  Checking Final Ledger Balances:")
david_bal = client.get("/accounts/acc_david/balance").json()
bob_bal = client.get("/accounts/acc_bob/balance").json()

print(f"   💰 David Balance: ₹{david_bal['balance']} (Credits: ₹{david_bal['total_credits']}, Debits: ₹{david_bal['total_debits']})")
print(f"   💰 Bob Balance:   ₹{bob_bal['balance']} (Credits: ₹{bob_bal['total_credits']}, Debits: ₹{bob_bal['total_debits']})")
print("\n" + "=" * 60)
print("✅  VOICE PAYMENT DEMO COMPLETED SUCCESSFULLY")
print("=" * 60)

