# -*- coding:utf-8 -*-

'''
Copyright (C) 2017-2022 Bryant Moscon - bmoscon@gmail.com

Please see the LICENSE file for the terms and conditions
associated with this software.


Defines contains all constant string definitions for Cryptofeed,
as well as some documentation (in comment form) regarding
the book definitions and structure
'''
ASCENDEX = 'ASCENDEX'
ASCENDEX_FUTURES = 'ASCENDEX_FUTURES'
BEQUANT = 'BEQUANT'
BITFINEX = 'BITFINEX'
BITHUMB = 'BITHUMB'
BITMEX = 'BITMEX'
BINANCE = 'BINANCE'
BINANCE_US = 'BINANCE_US'
BINANCE_FUTURES = 'BINANCE_FUTURES'
BINANCE_DELIVERY = 'BINANCE_DELIVERY'
BITDOTCOM = 'BIT.COM'
BITFLYER = 'BITFLYER'
BITGET = 'BITGET'
BITSTAMP = 'BITSTAMP'
BITTREX = 'BITTREX'
BLOCKCHAIN = 'BLOCKCHAIN'
BYBIT = 'BYBIT'
COINBASE = 'COINBASE'
CRYPTODOTCOM = "CRYPTO.COM"
DELTA = 'DELTA'
DERIBIT = 'DERIBIT'
DYDX = 'DYDX'
EXX = 'EXX'
FTX = 'FTX'
FTX_US = 'FTX_US'
FTX_TR = 'FTX_TR'
FMFW = 'FMFW'
GATEIO = 'GATEIO'
GEMINI = 'GEMINI'
HITBTC = 'HITBTC'
HUOBI = 'HUOBI'
HUOBI_DM = 'HUOBI_DM'
HUOBI_SWAP = 'HUOBI_SWAP'
INDEPENDENT_RESERVE = 'INDEPENDENT_RESERVE'
KRAKEN = 'KRAKEN'
KRAKEN_FUTURES = 'KRAKEN_FUTURES'
KUCOIN = 'KUCOIN'
OKCOIN = 'OKCOIN'
OKX = 'OKX'
PHEMEX = 'PHEMEX'
POLONIEX = 'POLONIEX'
PROBIT = 'PROBIT'
UPBIT = 'UPBIT'

# Market Data
L1_BOOK = 'l1_book'
L2_BOOK = 'l2_book'
L3_BOOK = 'l3_book'
TRADES = 'trades'
TICKER = 'ticker'
FUNDING = 'funding'
OPEN_INTEREST = 'open_interest'
LIQUIDATIONS = 'liquidations'
INDEX = 'index'
UNSUPPORTED = 'unsupported'
CANDLES = 'candles'
KLINES = 'klines'
MARKETS = 'markets'

MARKET_TYPE_FILL = "fill"
MARKET_TYPE_ORDER = "order"
MARKET_TYPE_POSITION = "position"
MARKET_TYPE_ASSET = "asset"
MARKET_TYPE_TICKER = "ticker"
MARKET_TYPE_TRADE = "trade"
MARKET_TYPE_ORDERBOOK = "orderbook"
MARKET_TYPE_KLINE = "kline"
MARKET_TYPE_KLINE_3M = "kline_3m"
MARKET_TYPE_KLINE_5M = "kline_5m"
MARKET_TYPE_KLINE_15M = "kline_15m"
MARKET_TYPE_KLINE_30M = "kline_30m"
MARKET_TYPE_KLINE_1H = "kline_1h"
MARKET_TYPE_KLINE_2H = "kline_2h"
MARKET_TYPE_KLINE_3H = "kline_3h"
MARKET_TYPE_KLINE_4H = "kline_4h"
MARKET_TYPE_KLINE_6H = "kline_6h"
MARKET_TYPE_KLINE_12H = "kline_12h"
MARKET_TYPE_KLINE_1D = "kline_1d"
MARKET_TYPE_KLINE_3D = "kline_3d"
MARKET_TYPE_KLINE_1W = "kline_1w"
MARKET_TYPE_KLINE_15D = "kline_15d"
MARKET_TYPE_KLINE_1MON = "kline_1mon"
MARKET_TYPE_KLINE_1Y = "kline_1y"

