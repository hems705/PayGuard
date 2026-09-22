from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


from app.main import app
from app.database import Base, get_db
from app import models

# Use in-memory SQLite for testing
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


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_account():
    # Account without initial balance
    response = client.post("/accounts/", json={"name": "Alice", "id": "acc_alice"})
    assert response.status_code == 201
    data = response.json()
    assert data["id"] == "acc_alice"
    assert data["name"] == "Alice"

    # Account with initial balance
    response_bob = client.post("/accounts/", json={"name": "Bob", "id": "acc_bob", "initial_balance": "500.00"})
    assert response_bob.status_code == 201
    assert response_bob.json()["id"] == "acc_bob"

    # Check Bob's balance
    bal_res = client.get("/accounts/acc_bob/balance")
    assert bal_res.status_code == 200
    assert bal_res.json()["balance"] == "500.0" or float(bal_res.json()["balance"]) == 500.00


def test_account_deposit_increases_balance():
    client.post("/accounts/", json={"name": "Saver", "id": "acc_saver", "initial_balance": "100.00"})

    deposit_res = client.post(
        "/accounts/acc_saver/deposit",
        json={"amount": "250.00"}
    )
    assert deposit_res.status_code == 200
    assert float(deposit_res.json()["amount"]) == 250.00

    bal_res = client.get("/accounts/acc_saver/balance")
    assert float(bal_res.json()["balance"]) == 350.00


def test_transaction_success():
    # Create 2 accounts
    client.post("/accounts/", json={"name": "Sender", "id": "acc_sender", "initial_balance": "1000.00"})
    client.post("/accounts/", json={"name": "Receiver", "id": "acc_receiver", "initial_balance": "100.00"})

    # Transfer 250.00 from Sender to Receiver
    tx_res = client.post(
        "/transactions/",
        json={
            "source_account_id": "acc_sender",
            "destination_account_id": "acc_receiver",
            "amount": "250.00"
        }
    )
    assert tx_res.status_code == 201
    tx_data = tx_res.json()
    assert tx_data["source_account_id"] == "acc_sender"
    assert tx_data["destination_account_id"] == "acc_receiver"
    assert float(tx_data["amount"]) == 250.00
    ref_id = tx_data["reference_id"]

    # Verify updated balances
    sender_bal = client.get("/accounts/acc_sender/balance").json()
    assert float(sender_bal["balance"]) == 750.00

    receiver_bal = client.get("/accounts/acc_receiver/balance").json()
    assert float(receiver_bal["balance"]) == 350.00

    # Retrieve transaction entries
    entries_res = client.get(f"/transactions/{ref_id}")
    assert entries_res.status_code == 200
    entries = entries_res.json()
    assert len(entries) == 2


def test_transaction_insufficient_funds():
    client.post("/accounts/", json={"name": "Poor User", "id": "acc_poor", "initial_balance": "50.00"})
    client.post("/accounts/", json={"name": "Rich User", "id": "acc_rich", "initial_balance": "1000.00"})

    # Attempt to transfer 100 from acc_poor
    tx_res = client.post(
        "/transactions/",
        json={
            "source_account_id": "acc_poor",
            "destination_account_id": "acc_rich",
            "amount": "100.00"
        }
    )
    assert tx_res.status_code == 400
    assert "Insufficient funds" in tx_res.json()["detail"]


def test_transaction_idempotency():
    client.post("/accounts/", json={"name": "User A", "id": "acc_a", "initial_balance": "500.00"})
    client.post("/accounts/", json={"name": "User B", "id": "acc_b", "initial_balance": "0.00"})

    headers = {"Idempotency-Key": "idemp_test_key_123"}
    tx_payload = {
        "source_account_id": "acc_a",
        "destination_account_id": "acc_b",
        "amount": "150.00"
    }

    # First attempt
    res1 = client.post("/transactions/", json=tx_payload, headers=headers)
    assert res1.status_code == 201
    data1 = res1.json()

    # Second attempt with SAME Idempotency-Key
    res2 = client.post("/transactions/", json=tx_payload, headers=headers)
    assert res2.status_code == 201
    data2 = res2.json()

    # Must be identical responses
    assert data1["reference_id"] == data2["reference_id"]

    # Balance of User A must be reduced ONCE (500 - 150 = 350, NOT 200)
    bal_a = client.get("/accounts/acc_a/balance").json()
    assert float(bal_a["balance"]) == 350.00


def test_voice_command_and_passcode_flow():
    # 1. Create Sender with initial balance 1000 and passcode 1234
    client.post("/accounts/", json={
        "name": "Account Balance",
        "id": "acc_main",
        "initial_balance": "1000.00",
        "passcode": "1234"
    })

    # 2. Create Recipient Bob
    client.post("/accounts/", json={
        "name": "Bob",
        "id": "acc_bob",
        "initial_balance": "0.00"
    })

    # 3. Voice Command: "Send 500 rs to Bob"
    voice_res = client.post("/voice/command", json={
        "sender_account_id": "acc_main",
        "command": "Send 500 rs to Bob"
    })
    assert voice_res.status_code == 200
    v_data = voice_res.json()
    assert v_data["recipient_name"] == "Bob"
    assert float(v_data["amount"]) == 500.00
    action_token = v_data["action_token"]
    assert "Do you want to send 500 rupees to Bob?" in v_data["prompt_text"]

    # 4. Confirm with WRONG passcode
    wrong_confirm = client.post("/voice/confirm", json={
        "action_token": action_token,
        "passcode": "0000"
    })
    assert wrong_confirm.status_code == 401

    # 5. Confirm with CORRECT passcode
    right_confirm = client.post("/voice/confirm", json={
        "action_token": action_token,
        "passcode": "1234"
    })
    assert right_confirm.status_code == 200
    confirm_data = right_confirm.json()
    assert confirm_data["status"] == "SUCCESS"

    # 6. Verify balances
    david_bal = client.get("/accounts/acc_main/balance").json()
    assert float(david_bal["balance"]) == 500.00

    bob_bal = client.get("/accounts/acc_bob/balance").json()
    assert float(bob_bal["balance"]) == 500.00


