import json
import uuid
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/transactions", tags=["Transactions"])


@router.post("/", response_model=schemas.TransactionResponse, status_code=status.HTTP_201_CREATED)
def create_transaction(
    transaction_in: schemas.TransactionCreate,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db)
):
    # Check Idempotency Key
    if idempotency_key:
        existing_key = db.query(models.IdempotencyKey).filter(
            models.IdempotencyKey.idempotency_key == idempotency_key
        ).first()
        if existing_key and existing_key.response_data:
            cached_data = json.loads(existing_key.response_data)
            return cached_data

    # Validation: Source & Destination must differ
    if transaction_in.source_account_id == transaction_in.destination_account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source and destination accounts must be different."
        )

    # Validate accounts exist
    source_acc = db.query(models.Account).filter(
        models.Account.id == transaction_in.source_account_id
    ).first()
    if not source_acc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source account '{transaction_in.source_account_id}' not found."
        )

    dest_acc = db.query(models.Account).filter(
        models.Account.id == transaction_in.destination_account_id
    ).first()
    if not dest_acc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Destination account '{transaction_in.destination_account_id}' not found."
        )

    # Check source account balance
    source_credits = db.query(func.coalesce(func.sum(models.LedgerEntry.amount), 0)).filter(
        models.LedgerEntry.account_id == transaction_in.source_account_id,
        models.LedgerEntry.entry_type == models.EntryType.CREDIT
    ).scalar() or Decimal("0.00")

    source_debits = db.query(func.coalesce(func.sum(models.LedgerEntry.amount), 0)).filter(
        models.LedgerEntry.account_id == transaction_in.source_account_id,
        models.LedgerEntry.entry_type == models.EntryType.DEBIT
    ).scalar() or Decimal("0.00")

    source_balance = Decimal(str(source_credits)) - Decimal(str(source_debits))

    if source_balance < transaction_in.amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient funds in source account '{transaction_in.source_account_id}'. Available: {source_balance}, Requested: {transaction_in.amount}"
        )

    # Atomic transaction execution
    reference_id = f"tx_{uuid.uuid4().hex[:12]}"

    debit_entry = models.LedgerEntry(
        id=f"entry_{uuid.uuid4().hex[:12]}",
        account_id=transaction_in.source_account_id,
        amount=transaction_in.amount,
        entry_type=models.EntryType.DEBIT,
        reference_id=reference_id
    )

    credit_entry = models.LedgerEntry(
        id=f"entry_{uuid.uuid4().hex[:12]}",
        account_id=transaction_in.destination_account_id,
        amount=transaction_in.amount,
        entry_type=models.EntryType.CREDIT,
        reference_id=reference_id
    )

    db.add(debit_entry)
    db.add(credit_entry)
    db.commit()
    db.refresh(debit_entry)

    response_payload = {
        "reference_id": reference_id,
        "source_account_id": transaction_in.source_account_id,
        "destination_account_id": transaction_in.destination_account_id,
        "amount": str(transaction_in.amount),
        "created_at": debit_entry.created_at.isoformat()
    }

    if idempotency_key:
        db_idempotency = models.IdempotencyKey(
            idempotency_key=idempotency_key,
            response_data=json.dumps(response_payload)
        )
        db.add(db_idempotency)
        db.commit()

    return schemas.TransactionResponse(
        reference_id=reference_id,
        source_account_id=transaction_in.source_account_id,
        destination_account_id=transaction_in.destination_account_id,
        amount=transaction_in.amount,
        created_at=debit_entry.created_at
    )


@router.get("/{reference_id}", response_model=List[schemas.LedgerEntryResponse])
def get_transaction_entries(reference_id: str, db: Session = Depends(get_db)):
    entries = db.query(models.LedgerEntry).filter(
        models.LedgerEntry.reference_id == reference_id
    ).all()

    if not entries:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No transaction found with reference ID '{reference_id}'."
        )

    return entries
