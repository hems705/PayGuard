import datetime
import enum

from app.database import Base
from sqlalchemy import Column, DateTime, Enum, Numeric, String, Text


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


class EntryType(str, enum.Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class Account(Base):
    __tablename__ = "accounts"

    id = Column(String, primary_key=True, index=True)  # e.g. "acc_123"
    name = Column(String, nullable=False)
    passcode_hash = Column(String, nullable=True)  # Hashed 4-6 digit passcode
    created_at = Column(
        DateTime, default=utc_now, nullable=False
    )


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id = Column(String, primary_key=True, index=True)
    account_id = Column(
        String, nullable=False, index=True
    )  # Which account this entry belongs to
    amount = Column(
        Numeric(precision=12, scale=2), nullable=False
    )  # Exact decimal precision for money
    entry_type = Column(
        Enum(EntryType), nullable=False
    )  # DEBIT (money out) or CREDIT (money in)
    reference_id = Column(
        String, nullable=False, index=True
    )  # Links the paired debit and credit entries together
    created_at = Column(
        DateTime, default=utc_now, nullable=False
    )


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    idempotency_key = Column(String, primary_key=True, index=True)
    response_data = Column(Text, nullable=True)  # Cached response for retries
    created_at = Column(
        DateTime, default=utc_now, nullable=False
    )


class PendingVoiceAction(Base):
    __tablename__ = "pending_voice_actions"

    token = Column(String, primary_key=True, index=True)
    sender_account_id = Column(String, nullable=False, index=True)
    destination_account_id = Column(String, nullable=False, index=True)
    amount = Column(Numeric(precision=12, scale=2), nullable=False)
    prompt_text = Column(Text, nullable=False)
    status = Column(String, default="PENDING", nullable=False)  # PENDING, COMPLETED, EXPIRED
    created_at = Column(DateTime, default=utc_now, nullable=False)
    expires_at = Column(DateTime, nullable=False)
