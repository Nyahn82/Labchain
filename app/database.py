from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

from app.config import settings


database_url = URL.create(
    drivername="mysql+pymysql",
    username=settings.db_user,
    password=settings.db_password.get_secret_value(),
    host=settings.db_host,
    port=settings.db_port,
    database=settings.db_name,
)

engine = create_engine(
    database_url,
    pool_pre_ping=True,
    hide_parameters=True,
    connect_args={"connect_timeout": 5, "read_timeout": 5, "write_timeout": 5},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
