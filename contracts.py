from typing import Tuple

from algosdk.v2client.algod import AlgodClient
from pyteal import *

from utils import fully_compile_contract


class TradingContract:
    class Variables:
        open_price_key = Bytes("o_price")
        seller_key = Bytes("seller")
        token_id_key = Bytes("token_id")

    @staticmethod
    @Subroutine(TealType.none)
    def send_algo_to(account: Expr, amount: Expr) -> Expr:
        return If(Balance(Global.current_application_address()) != Int(0)).Then(
            Seq(
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.sender: Global.current_application_address(),
                    TxnField.receiver: account,
                    TxnField.amount: amount,
                }),
                InnerTxnBuilder.Submit(),
            )
        )

    def on_create(self):
        token_id = Txn.assets[0]
        return Seq(
            App.globalPut(self.Variables.token_id_key, token_id),
            Approve()
        )

    def on_call(self):
        on_call_method = Txn.application_args[0]
        return Cond(
            [on_call_method == Bytes("open"), self.on_open()],
            [on_call_method == Bytes("buy"), self.on_buy()],
            [on_call_method == Bytes("close"), self.on_close()],
            [on_call_method == Bytes("cancel"), self.on_cancel()]
        )

    def on_open(self):
        token_id = App.globalGet(self.Variables.token_id_key)
        price = Btoi(Txn.application_args[1])
        axfer_txn_index = Txn.group_index() + Int(1)
        return Seq(
            Assert(
                And(
                    Gtxn[axfer_txn_index].type_enum() == TxnType.AssetTransfer,
                    Gtxn[axfer_txn_index].xfer_asset() == token_id,
                )
            ),
            App.globalPut(self.Variables.open_price_key, price),
            App.globalPut(self.Variables.seller_key, Txn.sender()),

            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: token_id,
                TxnField.asset_receiver: Global.current_application_address(),
            }),
            InnerTxnBuilder.Submit(),

            Approve(),
        )

    def on_buy(self):
        payment_txn_index = Txn.group_index() - Int(1)
        token_id = App.globalGet(self.Variables.token_id_key)
        assets_holding = AssetHolding.balance(Global.current_application_address(), token_id)
        open_price = App.globalGet(self.Variables.open_price_key)
        return Seq(
            assets_holding,
            Assert(
                And(
                    Gtxn[payment_txn_index].type_enum() == TxnType.Payment,
                    Gtxn[payment_txn_index].amount() == (open_price * assets_holding.value()),
                    token_id == Txn.assets[0],
                    assets_holding.value() > Int(0)
                )
            ),

            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: token_id,
                TxnField.asset_close_to: Txn.sender(),
            }),
            InnerTxnBuilder.Submit(),

            Approve(),
        )

    def on_close(self):
        open_price = App.globalGet(self.Variables.open_price_key)
        token_id = App.globalGet(self.Variables.token_id_key)
        assets_holding = AssetHolding.balance(Global.current_application_address(), token_id)
        seller = App.globalGet(self.Variables.seller_key)
        return Seq(
            Assert(BytesEq(seller, Txn.sender()) == Int(1)),
            assets_holding,
            If(assets_holding.hasValue()).Then(Seq(
                TradingContract.send_algo_to(Txn.sender(), open_price * assets_holding.value()),
            )),
            Approve()
        )

    def on_cancel(self):
        token_id = App.globalGet(self.Variables.token_id_key)
        assets_holding = AssetHolding.balance(Global.current_application_address(), token_id)
        return Seq(
            Assert(token_id == Txn.assets[0]),
            assets_holding,
            If(assets_holding.hasValue()).Then(Seq(
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields({
                    TxnField.type_enum: TxnType.AssetTransfer,
                    TxnField.xfer_asset: token_id,
                    TxnField.asset_close_to: Txn.sender(),
                }),
                InnerTxnBuilder.Submit(),
                Approve(),
            )),
            Reject(),
        )

    def on_delete(self):
        return Seq(
            Approve()
        )

    def approval_program(self):
        program = Cond(
            [Txn.application_id() == Int(0), self.on_create()],
            [Txn.on_completion() == OnComplete.NoOp, self.on_call()],
            [
                Txn.on_completion() == OnComplete.DeleteApplication,
                self.on_delete(),
            ],
            [
                Or(
                    Txn.on_completion() == OnComplete.OptIn,
                    Txn.on_completion() == OnComplete.CloseOut,
                    Txn.on_completion() == OnComplete.UpdateApplication,
                ),
                Reject(),
            ],
        )
        return program

    def clear_state_program(self):
        return Approve()

    @staticmethod
    def get_contracts(client: AlgodClient) -> Tuple[bytes, bytes]:
        trading_contract = TradingContract()
        approval_program = b""
        clear_state_program = b""

        if len(approval_program) == 0:
            approval_program = fully_compile_contract(client, trading_contract.approval_program())
            clear_state_program = fully_compile_contract(client, trading_contract.clear_state_program())

        return approval_program, clear_state_program

    @staticmethod
    def compile_contracts():
        trading_contract = TradingContract()
        with open("trading_approval.teal", "w") as f:
            compiled = compileTeal(trading_contract.approval_program(), mode=Mode.Application, version=5)
            f.write(compiled)

        with open("trading_clear_state.teal", "w") as f:
            compiled = compileTeal(trading_contract.clear_state_program(), mode=Mode.Application, version=5)
            f.write(compiled)


if __name__ == "__main__":
    TradingContract.compile_contracts()
