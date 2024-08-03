# -*- coding:utf-8 -*-

"""
Symbol object.

Copyright (C) 2017-2022 Bryant Moscon - bmoscon@gmail.com
Please see the LICENSE file for the terms and conditions
associated with this software.
"""
import json
from datetime import datetime as dt, timezone
from typing import Dict, Tuple, Union

# from aioquant.const import FUTURES, FX, OPTION, PERPETUAL, SPOT, CALL, PUT, CURRENCY
from aioquant.utils import logger

class SymbolInfo:
    """
    Attributes:
        platform: Exchange platform name, e.g. binance/bitmex.
        symbol: Trading pair name, CCXT格式.
        raw_symbol: 交易所使用的交易对
        price_tick: `报价`每一跳的最小单位,也可以理解为`报价`精度或者`报价`增量
        size_tick: `下单量`每一跳的最小单位,也可以理解为`下单量`精度或者`下单量`增量
        size_limit: 最小`下单量` (`下单量`指当订单类型为`限价单`或`sell-market`时,下单接口传的'quantity')
        value_tick: `下单金额`每一跳的最小单位,也可以理解为`下单金额`精度或者`下单金额`增量
        value_limit: 最小`下单金额` (`下单金额`指当订单类型为`限价单`时,下单接口传入的(quantity * price).当订单类型为`buy-market`时,下单接口传的'quantity')
        base_currency: 交易对中的基础币种
        quote_currency: 交易对中的报价币种
        settlement_currency: 交易对中的结算币种
        symbol_type: 符号类型,"spot"=现货,"future"=期货
        is_inverse: 如果是期货的话,是否是反向合约
        multiplier: 合约乘数,合约大小
    """

    def __init__(self, platform=None, symbol=None, raw_symbol=None, price_tick:float=None, size_tick:float=None, size_limit:float=None, value_tick:float=None, value_limit:float=None, base_currency="", quote_currency="", settlement_currency="", symbol_type="spot", is_inverse=False, multiplier=1):
        self.platform = platform
        self.symbol = symbol
        self.raw_symbol = raw_symbol
        self.price_tick = price_tick
        self.size_tick = size_tick
        self.size_limit = size_limit
        self.value_tick = value_tick
        self.value_limit = value_limit
        self.base_currency = base_currency
        self.quote_currency = quote_currency
        self.settlement_currency = settlement_currency
        self.symbol_type = symbol_type
        self.is_inverse = is_inverse
        self.multiplier = multiplier

    @property
    def data(self):
        d = {
            "platform": self.platform,
            "symbol": self.symbol,
            "raw_symbol": self.raw_symbol,
            "price_tick": self.price_tick,
            "size_tick": self.size_tick,
            "size_limit": self.size_limit,
            "value_tick": self.value_tick,
            "value_limit": self.value_limit,
            "base_currency": self.base_currency,
            "quote_currency": self.quote_currency,
            "settlement_currency": self.settlement_currency,
            "symbol_type": self.symbol_type,
            "is_inverse": self.is_inverse,
            "multiplier": self.multiplier
        }
        return d

    def __str__(self):
        info = json.dumps(self.data)
        return info

    def __repr__(self):
        return str(self)


class StdSymbols(object):
    def __init__(self, data):
        self.data = data
        self.exchanges = {}

    # @property
    def clear(self):
        self.exchanges = {}

    # 反回指定交易所的交易对
    # @property
    def get(self, exchange: str) -> Tuple[Dict, Dict]:
        exchange_symbol_mapping = {value: key for key, value in self.data[exchange].items()}
        std_symbol_mapping = self.data[exchange]
        return exchange_symbol_mapping, std_symbol_mapping

    # 返回存在交易对的交易所
    # @property
    def find(self, symbol):
        ret = []
        for exchange, data in self.data.items():
            if symbol in data:
                ret.append(exchange)
        return ret

    # @property
    def set(self, exchange: str, normalized: dict, exchange_info: dict):
        self.exchanges[exchange] = {}
        self.exchanges[exchange]['std_symbol_mapping'] = normalized
        self.exchanges[exchange]['exchange_symbol_mapping'] = exchange_info

class RestExchange:
    """ 通过RestAPI获取所有交易所信息相当于load_market
    """
    def __init__(self):
        self.data = {}

    async def load_all(self):
        while True:
            try:
                from aioquant import maps
                for exchange_name, exchange_info in maps.EXCHANGE_MAP.items():
                    exchange = exchange_info()
                    markets = await exchange.load_markets(True)
                    await exchange.close()
                    symbols = {}
                    for std_symbol, exchange_symbol in markets.items():
                        symbols[std_symbol] = exchange_symbol['id']
                    self.data[exchange_name] = symbols
                    logger.info('{} markets reloaded'.format(exchange_name),caller=self)
                return self.data
                break
            except Exception as e:
                logger.error(e, caller=self)

    def __await__(self):
        return self.load_all().__await__()