def test_auto_create_recipient_voice_command():
    client.post("/accounts/", json={
        "name": "Sender User",
        "id": "acc_sender_auto",
        "initial_balance": "1000.00",
        "passcode": "1234"
    })

    # Voice Command to non-existent account "Rahul"
    v_res = client.post("/voice/command", json={
        "sender_account_id": "acc_sender_auto",
        "command": "Send 300 rs to Rahul"
    })
    assert v_res.status_code == 200
    v_data = v_res.json()
    assert v_data["recipient_name"] == "Rahul"

    # Confirm payment
    c_res = client.post("/voice/confirm", json={
        "action_token": v_data["action_token"],
        "passcode": "1234"
    })
    assert c_res.status_code == 200
    assert c_res.json()["status"] == "SUCCESS"


def test_flexible_voice_command_phrasings():
    client.post("/accounts/", json={
        "name": "Flexible Sender",
        "id": "acc_flex_sender",
        "initial_balance": "5000.00",
        "passcode": "1234"
    })

    phrasings = [
        ("Can you transfer 500 rupees to Rahul please", "Rahul", 500.00),
        ("Give 250 bucks for Sam", "Sam", 250.00),
        ("100 to Alex", "Alex", 100.00),
        ("Deposit 750 INR into Priya's account", "Priya", 750.00)
    ]

    for cmd_str, expected_recipient, expected_amount in phrasings:
        res = client.post("/voice/command", json={
            "sender_account_id": "acc_flex_sender",
            "command": cmd_str
        })
        assert res.status_code == 200
        data = res.json()
        assert data["recipient_name"] == expected_recipient
        assert float(data["amount"]) == expected_amount


def test_max_transaction_limit_exceeded():
    client.post("/accounts/", json={
        "name": "Limit User",
        "id": "acc_limit_user",
        "initial_balance": "10000.00",
        "passcode": "1234"
    })

    # Attempt to transfer 6,000 (exceeds 5,000 limit)
    res = client.post("/voice/command", json={
        "sender_account_id": "acc_limit_user",
        "command": "Send 6000 rs to Bob"
    })
    assert res.status_code == 400
    assert "Transaction limit exceeded" in res.json()["detail"]


def test_voice_command_nil_balance():
    client.post("/accounts/", json={
        "name": "Zero Balance User",
        "id": "acc_zero_bal",
        "initial_balance": "0.00",
        "passcode": "1234"
    })

    # Attempt voice transfer with 0 balance
    res = client.post("/voice/command", json={
        "sender_account_id": "acc_zero_bal",
        "command": "Send 500 rs to Bob"
    })
    assert res.status_code == 400
    assert "Insufficient funds" in res.json()["detail"]


def test_voice_command_balance_query():
    client.post("/accounts/", json={
        "name": "Balance Checker",
        "id": "acc_bal_checker",
        "initial_balance": "1000000.00",
        "passcode": "1234"
    })

    # Test "show me the current balance"
    res1 = client.post("/voice/command", json={
        "sender_account_id": "acc_bal_checker",
        "command": "show me the current balance"
    })
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["action_type"] == "BALANCE_QUERY"
    assert float(data1["balance"]) == 1000000.00
    assert "1,000,000.00" in data1["prompt_text"]

    # Test "what is my balance"
    res2 = client.post("/voice/command", json={
        "sender_account_id": "acc_bal_checker",
        "command": "what is my balance"
    })
    assert res2.status_code == 200
    assert res2.json()["action_type"] == "BALANCE_QUERY"


def test_voice_command_last_transaction():
    # 1. User with no prior transactions
    client.post("/accounts/", json={
        "name": "New User",
        "id": "acc_new_tx",
        "passcode": "1234"
    })
    no_tx_res = client.post("/voice/command", json={
        "sender_account_id": "acc_new_tx",
        "command": "show me the last transaction i made"
    })
    assert no_tx_res.status_code == 200
    assert no_tx_res.json()["action_type"] == "LAST_TRANSACTION"
    assert "no past transactions" in no_tx_res.json()["prompt_text"]

    # 2. Add deposit / transaction and verify last transaction
    client.post("/accounts/acc_new_tx/deposit", json={"amount": "750.00"})
    tx_res = client.post("/voice/command", json={
        "sender_account_id": "acc_new_tx",
        "command": "show me the last transaction i made"
    })
    assert tx_res.status_code == 200
    tx_data = tx_res.json()
    assert tx_data["action_type"] == "LAST_TRANSACTION"
    assert float(tx_data["amount"]) == 750.00
    assert "750.00" in tx_data["prompt_text"]





