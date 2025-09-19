import os

from pydantic_settings import BaseSettings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import telemetry functions
from telemetry import increment_counter


class Settings(BaseSettings):
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/document_metadata",
    )


settings = Settings()

engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Dependency to get database session"""
    # Track database connection opened
    increment_counter("database_connections_total", 1, {"status": "opened"})
    
    db = SessionLocal()
    try:
        yield db
    finally:
        # Track database connection closed
        increment_counter("database_connections_total", 1, {"status": "closed"})
        db.close()
