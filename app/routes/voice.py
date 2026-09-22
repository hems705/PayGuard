import datetime
import re
import uuid
from decimal import Decimal
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.routes.accounts import verify_passcode
from app.services import elevenlabs_service

router = APIRouter(prefix="/voice", tags=["Voice & Speech Actions"])


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


SCALES = {
    "hundred": 100, "thousand": 1000, "k": 1000, "lakh": 100000, "lac": 100000, "lakhs": 100000, "lacs": 100000
}


def parse_voice_command(command: str) -> Tuple[Decimal, str]:
    """
    Extracts (amount, recipient_query) supporting:
    - '4897 rs to Rahul'
    - '4 8 9 7 rupees to Rahul'
    - '4 thousand 8 hundred and 97 rs to Rahul'
    """
    if not command or not command.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Voice command is empty."
        )

    clean_cmd = command.strip().lower()

    # Step 1: Collapse space-separated single digits like "4 8 9 7" -> "4897"
    for _ in range(5):
        clean_cmd = re.sub(r"\b(\d)\s+(\d)\b", r"\1\2", clean_cmd)

    # Step 2: Extract numbers with scales like "4 thousand 8 hundred and 97"
    scale_pattern = r"(\d+)\s*(thousand|hundred|lakh|lac|lakhs|lacs|k)\b"
    total_from_scales = 0

    def scale_replacer(match):
        nonlocal total_from_scales
        num = int(match.group(1))
        scale_name = match.group(2)
        mult = SCALES.get(scale_name, 1)
        total_from_scales += num * mult
        return ""

    scaled_cmd = re.sub(scale_pattern, scale_replacer, clean_cmd)

    if total_from_scales > 0:
        rem_nums = re.findall(r"\b\d+(?:\.\d{1,2})?\b", scaled_cmd)
        if rem_nums:
            total_from_scales += int(Decimal(rem_nums[0]))
        amount = Decimal(total_from_scales)
    else:
        amount_matches = re.findall(r"\b\d+(?:\.\d{1,2})?\b", clean_cmd)
        if not amount_matches:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not find payment amount in command. E.g. 'Send 4897 to Rahul'."
            )
        amount = Decimal(amount_matches[0])

    # Step 3: Extract recipient name
    stop_words = {
        "send", "transfer", "pay", "give", "please", "can", "you", "i", "want", "would", "like",
        "to", "for", "into", "account", "account's", "acc", "rs", "rs.", "rupee", "rupees",
        "inr", "bucks", "dollars", "money", "funds", "the", "a", "an", "amount", "of", "deposit", "and"
    }

    words = clean_cmd.split()
    recipient_tokens = []

    for word in words:
        clean_word = re.sub(r"(?:'s|’s)$", "", word)
        clean_word = re.sub(r"[^\w\s]", "", clean_word)
        if clean_word and clean_word not in stop_words and not clean_word.isdigit() and clean_word not in SCALES:
            recipient_tokens.append(clean_word)

    if not recipient_tokens:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not identify recipient name in command '{command}'."
        )

    recipient_name = " ".join(recipient_tokens).strip().title()
    return amount, recipient_name




def detect_voice_intent(command: str) -> str:
    """
    Determines intent from command:
    - 'BALANCE_QUERY'
    - 'LAST_TRANSACTION'
    - 'TRANSFER'
    """
    clean_cmd = command.strip().lower()

    # Balance Query patterns
    balance_patterns = [
        r"\b(show|tell|check|get|what('s| is)?|display|view)?\s*(me\s+)?(my\s+|the\s+)?(current\s+|available\s+|account\s+)?balance\b",
        r"\bhow much (money|balance|cash|funds)\b",
        r"\bbalance inquiry\b"
    ]
    for pattern in balance_patterns:
        if re.search(pattern, clean_cmd):
            # Exclude if it looks like an explicit money transfer
            if not re.search(r"\b(send|transfer|pay|give)\b.+\b(to|for|into)\b", clean_cmd):
                return "BALANCE_QUERY"

    # Last Transaction patterns
    tx_patterns = [
        r"\b(show|tell|check|get|what('s| is| was)?|display|view)?\s*(me\s+)?(my\s+|the\s+)?(last|latest|recent|previous|past)\s+(transaction|transfer|payment|activity)\b",
        r"\blast transaction( i made)?\b",
        r"\brecent transactions?\b",
        r"\blast payment\b"
    ]
    for pattern in tx_patterns:
        if re.search(pattern, clean_cmd):
            return "LAST_TRANSACTION"

    return "TRANSFER"


