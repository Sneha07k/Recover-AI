import random

import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.events.bus import EventBus
from app.experiments.harness import CONDITIONS, run_experiment
from app.models.enums import TransactionStatus
from app.simulator.generator import (
    create_merchant,
    generate_customers,
    generate_transactions,
)

EXPERIMENT_DB_URL = "sqlite:///../data/experiment.db"


def run_experiment_end_to_end(
    num_customers: int = 300, num_transactions: int = 3000, seed: int = 42
) -> dict:
    
    random.seed(seed)
    np.random.seed(seed)

    engine = create_engine(EXPERIMENT_DB_URL, connect_args={"check_same_thread": False})
    from app.models import models  

    Base.metadata.drop_all(bind=engine)  
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        merchant = create_merchant(db)
        customers = generate_customers(db, merchant, num_customers)
        
        isolated_bus = EventBus()
        transactions = generate_transactions(
            db, customers, num_transactions, bus=isolated_bus
        )

        failed = [t for t in transactions if t.status == TransactionStatus.FAILED]
        customers_by_id = {c.id: c for c in customers}

        results = run_experiment(
            db, failed, customers_by_id, conditions=CONDITIONS, seed=seed
        )

        return {
            "num_customers": num_customers,
            "num_transactions": num_transactions,
            "seed": seed,
            "total_failed": len(failed),
            "conditions": [
                {
                    "condition": cond,
                    "interventions": results[cond].interventions,
                    "successful": results[cond].successful,
                    "false_interventions": results[cond].false_interventions,
                    "recovery_rate": results[cond].recovery_rate,
                    "revenue_recovered": results[cond].revenue_recovered,
                    "total_cost": results[cond].total_cost,
                }
                for cond in CONDITIONS
            ],
        }
    finally:
        db.close()
