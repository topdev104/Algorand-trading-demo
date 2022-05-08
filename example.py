import os
import random

import dotenv
from algosdk.account import generate_account
from algosdk.future import transaction
from algosdk.logic import get_application_address

from account import Account
from contracts import TradingContract
from utils import wait_for_transaction, get_algod_client, get_genesis_accounts, PendingTxnResponse


class TradeExample:
    def __init__(self):
        self.algod_client = get_algod_client(os.environ.get('ALGOD_ADDRESS'), os.environ.get('ALGOD_TOKEN'))
        self.creator = Account(os.environ.get('CREATOR_PK'))

    def get_temporary_account(self):
        pk = generate_account()[0]
        account = Account(pk)
        genesis_accounts = get_genesis_accounts(os.environ.get('KMD_ADDRESS'), os.environ.get('KMD_TOKEN'))
        sp = self.algod_client.suggested_params()
        funding_account = genesis_accounts[0]
        txn = transaction.PaymentTxn(
            sender=funding_account.get_address(),
            receiver=account.get_address(),
            amt=10_000_000,
            sp=sp
        )
        signed_txn = txn.sign(funding_account.get_private_key())
        self.algod_client.send_transaction(signed_txn)
        wait_for_transaction(self.algod_client, signed_txn.get_txid())
        return account

    def create_asset(self, total: int):
        random_number = random.randint(0, 999)
        random_note = bytes(random.randint(0, 255) for _ in range(20))

        txn = transaction.AssetCreateTxn(
            sender=self.creator.get_address(),
            total=total,
            decimals=0,
            default_frozen=False,
            manager=self.creator.get_address(),
            reserve=self.creator.get_address(),
            freeze=self.creator.get_address(),
            clawback=self.creator.get_address(),
            unit_name=f"D{random_number}",
            asset_name=f"https://dummy.asset/{random_number}",
            note=random_note,
            sp=self.algod_client.suggested_params()
        )

        signed_txn = txn.sign(self.creator.get_private_key())

        self.algod_client.send_transaction(signed_txn)

        response = wait_for_transaction(self.algod_client, signed_txn.get_txid())
        assert response.assetIndex is not None and response.assetIndex > 0
        return response.assetIndex

    def opt_in_to_asset(self, asset_id: int, account: Account) -> PendingTxnResponse:
        txn = transaction.AssetOptInTxn(
            sender=account.get_address(),
            index=asset_id,
            sp=self.algod_client.suggested_params(),
        )
        signed_txn = txn.sign(account.get_private_key())

        self.algod_client.send_transaction(signed_txn)
        return wait_for_transaction(self.algod_client, signed_txn.get_txid())

    def fund_asset_to_app(self, token_id: int):
        pass

    def transfer_asset(self, asset_id: int, amt: int, sender: Account, receiver: Account) -> PendingTxnResponse:
        txn = transaction.AssetTransferTxn(
            sender=sender.get_address(),
            receiver=receiver.get_address(),
            index=asset_id,
            amt=amt,
            sp=self.algod_client.suggested_params(),
        )
        signed_txn = txn.sign(sender.get_private_key())

        self.algod_client.send_transaction(signed_txn)
        return wait_for_transaction(self.algod_client, signed_txn.get_txid())

    def deploy(self, token_id):
        approval, clear = TradingContract.get_contracts(self.algod_client)
        global_schema = transaction.StateSchema(num_uints=56, num_byte_slices=8)
        local_schema = transaction.StateSchema(num_uints=0, num_byte_slices=8)

        txn = transaction.ApplicationCreateTxn(
            sender=self.creator.get_address(),
            on_complete=transaction.OnComplete.NoOpOC,
            approval_program=approval,
            clear_program=clear,
            global_schema=global_schema,
            local_schema=local_schema,
            foreign_assets=[token_id],
            sp=self.algod_client.suggested_params(),
        )

        signed_txn = txn.sign(self.creator.get_private_key())

        self.algod_client.send_transaction(signed_txn)

        response = wait_for_transaction(self.algod_client, signed_txn.get_txid())
        assert response.applicationIndex is not None and response.applicationIndex > 0
        return response.applicationIndex

    def open_trade(self, app_id: int, seller: Account, token_id: int, price: int, asset_amount: int):
        asset_txn = transaction.AssetTransferTxn(
            sender=seller.get_address(),
            receiver=get_application_address(app_id),
            index=token_id,
            amt=asset_amount,
            sp=self.algod_client.suggested_params()
        )
        call_txn = transaction.ApplicationCallTxn(
            sender=seller.get_address(),
            index=app_id,
            on_complete=transaction.OnComplete.NoOpOC,
            sp=self.algod_client.suggested_params(),
            app_args=[
                b"open",
                price.to_bytes(8, 'big')
            ]
        )
        transaction.assign_group_id([call_txn, asset_txn])
        signed_asset_txn = asset_txn.sign(seller.get_private_key())
        signed_call_txn = call_txn.sign(seller.get_private_key())
        self.algod_client.send_transactions([signed_call_txn, signed_asset_txn])
        wait_for_transaction(self.algod_client, signed_call_txn.get_txid())

    def buy_token(self, app_id: int, buyer: Account, token_id: int, price, asset_amount):
        payment_txn = transaction.PaymentTxn(
            sender=buyer.get_address(),
            receiver=get_application_address(app_id),
            amt=asset_amount * price,
            sp=self.algod_client.suggested_params()
        )
        call_txn = transaction.ApplicationCallTxn(
            sender=buyer.get_address(),
            index=app_id,
            on_complete=transaction.OnComplete.NoOpOC,
            sp=self.algod_client.suggested_params(),
            app_args=[
                b"buy"
            ],
            foreign_assets=[token_id]
        )
        transaction.assign_group_id([payment_txn, call_txn])
        signed_payment_txn = payment_txn.sign(buyer.get_private_key())
        signed_call_txn = call_txn.sign(buyer.get_private_key())
        self.algod_client.send_transactions([signed_payment_txn, signed_call_txn])
        wait_for_transaction(self.algod_client, signed_call_txn.get_txid())

    def close_trade(self, app_id: int, seller: Account):
        txn = transaction.ApplicationCallTxn(
            sender=seller.get_address(),
            index=app_id,
            on_complete=transaction.OnComplete.NoOpOC,
            sp=self.algod_client.suggested_params(),
            app_args=[
                b"close"
            ],
        )
        signed_txn = txn.sign(seller.get_private_key())
        self.algod_client.send_transaction(signed_txn)
        wait_for_transaction(self.algod_client, signed_txn.get_txid())

    def cancel_trade(self, app_id: int, seller: Account, token_id: int):
        txn = transaction.ApplicationCallTxn(
            sender=seller.get_address(),
            index=app_id,
            on_complete=transaction.OnComplete.NoOpOC,
            sp=self.algod_client.suggested_params(),
            app_args=[
                b"cancel"
            ],
            foreign_assets=[token_id]
        )
        signed_txn = txn.sign(seller.get_private_key())
        self.algod_client.send_transaction(signed_txn)
        wait_for_transaction(self.algod_client, signed_txn.get_txid())

    def start(self):
        print("===================================================================")
        print("Create dummy asset...")
        token_id = self.create_asset(1_000_000)
        print("Token ID: ", token_id)

        print("===================================================================")
        print("Create seller account...")
        seller = self.get_temporary_account()
        print("Seller address: ", seller.get_address())

        print("===================================================================")
        print("Create buyer account...")
        buyer = self.get_temporary_account()
        print("Seller address: ", buyer.get_address())

        print("===================================================================")
        print("Transfer asset to seller...")
        self.transfer_asset(token_id, 100, self.creator, seller)

        print("===================================================================")
        print("Deploy Smart contracts...")
        app_id = self.deploy(token_id)
        app_address = get_application_address(app_id)
        print("App ID: ", app_id)
        print("App Address: ", app_address)

        print("===================================================================")
        print("Open Trade...")
        price = 100_000
        asset_amount = 50
        self.open_trade(app_id, seller, token_id, price, asset_amount)

        print("===================================================================")
        print("Buy Token...")
        self.buy_token(app_id, buyer, token_id, price, asset_amount)

        print("===================================================================")
        print("Close Trade...")
        self.close_trade(app_id, seller)

        # print("===================================================================")
        # print("Cancel Trade...")
        # self.cancel_trade(app_id, seller, token_id)


if __name__ == '__main__':
    dotenv.load_dotenv('.env')
    TradeExample().start()
