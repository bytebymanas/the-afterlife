from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def ensure_runtime_schema():
    """Create new tables and apply additive columns to older single-user installs."""
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    if "provider_connections" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("provider_connections")}
    additions = {
        "kaggle_username": "VARCHAR(120) NOT NULL DEFAULT ''",
        "kaggle_kernel_id": "VARCHAR(260)",
        "setup_state": "VARCHAR(32) NOT NULL DEFAULT 'NOT_CONFIGURED'",
        "active_setup_job_id": "VARCHAR(36)",
        "last_heartbeat": "TIMESTAMP",
        "gpu_metadata": "JSON NOT NULL DEFAULT '{}'",
        "cooldown_until": "TIMESTAMP",
        "failed_attempts": "INTEGER NOT NULL DEFAULT 0",
    }
    with engine.begin() as connection:
        for name, ddl in additions.items():
            if name not in existing:
                connection.exec_driver_sql(f"ALTER TABLE provider_connections ADD COLUMN {name} {ddl}")


def session_dependency():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