# Account Data / Authenticated Channels
ACCOUNTS = 'accounts'
BALANCES = 'balances'
POSITIONS = 'positions'
ORDERS = 'orders'
FILLS = 'fills'
PLACE_ORDER = 'place_order'
CANCEL_ORDER = 'cancel_order'
ORDER_STATUS = 'order_status'
TRADE_HISTORY = 'trade_history'
ORDER_INFO = 'order_info'
TRANSACTIONS = 'transactions'

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

BUY = 'buy'
SELL = 'sell'
BID = 'bid'
ASK = 'ask'
UND = 'undefined'
MAKER = 'maker'
TAKER = 'taker'
LONG = 'long'
SHORT = 'short'
BOTH = 'both'

LIMIT = 'limit'
MARKET = 'market'
STOP_LIMIT = 'stop-limit'
STOP_MARKET = 'stop-market'
MAKER_OR_CANCEL = 'maker-or-cancel'
FILL_OR_KILL = 'fill-or-kill'
IMMEDIATE_OR_CANCEL = 'immediate-or-cancel'
GOOD_TIL_CANCELED = 'good-til-canceled'
TRIGGER_LIMIT = 'trigger-limit'
TRIGGER_MARKET = 'trigger-market'
MARGIN_LIMIT = 'margin-limit'
MARGIN_MARKET = 'margin-market'

OPEN = 'open'
PENDING = 'pending'
FILLED = 'filled'
PARTIAL = 'partial'
CANCELLED = 'cancelled'
UNFILLED = 'unfilled'
EXPIRED = 'expired'
SUSPENDED = 'suspended'
FAILED = 'failed'
SUBMITTING = 'submitting'
CANCELLING = 'cancelling'
CLOSED = 'closed'

# Instrument Definitions

CURRENCY = 'currency'
FUTURES = 'futures'
PERPETUAL = 'perpetual'
OPTION = 'option'
OPTION_COMBO = 'option_combo'
FUTURE_COMBO = 'future_combo'
SPOT = 'spot'
MARGIN = 'margin'
SWAP = 'swap'
FUTURE = 'future'
DELIVERY = 'delivery'
CALL = 'call'
PUT = 'put'
FX = 'fx'


# HTTP methods
GET = 'GET'
DELETE = 'DELETE'
POST = 'POST'


"""
L2 Orderbook Layout
    * BID and ASK are SortedDictionaries
    * PRICE and SIZE are of type decimal.Decimal

{
    symbol: {
        BID: {
            PRICE: SIZE,
            PRICE: SIZE,
            ...
        },
        ASK: {
            PRICE: SIZE,
            PRICE: SIZE,
            ...
        }
    },
    symbol: {
        ...
    },
    ...
}


L3 Orderbook Layout
    * Similar to L2, except orders are not aggregated by price,
      each price level contains the individual orders for that price level
{
    Symbol: {
        BID: {
            PRICE: {
                order-id: amount,
                order-id: amount,
                order-id: amount
            },
            PRICE: {
                order-id: amount,
                order-id: amount,
                order-id: amount
            }
            ...
        },
        ASK: {
            PRICE: {
                order-id: amount,
                order-id: amount,
                order-id: amount
            },
            PRICE: {
                order-id: amount,
                order-id: amount,
                order-id: amount
            }
            ...
        }
    },
    Symbol: {
        ...
    },
    ...
}


Delta is in format of:

for L2 books, it is as below
for L3 books:
    * tuples will be order-id, price, size

    {
        BID: [ (price, size), (price, size), (price, size), ...],
        ASK: [ (price, size), (price, size), (price, size), ...]
    }

    For L2 books a size of 0 means the price level should be deleted.
    For L3 books, a size of 0 means the order should be deleted. If there are
    no orders at the price, the price level can be deleted.



Trading Responses

Balances:

{
    coin/fiat: {
        total: Decimal, # total amount
        available: Decimal # available for trading
    },
    ...
}


Orders:

[
    {
        order_id: str,
        symbol: str,
        side: str,
        order_type: limit/market/etc,
        price: Decimal,
        total: Decimal,
        executed: Decimal,
        pending: Decimal,
        timestamp: float,
        order_status: FILLED/PARTIAL/CANCELLED/OPEN
    },
    {...},
    ...

]


Trade history:
[{
    'price': Decimal,
    'amount': Decimal,
    'timestamp': float,
    'side': str
    'fee_currency': str,
    'fee_amount': Decimal,
    'trade_id': str,
    'order_id': str
    },
    {
        ...
    }
]

"""



