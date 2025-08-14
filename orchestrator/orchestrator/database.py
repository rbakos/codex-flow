"""
Production-ready database configuration with connection pooling,
async support, and monitoring.
"""
import os
from typing import AsyncGenerator, Optional
from contextlib import asynccontextmanager
import logging

from sqlalchemy import create_engine, pool, event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker, declarative_base
from sqlalchemy.pool import NullPool, QueuePool
import asyncpg
from tenacity import retry, stop_after_attempt, wait_exponential

from .logging_config import StructuredLogger, performance

logger = StructuredLogger(__name__)

# Base class for models
Base = declarative_base()


class DatabaseConfig:
    """Database configuration with production settings."""
    
    def __init__(self):
        self.database_url = os.getenv("ORCH_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/orchestrator")
        self.async_database_url = self._make_async_url(self.database_url)
        
        # Connection pool settings
        self.pool_size = int(os.getenv("DB_POOL_SIZE", "20"))
        self.max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "40"))
        self.pool_timeout = int(os.getenv("DB_POOL_TIMEOUT", "30"))
        self.pool_recycle = int(os.getenv("DB_POOL_RECYCLE", "3600"))
        self.pool_pre_ping = os.getenv("DB_POOL_PRE_PING", "true").lower() == "true"
        
        # Performance settings
        self.echo_sql = os.getenv("DB_ECHO_SQL", "false").lower() == "true"
        self.slow_query_threshold = float(os.getenv("DB_SLOW_QUERY_THRESHOLD", "1.0"))  # seconds
        
    def _make_async_url(self, sync_url: str) -> str:
        """Convert sync database URL to async."""
        if sync_url.startswith("postgresql://"):
            return sync_url.replace("postgresql://", "postgresql+asyncpg://")
        elif sync_url.startswith("postgresql+psycopg2://"):
            return sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        return sync_url


config = DatabaseConfig()


