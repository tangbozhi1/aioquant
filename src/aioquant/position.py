# -*- coding:utf-8 -*-

"""
Position object.

Author: HuangTao
Date:   2018/04/22
Email:  huangtao@ifclover.com
"""

import json

from aioquant.utils import tools

#保证金模式
MARGIN_MODE_CROSSED = "crossed" #全仓
MARGIN_MODE_FIXED = "fixed" #逐仓

class Position:
    """Position object.

    Attributes:
        platform: Exchange platform name, e.g. `binance` / `bitmex`.
        account: Trading account name, e.g. `test@gmail.com`.
        strategy: Strategy name, e.g. `my_strategy`.
        symbol: Trading pair name, e.g. `ETH/BTC`.
    cryptofeed:
        self.exchange = exchange
        self.symbol = symbol
        self.position = position
        self.entry_price = entry_price
        self.side = side
        self.unrealised_pnl = unrealised_pnl
        self.timestamp = timestamp
        self.raw = raw
    """

    def __init__(self, platform=None, account=None, strategy=None, symbol=None, margin_mode=None,long_quantity=0,long_avg_qty=0,long_open_price=0,long_hold_price=0,long_liquid_price=0,long_unrealised_pnl=0,long_leverage=0,long_margin=0,short_quantity=0,short_avg_qty=0,short_open_price=0,short_hold_price=0,short_liquid_price=0,short_unrealised_pnl=0,short_leverage=0,short_margin=0,timestamp=None):
        self.platform = platform
        self.account = account
        self.strategy = strategy
        self.symbol = symbol
        self.margin_mode = margin_mode        #全仓or逐仓
        self.long_quantity = long_quantity          #多仓数量 [不能为负数]
        self.long_avg_qty = long_avg_qty        #多仓可用数量(平仓挂单会冻结相应数量) [不能为负数]
        self.long_open_price = long_open_price        #多仓开仓平均价格
        self.long_hold_price = long_hold_price       #多仓持仓平均价格(与结算有关,某些平台采用周结算制度)
        self.long_liquid_price = long_liquid_price      #多仓预估爆仓价格,逐仓模式爆仓价格单独计算(OKEX全仓模式多头和空头破产价格合并计算,也就是破产价格相同)
        self.long_unrealised_pnl = long_unrealised_pnl   #多仓未实现盈亏 [可正可负,正数代表盈利,负数代表亏损]
        self.long_leverage = long_leverage         #多仓杠杠倍数,逐仓模式下可以单独设置,全仓模式下只能统一设置
        self.long_margin = long_margin            #多仓保证金,本字段逐仓模式下意义更重要
        self.short_quantity = short_quantity         #空仓数量 [不能为负数]
        self.short_avg_qty = short_avg_qty         #空仓可用数量(平仓挂单会冻结相应数量) [不能为负数]
        self.short_open_price = short_open_price      #空仓开仓平均价格
        self.short_hold_price = short_hold_price      #空仓持仓平均价格(与结算有关,某些平台采用周结算制度)
        self.short_liquid_price = short_liquid_price    #空仓预估爆仓价格,逐仓模式爆仓价格单独计算(OKEX全仓模式多头和空头破产价格合并计算,也就是破产价格相同)
        self.short_unrealised_pnl = short_unrealised_pnl   #空仓未实现盈亏 [可正可负,正数代表盈利,负数代表亏损]
        self.short_leverage = short_leverage         #空仓杠杠倍数,逐仓模式下可以单独设置,全仓模式下只能统一设置
        self.short_margin = short_margin           #空仓保证金,本字段逐仓模式下意义更重要
        self.timestamp = timestamp  # Update timestamp(millisecond).

    def update(self, margin_mode = None,long_quantity = 0, long_avg_qty = 0, long_open_price = 0,long_hold_price = 0,long_liquid_price = 0,long_unrealised_pnl = 0,long_leverage = 0,long_margin = 0,short_quantity = 0,short_avg_qty = 0,short_open_price = 0,short_hold_price = 0,short_liquid_price = 0,short_unrealised_pnl = 0,short_leverage = 0,short_margin = 0,timestamp = None):
        self.margin_mode = margin_mode
        self.long_quantity = long_quantity
        self.long_avg_qty = long_avg_qty
        self.long_open_price = long_open_price
        self.long_hold_price = long_hold_price
        self.long_liquid_price = long_liquid_price
        self.long_unrealised_pnl = long_unrealised_pnl
        self.long_leverage = long_leverage
        self.long_margin = long_margin
        self.short_quantity = short_quantity
        self.short_avg_qty = short_avg_qty
        self.short_open_price = short_open_price
        self.short_hold_price = short_hold_price
        self.short_liquid_price = short_liquid_price
        self.short_unrealised_pnl = short_unrealised_pnl
        self.short_leverage = short_leverage
        self.short_margin = short_margin
        self.timestamp = timestamp if timestamp else tools.get_cur_timestamp_ms()

    @property
    def data(self):
        d = {
            "platform": self.platform,
            "account": self.account,
            "strategy": self.strategy,
            "symbol": self.symbol,
            "margin_mode":self.margin_mode,         #全仓or逐仓
            "long_quantity": self.long_quantity,    #多仓数量 [不能为负数]
            "long_avg_qty": self.long_avg_qty,          #多仓可用数量(平仓挂单会冻结相应数量) [不能为负数]
            "long_open_price":self.long_open_price,     #多仓开仓平均价格
            "long_hold_price":self.long_hold_price,     #多仓持仓平均价格(与结算有关,某些平台采用周结算制度)
            "long_liquid_price":self.long_liquid_price,  #多仓预估爆仓价格,逐仓模式爆仓价格单独计算(OKEX全仓模式多头和空头破产价格合并计算,也就是破产价格相同)
            "long_unrealised_pnl":self.long_unrealised_pnl, #多仓未实现盈亏 [可正可负,正数代表盈利,负数代表亏损]
            "long_leverage":self.long_leverage,      #多仓杠杠倍数,逐仓模式下可以单独设置,全仓模式下只能统一设置
            "long_margin":self.long_margin ,       #多仓保证金,本字段逐仓模式下意义更重要
            "short_quantity":self.short_quantity,      #空仓数量 [不能为负数]
            "short_avg_qty":self.short_avg_qty ,    #空仓可用数量(平仓挂单会冻结相应数量) [不能为负数]
            "short_open_price":self.short_open_price,    #空仓开仓平均价格
            "short_hold_price":self.short_hold_price ,   #空仓持仓平均价格(与结算有关,某些平台采用周结算制度)
            "short_liquid_price":self.short_liquid_price  ,  #空仓预估爆仓价格,逐仓模式爆仓价格单独计算(OKEX全仓模式多头和空头破产价格合并计算,也就是破产价格相同)
            "short_unrealised_pnl":self.short_unrealised_pnl,   #空仓未实现盈亏 [可正可负,正数代表盈利,负数代表亏损]
            "short_leverage":self.short_leverage ,     #空仓杠杠倍数,逐仓模式下可以单独设置,全仓模式下只能统一设置
            "short_margin":self.short_margin ,        #空仓保证金,本字段逐仓模式下意义更重要
            "timestamp": self.timestamp
        }
        return d

    def __str__(self):
        info = json.dumps(self.data)
        return info

    def __repr__(self):
        return str(self)
