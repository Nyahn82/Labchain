"""Blockchain settings shared by web capture and the isolated worker process.

Importing this module never constructs web settings or reads a dotenv file.
"""
from pathlib import Path
from typing import Literal
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class BlockchainSettings(BaseSettings):
    blockchain_source_node: Literal['node1', 'node2', 'node3', 'node4'] = 'node1'
    blockchain_source_msp: Literal['Org1MSP', 'Org2MSP'] = 'Org1MSP'

    # Full credential validation belongs to worker startup.
    blockchain_delivery_enabled: bool = False
    blockchain_gateway_endpoint: str = '127.0.0.1:7051'
    blockchain_gateway_tls_ca_path: Path | None = None
    blockchain_client_msp_id: str = 'Org1MSP'
    blockchain_client_cert_path: Path | None = None
    blockchain_client_key_path: Path | None = None
    blockchain_channel: str = 'labchain-channel'
    blockchain_chaincode: str = 'labchain-anchor'
    blockchain_adapter_command: list[str] = Field(default_factory=lambda: [
        '/usr/bin/node', str(Path(__file__).resolve().parents[1] / 'blockchain/gateway-adapter/src/cli.js')])
    blockchain_worker_poll_seconds: float = 2
    blockchain_worker_batch_size: int = 1
    blockchain_worker_max_attempts: int = 8
    blockchain_worker_retry_base_seconds: float = 15
    blockchain_worker_retry_max_seconds: float = 900
    blockchain_worker_lease_seconds: float = 120
    blockchain_adapter_timeout_seconds: float = 90

    @model_validator(mode='after')
    def validate_blockchain_source(self):
        expected = 'Org1MSP' if self.blockchain_source_node in {'node1', 'node2'} else 'Org2MSP'
        if self.blockchain_source_msp != expected:
            raise ValueError('Blockchain source node and MSP do not match.')
        return self
