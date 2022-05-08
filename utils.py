from base64 import b64decode
from typing import List, Tuple, Dict, Any, Optional, Union

from algosdk.kmd import KMDClient
from algosdk.v2client.algod import AlgodClient
from pyteal import compileTeal, Mode, Expr

from account import Account


class PendingTxnResponse:
    def __init__(self, response: Dict[str, Any]) -> None:
        self.poolError: str = response["pool-error"]
        self.txn: Dict[str, Any] = response["txn"]

        self.applicationIndex: Optional[int] = response.get("application-index")
        self.assetIndex: Optional[int] = response.get("asset-index")
        self.closeRewards: Optional[int] = response.get("close-rewards")
        self.closingAmount: Optional[int] = response.get("closing-amount")
        self.confirmedRound: Optional[int] = response.get("confirmed-round")
        self.globalStateDelta: Optional[Any] = response.get("global-state-delta")
        self.localStateDelta: Optional[Any] = response.get("local-state-delta")
        self.receiverRewards: Optional[int] = response.get("receiver-rewards")
        self.senderRewards: Optional[int] = response.get("sender-rewards")

        self.inner_txns: List[Any] = response.get("inner-txns", [])
        self.logs: List[bytes] = [b64decode(ll) for ll in response.get("logs", [])]


def get_algod_client(algod_address: str, algod_token: str) -> AlgodClient:
    headers = {
        'X-API-Key': algod_token
    }
    return AlgodClient(algod_token, algod_address, headers)


def get_kmd_client(kmd_address: str, kmd_token: str) -> KMDClient:
    return KMDClient(kmd_token, kmd_address)


def get_genesis_accounts(kmd_address, kmd_token) -> List[Account]:
    kmd_wallet_name = "unencrypted-default-wallet"
    kmd_wallet_password = ""

    kmd = get_kmd_client(kmd_address, kmd_token)

    wallets = kmd.list_wallets()
    wallet_id = None
    for wallet in wallets:
        if wallet["name"] == kmd_wallet_name:
            wallet_id = wallet["id"]
            break

    if wallet_id is None:
        raise Exception("Wallet not found: {}".format(kmd_wallet_name))

    wallet_handle = kmd.init_wallet_handle(wallet_id, kmd_wallet_password)

    try:
        addresses = kmd.list_keys(wallet_handle)
        private_keys = [
            kmd.export_key(wallet_handle, kmd_wallet_password, addr)
            for addr in addresses
        ]
        kmd_accounts = [Account(sk) for sk in private_keys]
    finally:
        kmd.release_wallet_handle(wallet_handle)

    return kmd_accounts


def wait_for_transaction(
        client: AlgodClient, tx_id: str
) -> PendingTxnResponse:
    last_status = client.status()
    last_round = last_status.get("last-round")
    pending_txn = client.pending_transaction_info(tx_id)
    while not (pending_txn.get("confirmed-round") and pending_txn.get("confirmed-round") > 0):
        print("Waiting for confirmation...")
        last_round += 1
        client.status_after_block(last_round)
        pending_txn = client.pending_transaction_info(tx_id)
    print(
        "Transaction {} confirmed in round {}.".format(
            tx_id, pending_txn.get("confirmed-round")
        )
    )
    return PendingTxnResponse(pending_txn)


def fully_compile_contract(client: AlgodClient, contract: Expr) -> bytes:
    teal = compileTeal(contract, mode=Mode.Application, version=5)
    response = client.compile(teal)
    return b64decode(response["result"])


def decode_state(state_array: List[Any]) -> Dict[bytes, Union[int, bytes]]:
    state: Dict[bytes, Union[int, bytes]] = dict()

    for pair in state_array:
        key = b64decode(pair["key"])

        value = pair["value"]
        value_type = value["type"]

        if value_type == 2:
            # value is uint64
            value = value.get("uint", 0)
        elif value_type == 1:
            # value is byte array
            value = b64decode(value.get("bytes", ""))
        else:
            raise Exception(f"Unexpected state type: {value_type}")

        state[key] = value

    return state


def get_app_global_state(
    client: AlgodClient, app_id: int
) -> Dict[bytes, Union[int, bytes]]:
    app_info = client.application_info(app_id)
    return decode_state(app_info["params"]["global-state"])


def get_balances(client: AlgodClient, account: str) -> Dict[int, int]:
    balances: Dict[int, int] = dict()

    account_info = client.account_info(account)

    # set key 0 to Algo balance
    balances[0] = account_info["amount"]

    assets: List[Dict[str, Any]] = account_info.get("assets", [])
    for assetHolding in assets:
        assetID = assetHolding["asset-id"]
        amount = assetHolding["amount"]
        balances[assetID] = amount

    return balances


def get_last_block_timestamp(client: AlgodClient) -> Tuple[int, int]:
    status = client.status()
    last_round = status["last-round"]
    block = client.block_info(last_round)
    timestamp = block["block"]["ts"]

    return block, timestamp