@router.post("/command", response_model=schemas.VoiceCommandResponse)
def process_voice_command(
    req: schemas.VoiceCommandRequest,
    db: Session = Depends(get_db)
):
    sender = db.query(models.Account).filter(models.Account.id == req.sender_account_id).first()
    if not sender:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sender account '{req.sender_account_id}' not found."
        )

    intent = detect_voice_intent(req.command)

    # 1. BALANCE QUERY INTENT
    if intent == "BALANCE_QUERY":
        s_credits = db.query(func.coalesce(func.sum(models.LedgerEntry.amount), 0)).filter(
            models.LedgerEntry.account_id == sender.id,
            models.LedgerEntry.entry_type == models.EntryType.CREDIT
        ).scalar() or Decimal("0.00")

        s_debits = db.query(func.coalesce(func.sum(models.LedgerEntry.amount), 0)).filter(
            models.LedgerEntry.account_id == sender.id,
            models.LedgerEntry.entry_type == models.EntryType.DEBIT
        ).scalar() or Decimal("0.00")

        balance = Decimal(str(s_credits)) - Decimal(str(s_debits))
        prompt_text = f"Your current available balance is ₹{balance:,.2f}."
        audio_b64 = elevenlabs_service.generate_speech_audio(prompt_text)

        return schemas.VoiceCommandResponse(
            action_type="BALANCE_QUERY",
            prompt_text=prompt_text,
            balance=balance,
            audio_base64=audio_b64
        )

    # 2. LAST TRANSACTION INTENT
    if intent == "LAST_TRANSACTION":
        last_entry = db.query(models.LedgerEntry).filter(
            models.LedgerEntry.account_id == sender.id
        ).order_by(models.LedgerEntry.created_at.desc()).first()

        if not last_entry:
            prompt_text = "You have no past transactions recorded."
            audio_b64 = elevenlabs_service.generate_speech_audio(prompt_text)
            return schemas.VoiceCommandResponse(
                action_type="LAST_TRANSACTION",
                prompt_text=prompt_text,
                transaction_details=None,
                audio_base64=audio_b64
            )

        party_name = "Unknown"
        if last_entry.entry_type == models.EntryType.DEBIT:
            paired_entry = db.query(models.LedgerEntry).filter(
                models.LedgerEntry.reference_id == last_entry.reference_id,
                models.LedgerEntry.entry_type == models.EntryType.CREDIT
            ).first()
            if paired_entry:
                rec_acc = db.query(models.Account).filter(models.Account.id == paired_entry.account_id).first()
                if rec_acc:
                    party_name = rec_acc.name
            tx_type_str = f"transfer of ₹{last_entry.amount:,.2f} to {party_name}"
        else:
            paired_entry = db.query(models.LedgerEntry).filter(
                models.LedgerEntry.reference_id == last_entry.reference_id,
                models.LedgerEntry.entry_type == models.EntryType.DEBIT
            ).first()
            if paired_entry:
                snd_acc = db.query(models.Account).filter(models.Account.id == paired_entry.account_id).first()
                if snd_acc:
                    party_name = snd_acc.name
                tx_type_str = f"received payment of ₹{last_entry.amount:,.2f} from {party_name}"
            else:
                tx_type_str = f"credit/deposit of ₹{last_entry.amount:,.2f}"

        prompt_text = f"Your last transaction was a {tx_type_str}."
        audio_b64 = elevenlabs_service.generate_speech_audio(prompt_text)

        tx_details = {
            "reference_id": last_entry.reference_id,
            "amount": str(last_entry.amount),
            "entry_type": last_entry.entry_type.value,
            "party_name": party_name,
            "created_at": last_entry.created_at.isoformat()
        }

        return schemas.VoiceCommandResponse(
            action_type="LAST_TRANSACTION",
            prompt_text=prompt_text,
            amount=last_entry.amount,
            transaction_details=tx_details,
            audio_base64=audio_b64
        )

    # 3. TRANSFER INTENT
    # Parse Command
    amount, recipient_query = parse_voice_command(req.command)

    # Max Transaction Limit Check (₹5,000 max per transaction)
    MAX_TRANSACTION_LIMIT = Decimal("5000.00")
    if amount > MAX_TRANSACTION_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Transaction limit exceeded. Maximum voice transfer limit is ₹5,000.00 per transaction."
        )

    # Validate Sender

    sender = db.query(models.Account).filter(models.Account.id == req.sender_account_id).first()
    if not sender:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sender account '{req.sender_account_id}' not found."
        )

    if not sender.passcode_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Sender account '{sender.name}' does not have a security passcode configured."
        )

    # Find Recipient Account (by exact ID or case-insensitive name match)
    recipient = db.query(models.Account).filter(
        (models.Account.id == recipient_query) |
        (func.lower(models.Account.name) == recipient_query) |
        (models.Account.name.ilike(f"%{recipient_query}%"))
    ).first()

    if not recipient:
        new_recipient_id = f"acc_{uuid.uuid4().hex[:12]}"
        recipient = models.Account(
            id=new_recipient_id,
            name=recipient_query.title()
        )
        db.add(recipient)
        db.commit()
        db.refresh(recipient)


    if sender.id == recipient.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot send money to yourself."
        )

    # Check Sender Balance
    s_credits = db.query(func.coalesce(func.sum(models.LedgerEntry.amount), 0)).filter(
        models.LedgerEntry.account_id == sender.id,
        models.LedgerEntry.entry_type == models.EntryType.CREDIT
    ).scalar() or Decimal("0.00")

    s_debits = db.query(func.coalesce(func.sum(models.LedgerEntry.amount), 0)).filter(
        models.LedgerEntry.account_id == sender.id,
        models.LedgerEntry.entry_type == models.EntryType.DEBIT
    ).scalar() or Decimal("0.00")

    s_balance = Decimal(str(s_credits)) - Decimal(str(s_debits))
    if s_balance < amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient funds. Available: {s_balance}, Required: {amount}"
        )

    # Create Pending Voice Action Token (expires in 5 minutes)
    action_token = f"vtok_{uuid.uuid4().hex[:12]}"
    expires_at = utc_now() + datetime.timedelta(minutes=5)
    prompt_text = f"Do you want to send {amount} rupees to {recipient.name}? Please enter your passcode to confirm."

    pending_action = models.PendingVoiceAction(
        token=action_token,
        sender_account_id=sender.id,
        destination_account_id=recipient.id,
        amount=amount,
        prompt_text=prompt_text,
        status="PENDING",
        expires_at=expires_at
    )
    db.add(pending_action)
    db.commit()

    # Generate ElevenLabs Audio Prompt
    audio_b64 = elevenlabs_service.generate_speech_audio(prompt_text)

    return schemas.VoiceCommandResponse(
        action_token=action_token,
        prompt_text=prompt_text,
        recipient_name=recipient.name,
        amount=amount,
        audio_base64=audio_b64,
        expires_at=expires_at
    )


