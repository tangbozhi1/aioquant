# -*- coding:utf-8 -*-

"""
Fill object.

Author: HuangTao
Date:   2018/05/14
Email:  huangtao@ifclover.com
"""

import json

from aioquant.utils import tools

# maker or taker
LIQUIDITY_TYPE_TAKER = "TAKER"
LIQUIDITY_TYPE_MAKER = "MAKER"

# Order type.
ORDER_TYPE_LIMIT = "LIMIT"  # Limit order.
ORDER_TYPE_MARKET = "MARKET"  # Market order.
ORDER_TYPE_POST_ONLY = "POST-ONLY" # Post only (Order shall be filled only as maker).
ORDER_TYPE_FOK = "FOK" # Fill or Kill (FOK).
ORDER_TYPE_IOC = "IOC" # Immediate or Cancel (IOC).

# Order direction.
ORDER_ACTION_BUY = "BUY"  # Buy
ORDER_ACTION_SELL = "SELL"  # Sell

# Order status.
ORDER_STATUS_NONE = "NONE"  # New created order, no status.
ORDER_STATUS_SUBMITTED = "SUBMITTED"  # The order that submitted to server successfully.
ORDER_STATUS_PARTIAL_FILLED = "PARTIAL-FILLED"  # The order that filled partially.
ORDER_STATUS_FILLED = "FILLED"  # The order that filled fully.
ORDER_STATUS_CANCELED = "CANCELED"  # The order that canceled.
ORDER_STATUS_FAILED = "FAILED"  # The order that failed.
ORDER_STATUS_INSURANCE = "INSURANCE"  # The order that insurance.

# Future order trade type.
TRADE_TYPE_NONE = 0  # Unknown type, some Exchange's order information couldn't known the type of trade.
# buy open开多，sell open开空，buy close平空，sell close平多.
TRADE_TYPE_BUY_OPEN = 1  # Buy open, action = BUY & quantity > 0.
TRADE_TYPE_SELL_OPEN = 2  # Sell open, action = SELL & quantity < 0.
TRADE_TYPE_SELL_CLOSE = 3  # Sell close, action = SELL & quantity > 0.
TRADE_TYPE_BUY_CLOSE = 4  # Buy close, action = BUY & quantity < 0.

class Fill:
    """Fill object.

    Attributes:
        platform: Exchange platform name, e.g. `binance` / `bitmex`.
        account: Trading account name, e.g. `test@gmail.com`.
        strategy: Strategy name, e.g. `my_strategy`.
        order_id: Order id.
        fill_id: Order fill id.
        symbol: Trading pair name, e.g. `ETH/BTC`.
        action: Trading side, `BUY` / `SELL`.
        price: Order price.
        quantity: Order quantity.
        role: 是maker成交还是taker成交
        fee: Trading fee.
        ctime: Order create time, millisecond.
    cryptofeed:
        self.exchange = exchange
        self.symbol = symbol
        self.side = side
        self.amount = amount
        self.price = price
        self.fee = fee
        self.id = id
        self.order_id = order_id
        self.type = type
        self.liquidity = liquidity
        self.account = account
        self.timestamp = timestamp
        self.raw = raw
    """

    def __init__(self, platform=None, account=None, strategy=None, symbol=None, fill_id=None, order_id=None,trade_type=TRADE_TYPE_NONE, liquidity_price=None, action=None, price=0, quantity=0, role=None, fee=0, ctime=None):
        self.platform = platform
        self.account = account
        self.strategy = strategy
        self.symbol = symbol
        self.fill_id = fill_id
        self.order_id = order_id
        self.trade_type = trade_type
        self.liquidity_price = liquidity_price
        self.action = action
        self.price = price
        self.quantity = quantity
        self.role = role
        self.fee = fee
        self.ctime = ctime if ctime else tools.get_cur_timestamp_ms()

    @property
    def data(self):
        d = {
            "platform": self.platform,
            "account": self.account,
            "strategy": self.strategy,
            "symbol": self.symbol,
            "fill_id": self.fill_id,
            "order_id": self.order_id,
            "trade_type": self.trade_type,
            "liquidity_price": self.liquidity_price,
            "action": self.action,
            "price": self.price,
            "quantity": self.quantity,
            "role": self.role,
            "fee": self.fee,
            "ctime": self.ctime
        }
        return d

    def __str__(self):
        info = json.dumps(self.data)
        return info

    def __repr__(self):
        return str(self)
