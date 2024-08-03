# -*- coding:utf-8 -*-

"""
Market module.

Author: HuangTao
Date:   2019/02/16
Email:  huangtao@ifclover.com
"""

import json
from aioquant import const
from aioquant.utils import logger

class Ticker:
    """Ticker object.

    Args:
        platform: Exchange platform name, e.g. bitmex.
        symbol: Trading pair, e.g. BTC/USD.
        ask: sell price.
        bid: buy price.
        last: final price.
        timestamp: Update time, millisecond.
    cryptofeed：
        self.exchange = exchange
        self.symbol = symbol
        self.bid = bid
        self.ask = ask
        self.timestamp = timestamp
        self.raw = raw
        {"exchange":"BINANCE_DELIVERY","symbol":"FTM-USD-PERP","bid":0.2717,"ask":0.2718,"timestamp":1662941327.607,"receipt_timestamp":1662941327.764851}
    """

    def __init__(self, platform=None, symbol=None, ask=None, bid=None, last=None, timestamp=None):
        """ Initialize. """
        self.platform = platform
        self.symbol = symbol
        self.ask = ask
        self.bid = bid
        self.last = last
        self.timestamp = timestamp

    @property
    def data(self):
        d = {
            "platform": self.platform,
            "symbol": self.symbol,
            "ask": self.ask,
            "bid": self.bid,
            "last": self.last,
            "timestamp": self.timestamp
        }
        return d

    @property
    def smart(self):
        d = {
            "p": self.platform,
            "s": self.symbol,
            "a": self.ask,
            "b": self.bid,
            "l": self.last,
            "t": self.timestamp
        }
        return d

    def load_smart(self, d):
        self.platform = d["p"]
        self.symbol = d["s"]
        self.ask = d["a"]
        self.bid = d["b"]
        self.last = d["l"]
        self.timestamp = d["t"]
        return self

    def __str__(self):
        info = json.dumps(self.data)
        return info

    def __repr__(self):
        return str(self)

class Orderbook:
    """Orderbook object.

    Args:
        platform: Exchange platform name, e.g. `binance` / `bitmex`.
        symbol: Trade pair name, e.g. `ETH/BTC`.
        asks: Asks list, e.g. `[[price, quantity], [...], ...]`
        bids: Bids list, e.g. `[[price, quantity], [...], ...]`
        timestamp: Update time, millisecond.
    cryptofeed：
        self.exchange = exchange
        self.symbol = symbol
        self.book = _OrderBook(max_depth=max_depth, checksum_format=checksum_format, max_depth_strict=truncate)
        if bids:
            self.book.bids = bids
        if asks:
            self.book.asks = asks
        self.delta = None
        self.timestamp = None
        self.sequence_number = None
        self.checksum = None
        self.raw = None
        {"exchange":"BINANCE_DELIVERY","symbol":"BCH-USD-PERP","book":{"bid":{"129.7":106,"129.69":70},"ask":{"129.71":2,"129.72":200}},"timestamp":1662941435.633,"receipt_timestamp":1662941436.7803996}
    """

    def __init__(self, platform=None, symbol=None, asks=None, bids=None, timestamp=None):
        """Initialize."""
        self.platform = platform
        self.symbol = symbol
        self.asks = asks
        self.bids = bids
        self.timestamp = timestamp

    @property
    def data(self):
        d = {
            "platform": self.platform,
            "symbol": self.symbol,
            "asks": self.asks,
            "bids": self.bids,
            "timestamp": self.timestamp
        }
        return d

    @property
    def smart(self):
        d = {
            "p": self.platform,
            "s": self.symbol,
            "a": self.asks,
            "b": self.bids,
            "t": self.timestamp
        }
        return d

    def load_smart(self, d):
        self.platform = d["p"]
        self.symbol = d["s"]
        self.asks = d["a"]
        self.bids = d["b"]
        self.timestamp = d["t"]
        return self

    def __str__(self):
        info = json.dumps(self.data)
        return info

    def __repr__(self):
        return str(self)


class Trade:
    """Trade object.

    Args:
        platform: Exchange platform name, e.g. `binance` / `bitmex`.
        symbol: Trade pair name, e.g. `ETH/BTC`.
        action: Trade action, `BUY` / `SELL`.
        price: Order place price.
        quantity: Order place quantity.
        timestamp: Update time, millisecond.
    cryptofeed：
        self.exchange = exchange
        self.symbol = symbol
        self.side = side
        self.amount = amount
        self.price = price
        self.timestamp = timestamp
        self.id = id
        self.type = type
        self.raw = raw
        {"exchange":"BINANCE_DELIVERY","symbol":"ETH-USD-PERP","side":"buy","amount":1,"price":1736.01,"id":"209120980","type":null,"timestamp":1662944788.945,"receipt_timestamp":1662944789.1553712}
    """

    def __init__(self, platform=None, symbol=None, action=None, price=None, quantity=None, id=None, timestamp=None):
        """Initialize."""
        self.platform = platform
        self.symbol = symbol
        self.action = action
        self.price = price
        self.quantity = quantity
        self.id = id
        self.timestamp = timestamp

    @property
    def data(self):
        d = {
            "platform": self.platform,
            "symbol": self.symbol,
            "action": self.action,
            "price": self.price,
            "quantity": self.quantity,
            "id": self.id,
            "timestamp": self.timestamp
        }
        return d

    @property
    def smart(self):
        d = {
            "p": self.platform,
            "s": self.symbol,
            "a": self.action,
            "P": self.price,
            "q": self.quantity,
            "i": self.id,
            "t": self.timestamp
        }
        return d

    def load_smart(self, d):
        self.platform = d["p"]
        self.symbol = d["s"]
        self.action = d["a"]
        self.price = d["P"]
        self.quantity = d["q"]
        self.id = d['i']
        self.timestamp = d["t"]
        return self

    def __str__(self):
        info = json.dumps(self.data)
        return info

    def __repr__(self):
        return str(self)


