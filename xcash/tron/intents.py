from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import eth_abi
from tron.contracts_codec import tron_base58_to_evm_address
from web3 import Web3

from chains.models import TxTaskType

if TYPE_CHECKING:
    from collections.abc import Callable

    from chains.models import Address
    from chains.models import Chain


@dataclass(frozen=True)
class TronTxIntent:
    sender: Address
    chain: Chain
    to: str
    function_selector: str
    parameter: str
    fee_limit: int
    tx_type: TxTaskType
    verify_fn: Callable[[], None] | None = None


def build_contract_call_intent(
    *,
    sender: Address,
    chain: Chain,
    contract_address: str,
    function_selector_value: str,
    parameter: str,
    fee_limit: int,
    tx_type: TxTaskType,
    verify_fn: Callable[[], None] | None = None,
) -> TronTxIntent:
    if fee_limit < 0:
        raise ValueError("fee_limit must be >= 0")
    try:
        bytes.fromhex(parameter)
    except ValueError as exc:
        raise ValueError("parameter must be hex") from exc

    return TronTxIntent(
        sender=sender,
        chain=chain,
        to=contract_address,
        function_selector=function_selector_value,
        parameter=parameter.lower(),
        fee_limit=fee_limit,
        tx_type=tx_type,
        verify_fn=verify_fn,
    )


def build_vault_slot_deploy_intent(
    *,
    sender: Address,
    chain: Chain,
    factory_address: str,
    vault_address: str,
    salt: bytes,
    verify_fn: Callable[[], None] | None = None,
) -> TronTxIntent:
    if len(salt) != 32:
        raise ValueError("salt must be 32 bytes")
    parameter = eth_abi.encode(
        ["address", "bytes32"],
        [tron_base58_to_evm_address(vault_address), salt],
    ).hex()
    return build_contract_call_intent(
        sender=sender,
        chain=chain,
        contract_address=factory_address,
        function_selector_value="deployVaultSlot(address,bytes32)",
        parameter=parameter,
        # 任务入队时尚未估算；广播前按实时能量报价生成 fee_limit。
        fee_limit=0,
        tx_type=TxTaskType.VaultSlotDeploy,
        verify_fn=verify_fn,
    )


def build_vault_slot_collect_intent(
    *,
    sender: Address,
    chain: Chain,
    slot_address: str,
    token_address: str,
    verify_fn: Callable[[], None] | None = None,
) -> TronTxIntent:
    parameter = eth_abi.encode(
        ["address"],
        [tron_base58_to_evm_address(token_address)],
    ).hex()
    return build_contract_call_intent(
        sender=sender,
        chain=chain,
        contract_address=slot_address,
        function_selector_value="collect(address)",
        parameter=parameter,
        fee_limit=0,
        tx_type=TxTaskType.VaultSlotCollect,
        verify_fn=verify_fn,
    )


def trc20_balance_of_parameter(owner_address: str) -> str:
    return eth_abi.encode(
        ["address"],
        [Web3.to_checksum_address(tron_base58_to_evm_address(owner_address))],
    ).hex()
