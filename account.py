from algosdk import account, mnemonic


class Account:
    """Represents a private key and address for an Algorand account"""

    def __init__(self, private_key: str) -> None:
        self.sk = private_key
        self.address = account.address_from_private_key(private_key)

    def get_address(self) -> str:
        return self.address

    def get_private_key(self) -> str:
        return self.sk

    def get_mnemonic(self) -> str:
        return mnemonic.from_private_key(self.sk)

    @classmethod
    def from_mnemonic(cls, m: str) -> "Account":
        return cls(mnemonic.to_private_key(m))