class Kline:
    """Kline object.

    Args:
        platform: Exchange platform name, e.g. `binance` / `bitmex`.
        symbol: Trade pair name, e.g. `ETH/BTC`.
        open: Open price.
        high: Highest price.
        low: Lowest price.
        close: Close price.
        volume: Total trade volume.
        timestamp: Update time, millisecond.
        kline_type: Kline type name, `kline`, `kline_5min`, `kline_15min` ... and so on.
    cryptofeed：
        self.exchange = exchange
        self.symbol = symbol
        self.start = start
        self.stop = stop
        self.interval = interval
        self.trades = trades
        self.open = open
        self.close = close
        self.high = high
        self.low = low
        self.volume = volume
        self.closed = closed
        self.timestamp = timestamp
        self.raw = raw
        {"exchange":"BINANCE_DELIVERY","symbol":"MATIC-USD-PERP","start":1662941100,"stop":1662941159.999,"interval":"1m","trades":28,"open":0.8905,"close":0.8908,"high":0.8909,"low":0.8905,"volume":1604,"closed":true,"timestamp":1662941162.004,"receipt_timestamp":1662941162.1787884}
    """

    def __init__(self, platform=None, symbol=None, start=None, stop=None, open=None, high=None, low=None, close=None, volume=None,
                 timestamp=None, kline_type=None):
        """Initialize."""
        self.platform = platform
        self.start = start
        self.stop = stop
        self.symbol = symbol
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.timestamp = timestamp
        self.kline_type = kline_type

    @property
    def data(self):
        d = {
            "platform": self.platform,
            "symbol": self.symbol,
            "start": self.start,
            "stop": self.stop,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "timestamp": self.timestamp,
            "kline_type": self.kline_type
        }
        return d

    @property
    def smart(self):
        d = {
            "p": self.platform,
            "s": self.symbol,
            "a": self.start,
            "st": self.stop,
            "o": self.open,
            "h": self.high,
            "l": self.low,
            "c": self.close,
            "v": self.volume,
            "t": self.timestamp,
            "kt": self.kline_type
        }
        return d

    def load_smart(self, d):
        self.platform = d["p"]
        self.symbol = d["s"]
        self.start = d['a']
        self.stop = d['st']
        self.open = d["o"]
        self.high = d["h"]
        self.low = d["l"]
        self.close = d["c"]
        self.volume = d["v"]
        self.timestamp = d["t"]
        self.kline_type = d["kt"]
        return self

    def __str__(self):
        info = json.dumps(self.data)
        return info

    def __repr__(self):
        return str(self)


class Market:
    """Subscribe Market.

    Args:
        market_type: Market data type,
            MARKET_TYPE_TRADE = "trade"
            MARKET_TYPE_ORDERBOOK = "orderbook"
            MARKET_TYPE_TICKER = "ticker"
            MARKET_TYPE_KLINE = "kline"
            MARKET_TYPE_KLINE_5M = "kline_5m"
            MARKET_TYPE_KLINE_15M = "kline_15m"
        platform: Exchange platform name, e.g. `binance` / `bitmex`.
        symbol: Trade pair name, e.g. `ETH/BTC`.
        callback: Asynchronous callback function for market data update.
                e.g. async def on_event_kline_update(kline: Kline):
                        pass
    """

    def __init__(self, market_type, platform, symbol, callback, account=None, strategy=None):
        """Initialize."""
        if platform == "#" or symbol == "#":
            multi = True
        else:
            multi = False
        if market_type == const.MARKET_TYPE_ORDERBOOK:
            from aioquant.event import EventOrderbook
            EventOrderbook(Orderbook(platform, symbol)).subscribe(callback, multi)
        elif market_type == const.MARKET_TYPE_TRADE:
            from aioquant.event import EventTrade
            EventTrade(Trade(platform, symbol)).subscribe(callback, multi)
        elif market_type == const.MARKET_TYPE_TICKER:
            from aioquant.event import EventTicker
            EventTicker(Ticker(platform, symbol)).subscribe(callback, multi)
        elif market_type in [
            const.MARKET_TYPE_KLINE, const.MARKET_TYPE_KLINE_5M, const.MARKET_TYPE_KLINE_15M,
            const.MARKET_TYPE_KLINE_30M, const.MARKET_TYPE_KLINE_1H, const.MARKET_TYPE_KLINE_2H,
            const.MARKET_TYPE_KLINE_4H, const.MARKET_TYPE_KLINE_6H, const.MARKET_TYPE_KLINE_12H,
            const.MARKET_TYPE_KLINE_1D
        ]:
            from aioquant.event import EventKline
            EventKline(Kline(platform, symbol, kline_type=market_type)).subscribe(callback, multi)
        elif market_type == const.MARKET_TYPE_ASSET:
            from aioquant.event import EventAsset
            from aioquant.asset import Asset
            EventAsset(Asset(platform,account)).subscribe(callback, multi)
        elif market_type == const.MARKET_TYPE_ORDER:
            from aioquant.event import EventOrder
            from aioquant.order import Order
            EventOrder(Order(platform,account,strategy)).subscribe(callback, multi)
        elif market_type == const.MARKET_TYPE_FILL:
            from aioquant.event import EventFill
            from aioquant.fill import Fill
            EventFill(Fill(platform,account,strategy)).subscribe(callback, multi)
        elif market_type == const.MARKET_TYPE_POSITION:
            from aioquant.event import EventPosition
            from aioquant.position import Position
            EventPosition(Position(platform,account,strategy)).subscribe(callback, multi)
        else:
            logger.error("market_type error:", market_type, caller=self)
