from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.audit_service import build_audit_entry
from app.api.schemas import AgentDecisionOut, AuditTrailEntry, RecoveryAttemptOut
from app.database import get_db
from app.models.models import AgentDecision, PolicyDecision, RecoveryAttempt

router = APIRouter(tags=["audit"])


@router.get("/recovery-events", response_model=list[RecoveryAttemptOut])
def list_recovery_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return (
        db.query(RecoveryAttempt)
        .order_by(RecoveryAttempt.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/agent-decisions", response_model=list[AgentDecisionOut])
def list_agent_decisions(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return (
        db.query(AgentDecision)
        .order_by(AgentDecision.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/audit-log", response_model=list[AuditTrailEntry])
def list_audit_log(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    
    policy_decisions = (
        db.query(PolicyDecision)
        .order_by(PolicyDecision.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    entries = []
    for pd in policy_decisions:
        entry = build_audit_entry(db, pd.transaction_id)
        if entry is not None:
            entries.append(entry)
    return entries


@router.get("/audit-log/{transaction_id}", response_model=AuditTrailEntry)
def get_audit_entry(transaction_id: int, db: Session = Depends(get_db)):
    entry = build_audit_entry(db, transaction_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return entry
