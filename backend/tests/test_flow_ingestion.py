import os
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL","sqlite:////tmp/daily-report-flow-tests.db")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import FlowEvent
from app.services.flow_ingestion import persist_flow_events


def _db():
    engine=create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _event(premium=500000):
    return {
        "event_type":"options",
        "symbol":"NVDA",
        "provider":"SquawkFlow",
        "outlier_score":88.0,
        "source_url":"https://squawkflow.com/options-flow",
        "occurred_at":datetime(2026,9,9,15,30,tzinfo=timezone.utc).isoformat(),
        "data":{"side":"call","strike":200,"expiration":"2026-09-18","contracts":1000,"premium":premium},
    }


def test_persists_real_flow_and_dedupes_repeat_observation():
    db=_db()
    first=persist_flow_events(db,[_event()])
    second=persist_flow_events(db,[_event()])
    assert first["inserted"]==1
    assert second["inserted"]==0
    assert second["deduped"]==1
    rows=db.query(FlowEvent).all()
    assert len(rows)==1
    assert rows[0].symbol=="NVDA"
    assert rows[0].payload["_fingerprint"]


def test_changed_observation_is_preserved_for_persistence_analysis():
    db=_db()
    persist_flow_events(db,[_event(500000)])
    result=persist_flow_events(db,[_event(750000)])
    assert result["inserted"]==1
    assert db.query(FlowEvent).count()==2
