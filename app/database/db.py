from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.ext.declarative import declarative_base

DATABASE_URL = "sqlite:///example.db"

engine = create_engine(DATABASE_URL, echo=False)

# 优化 SQLite 性能：开启 WAL 模式和适当的同步设置
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")  # Normal slower than OFF but safer, faster than FULL
    cursor.execute("PRAGMA cache_size=-10000")   # ~10MB cache
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.close()

SessionLocal = scoped_session(
    sessionmaker(autocommit=False, autoflush=False, bind=engine)
)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
