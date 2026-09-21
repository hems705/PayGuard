import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from app.models import EntryType


class AccountCreate(BaseModel):
    name: str = Field(..., min_length=1, description="Account holder name")
    id: Optional[str] = Field(None, description="Optional custom account ID (e.g. acc_123)")
    initial_balance: Optional[Decimal] = Field(Decimal("0.00"), ge=0, description="Optional initial balance")
    passcode: Optional[str] = Field(None, min_length=4, max_length=6, description="Optional 4-6 digit passcode")


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    has_passcode: bool = False
    created_at: datetime.datetime


class PasscodeSetRequest(BaseModel):
    passcode: str = Field(..., min_length=4, max_length=6, description="4-6 digit passcode")


class TransactionCreate(BaseModel):
    source_account_id: str = Field(..., description="ID of the source account (debited)")
    destination_account_id: str = Field(..., description="ID of the destination account (credited)")
    amount: Decimal = Field(..., gt=0, decimal_places=2, description="Transaction amount (must be positive)")


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    reference_id: str
    source_account_id: str
    destination_account_id: str
    amount: Decimal
    created_at: datetime.datetime


class BalanceResponse(BaseModel):
    account_id: str
    balance: Decimal
    total_credits: Decimal
    total_debits: Decimal


class LedgerEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    amount: Decimal
    entry_type: EntryType
    reference_id: str
    created_at: datetime.datetime


class VoiceCommandRequest(BaseModel):
    sender_account_id: str = Field(..., description="ID of sender account")
    command: str = Field(..., description="Natural language voice/text command e.g. 'Send 500 rs to Bob'")


class VoiceCommandResponse(BaseModel):
    action_token: str
    prompt_text: str
    recipient_name: str
    amount: Decimal
    audio_base64: Optional[str] = None
    expires_at: datetime.datetime


class VoiceConfirmRequest(BaseModel):
    action_token: str = Field(..., description="Token returned by voice command prompt")
    passcode: str = Field(..., min_length=4, max_length=6, description="User's passcode")


class VoiceConfirmResponse(BaseModel):
    status: str
    transaction_reference_id: str
    response_text: str
    audio_base64: Optional[str] = None
