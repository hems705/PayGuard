import hashlib
import uuid
from decimal import Decimal
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/accounts", tags=["Accounts"])


def hash_passcode(passcode: str) -> str:
    salt = "PayGuardSalt_2026"
    return hashlib.sha256(f"{salt}{passcode}".encode("utf-8")).hexdigest()


def verify_passcode(passcode: str, hashed: str) -> bool:
    if not hashed:
        return False
    return hash_passcode(passcode) == hashed


def to_account_response(account: models.Account) -> schemas.AccountResponse:
    return schemas.AccountResponse(
        id=account.id,
        name=account.name,
        has_passcode=bool(account.passcode_hash),
        created_at=account.created_at
    )


@router.post("/", response_model=schemas.AccountResponse, status_code=status.HTTP_201_CREATED)
def create_account(account_in: schemas.AccountCreate, db: Session = Depends(get_db)):
    account_id = account_in.id or f"acc_{uuid.uuid4().hex[:12]}"
    
    existing = db.query(models.Account).filter(models.Account.id == account_id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Account with ID '{account_id}' already exists."
        )

    passcode_hash = hash_passcode(account_in.passcode) if account_in.passcode else None

    db_account = models.Account(id=account_id, name=account_in.name, passcode_hash=passcode_hash)
    db.add(db_account)

    if account_in.initial_balance and account_in.initial_balance > 0:
        init_entry = models.LedgerEntry(
            id=f"entry_{uuid.uuid4().hex[:12]}",
            account_id=account_id,
            amount=account_in.initial_balance,
            entry_type=models.EntryType.CREDIT,
            reference_id=f"init_{account_id}"
        )
        db.add(init_entry)

    db.commit()
    db.refresh(db_account)
    return to_account_response(db_account)


@router.post("/{account_id}/passcode", response_model=schemas.AccountResponse)
def set_account_passcode(
    account_id: str,
    passcode_in: schemas.PasscodeSetRequest,
    db: Session = Depends(get_db)
):
    account = db.query(models.Account).filter(models.Account.id == account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account '{account_id}' not found."
        )

    account.passcode_hash = hash_passcode(passcode_in.passcode)
    db.commit()
    db.refresh(account)
    return to_account_response(account)


@router.get("/{account_id}", response_model=schemas.AccountResponse)
def get_account(account_id: str, db: Session = Depends(get_db)):
    account = db.query(models.Account).filter(models.Account.id == account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account '{account_id}' not found."
        )
    return to_account_response(account)


@router.get("/{account_id}/balance", response_model=schemas.BalanceResponse)
def get_account_balance(account_id: str, db: Session = Depends(get_db)):
    account = db.query(models.Account).filter(models.Account.id == account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account '{account_id}' not found."
        )

    credits = db.query(func.coalesce(func.sum(models.LedgerEntry.amount), 0))\
        .filter(
            models.LedgerEntry.account_id == account_id,
            models.LedgerEntry.entry_type == models.EntryType.CREDIT
        ).scalar() or Decimal("0.00")

    debits = db.query(func.coalesce(func.sum(models.LedgerEntry.amount), 0))\
        .filter(
            models.LedgerEntry.account_id == account_id,
            models.LedgerEntry.entry_type == models.EntryType.DEBIT
        ).scalar() or Decimal("0.00")

    total_credits = Decimal(str(credits))
    total_debits = Decimal(str(debits))
    balance = total_credits - total_debits

    return schemas.BalanceResponse(
        account_id=account_id,
        balance=balance,
        total_credits=total_credits,
        total_debits=total_debits
    )


@router.get("/{account_id}/entries", response_model=List[schemas.LedgerEntryResponse])
def get_account_entries(
    account_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    account = db.query(models.Account).filter(models.Account.id == account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account '{account_id}' not found."
        )

    entries = db.query(models.LedgerEntry)\
        .filter(models.LedgerEntry.account_id == account_id)\
        .order_by(models.LedgerEntry.created_at.desc())\
        .offset(skip)\
        .limit(limit)\
        .all()

    return entries