class DatabaseManager:
    """Manages database connections and sessions."""
    
    def __init__(self):
        self.config = config
        self._sync_engine = None
        self._async_engine = None
        self._sync_session_factory = None
        self._async_session_factory = None
        
    @property
    def sync_engine(self):
        """Get or create synchronous engine."""
        if not self._sync_engine:
            self._sync_engine = create_engine(
                self.config.database_url,
                poolclass=QueuePool,
                pool_size=self.config.pool_size,
                max_overflow=self.config.max_overflow,
                pool_timeout=self.config.pool_timeout,
                pool_recycle=self.config.pool_recycle,
                pool_pre_ping=self.config.pool_pre_ping,
                echo=self.config.echo_sql,
                connect_args={
                    "server_settings": {
                        "application_name": "codex-orchestrator",
                        "jit": "off"
                    },
                    "command_timeout": 60,
                    "options": "-c statement_timeout=60000"  # 60 seconds
                }
            )
            
            # Add event listeners for monitoring
            self._setup_engine_monitoring(self._sync_engine)
            
            return self._sync_engine
    
    @property
    def async_engine(self):
        """Get or create asynchronous engine."""
        if not self._async_engine:
            self._async_engine = create_async_engine(
                self.config.async_database_url,
                pool_size=self.config.pool_size,
                max_overflow=self.config.max_overflow,
                pool_timeout=self.config.pool_timeout,
                pool_recycle=self.config.pool_recycle,
                pool_pre_ping=self.config.pool_pre_ping,
                echo=self.config.echo_sql
            )
            
            return self._async_engine
    
    @property
    def sync_session_factory(self):
        """Get synchronous session factory."""
        if not self._sync_session_factory:
            self._sync_session_factory = sessionmaker(
                bind=self.sync_engine,
                autocommit=False,
                autoflush=False,
                expire_on_commit=False
            )
        return self._sync_session_factory
    
    @property
    def async_session_factory(self):
        """Get asynchronous session factory."""
        if not self._async_session_factory:
            self._async_session_factory = async_sessionmaker(
                bind=self.async_engine,
                autocommit=False,
                autoflush=False,
                expire_on_commit=False
            )
        return self._async_session_factory
    
    def get_sync_session(self) -> Session:
        """Get a new synchronous database session."""
        return self.sync_session_factory()
    
    def get_async_session(self) -> AsyncSession:
        """Get a new asynchronous database session."""
        return self.async_session_factory()
    
    @asynccontextmanager
    async def async_session_scope(self) -> AsyncGenerator[AsyncSession, None]:
        """Async context manager for database sessions with automatic cleanup."""
        async with self.async_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
    
    def _setup_engine_monitoring(self, engine):
        """Set up monitoring for database operations."""
        
        @event.listens_for(engine, "before_execute")
        def receive_before_execute(conn, clauseelement, multiparams, params, execution_options):
            conn.info.setdefault("query_start_time", []).append(performance.start_timer("db_query"))
        
        @event.listens_for(engine, "after_execute")
        def receive_after_execute(conn, clauseelement, multiparams, params, execution_options, result):
            if conn.info.get("query_start_time"):
                duration_ms = performance.end_timer("db_query")
                
                # Log slow queries
                if duration_ms and duration_ms > self.config.slow_query_threshold * 1000:
                    logger.warning(
                        "Slow query detected",
                        duration_ms=duration_ms,
                        query=str(clauseelement)[:500]  # Truncate long queries
                    )
        
        @event.listens_for(engine, "connect")
        def receive_connect(dbapi_conn, connection_record):
            logger.info("Database connection established", pool_size=engine.pool.size())
        
        @event.listens_for(engine, "close")
        def receive_close(dbapi_conn, connection_record):
            logger.info("Database connection closed", pool_size=engine.pool.size())
    
    async def create_tables(self):
        """Create all tables (async)."""
        async with self.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables created")
    
    async def drop_tables(self):
        """Drop all tables (async)."""
        async with self.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            logger.warning("Database tables dropped")
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def health_check(self) -> bool:
        """Check database health with retry logic."""
        try:
            async with self.async_session_scope() as session:
                result = await session.execute("SELECT 1")
                return result.scalar() == 1
        except Exception as e:
            logger.error("Database health check failed", error=e)
            return False
    
    async def get_pool_stats(self) -> dict:
        """Get connection pool statistics."""
        pool = self.sync_engine.pool
        return {
            "size": pool.size(),
            "checked_in": pool.checkedin(),
            "overflow": pool.overflow(),
            "total": pool.size() + pool.overflow()
        }
    
    async def cleanup(self):
        """Clean up database connections."""
        if self._sync_engine:
            self._sync_engine.dispose()
            logger.info("Synchronous engine disposed")
            
        if self._async_engine:
            await self._async_engine.dispose()
            logger.info("Asynchronous engine disposed")


# Global database manager instance
db_manager = DatabaseManager()


# Dependency injection for FastAPI
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database sessions."""
    async with db_manager.async_session_scope() as session:
        yield session


def get_sync_db() -> Session:
    """Get synchronous database session (for migrations, etc.)."""
    session = db_manager.get_sync_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class DatabaseMigrationManager:
    """Manages database migrations using Alembic."""
    
    def __init__(self):
        self.db_manager = db_manager
        
    async def run_migrations(self):
        """Run pending database migrations."""
        # This would integrate with Alembic
        # For now, just ensure tables exist
        await self.db_manager.create_tables()
        logger.info("Database migrations completed")
    
    async def rollback_migration(self, revision: str):
        """Rollback to a specific migration revision."""
        # Implement Alembic rollback
        logger.info(f"Rolling back to revision: {revision}")
        pass


# Connection pool monitoring
class PoolMonitor:
    """Monitor and log connection pool metrics."""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        
    async def log_metrics(self):
        """Log current pool metrics."""
        stats = await self.db_manager.get_pool_stats()
        logger.info(
            "Database pool stats",
            pool_size=stats["size"],
            checked_in=stats["checked_in"],
            overflow=stats["overflow"],
            total=stats["total"]
        )
    
    async def check_pool_health(self) -> bool:
        """Check if pool is healthy."""
        stats = await self.db_manager.get_pool_stats()
        
        # Alert if pool is exhausted
        if stats["checked_in"] == 0 and stats["overflow"] >= self.db_manager.config.max_overflow:
            logger.critical(
                "Database pool exhausted!",
                pool_stats=stats,
                alert_required=True
            )
            return False
            
        return True


pool_monitor = PoolMonitor(db_manager)