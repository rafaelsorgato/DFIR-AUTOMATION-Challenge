import json
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, text
from sqlalchemy.orm import declarative_base, sessionmaker

from config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    source = Column(String(32), nullable=False)
    severity = Column(String(16), nullable=False)
    description = Column(Text, nullable=False)
    artifacts = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, default="PENDING")
    analysis_result = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "source": self.source,
            "severity": self.severity,
            "description": self.description,
            "artifacts": json.loads(self.artifacts),
            "status": self.status,
            "analysis_result": json.loads(self.analysis_result) if self.analysis_result else None,
            "created_at": self.created_at.isoformat() + "Z",
            "updated_at": self.updated_at.isoformat() + "Z",
        }


def init_db():
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        for idx in ("ix_alerts_alert_id",):
            try:
                conn.execute(text(f"DROP INDEX IF EXISTS {idx}"))
                conn.commit()
            except Exception:
                pass
        for col in ("raw_payload", "alert_id"):
            try:
                conn.execute(text(f"ALTER TABLE alerts DROP COLUMN {col}"))
                conn.commit()
            except Exception:
                pass
