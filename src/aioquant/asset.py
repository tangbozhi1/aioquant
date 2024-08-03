# -*- coding:utf-8 -*-

"""
Asset object.

Author: HuangTao
Date:   2018/04/22
Email:  huangtao@ifclover.com
"""

import json

class Asset:
    """Asset object.

    Attributes:
        platform: Exchange platform name, e.g. `binance` / `bitmex`.
        account: Trading account name, e.g. `test@gmail.com`.
        strategy: Strategy name, e.g. `my_strategy`.
        symbol: Trading pair name, e.g. `ETH/BTC`.
    cryptofeed:
        self.exchange = exchange
        self.currency = currency
        self.balance = balance
        self.reserved = reserved
        self.raw = raw
    """

    def __init__(self, platform=None, account=None, assets=None, timestamp=None, update=False):
        """ Initialize. """
        self.platform = platform
        self.account = account
        self.assets = assets or {}
        self.timestamp = timestamp
        self.update = update

    @property
    def data(self):
        d = {
            "platform": self.platform,
            "account": self.account,
            "assets": self.assets,
            "timestamp": self.timestamp,
            "update": self.update
        }
        return d

    def __str__(self):
        info = json.dumps(self.data)
        return info

    def __repr__(self):
        return str(self)
