"""Process-environment-only worker configuration, independent of FastAPI secrets."""
from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

from app.blockchain_config import BlockchainSettings


class WorkerSettings(BlockchainSettings):
    db_host: str
    db_port: int = 3306
    db_name: str
    db_user: str
    db_password: SecretStr

    # systemd loads /etc/rhu-labchain/blockchain-worker.env into the process.
    # Never open the web .env, and never require its MFA/authentication secrets.
    model_config = SettingsConfigDict(env_file=None, hide_input_in_errors=True)


def worker_sessions(settings):
    url = URL.create(drivername='mysql+pymysql', username=settings.db_user,
        password=settings.db_password.get_secret_value(), host=settings.db_host,
        port=settings.db_port, database=settings.db_name)
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True,
        connect_args={'connect_timeout': 5, 'read_timeout': 5, 'write_timeout': 5})
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)