@router.post("/confirm", response_model=schemas.VoiceConfirmResponse)
def confirm_voice_command(
    req: schemas.VoiceConfirmRequest,
    db: Session = Depends(get_db)
):
    pending = db.query(models.PendingVoiceAction).filter(
        models.PendingVoiceAction.token == req.action_token
    ).first()

    if not pending or pending.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or already processed action token."
        )

    current_time = utc_now()
    expires_at = pending.expires_at
    if expires_at.tzinfo is None:
        current_time = current_time.replace(tzinfo=None)

    if expires_at < current_time:
        pending.status = "EXPIRED"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action token has expired. Please state your command again."
        )


    # Verify Passcode
    sender = db.query(models.Account).filter(models.Account.id == pending.sender_account_id).first()
    recipient = db.query(models.Account).filter(models.Account.id == pending.destination_account_id).first()

    if not sender or not verify_passcode(req.passcode, sender.passcode_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect passcode. Payment cancelled."
        )

    # Execute Double-Entry Ledger Transaction
    ref_id = f"tx_voice_{uuid.uuid4().hex[:12]}"

    debit_entry = models.LedgerEntry(
        id=f"entry_{uuid.uuid4().hex[:12]}",
        account_id=sender.id,
        amount=pending.amount,
        entry_type=models.EntryType.DEBIT,
        reference_id=ref_id
    )

    credit_entry = models.LedgerEntry(
        id=f"entry_{uuid.uuid4().hex[:12]}",
        account_id=recipient.id,
        amount=pending.amount,
        entry_type=models.EntryType.CREDIT,
        reference_id=ref_id
    )

    db.add(debit_entry)
    db.add(credit_entry)
    pending.status = "COMPLETED"
    db.commit()

    response_text = f"Payment successful! {pending.amount} rupees sent to {recipient.name}."
    audio_b64 = elevenlabs_service.generate_speech_audio(response_text)

    return schemas.VoiceConfirmResponse(
        status="SUCCESS",
        transaction_reference_id=ref_id,
        response_text=response_text,
        audio_base64=audio_b64
    )
