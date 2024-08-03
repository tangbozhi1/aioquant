# -*- coding:utf-8 -*-

"""
Binance Trade module.
https://github.com/binance-exchange/binance-official-api-docs/blob/master/rest-api.md

Author: HuangTao
Date:   2018/08/09
Email:  huangtao@ifclover.com
"""

import copy
import hmac
import time

from aioquant.error import Error
from aioquant.utils import tools
from aioquant.utils import logger
from aioquant.tasks import SingleTask, LoopRunTask
from aioquant.utils.decorator import async_method_locker
from aioquant.utils.web import Websocket
from ccxt.async_support.ftx import ftx
from aioquant import const
from aioquant.Gateway import ExchangeGateway,ExchangeWebsocket
from aioquant.configure import config
from aioquant.asset import Asset
from aioquant.order import Order
from aioquant.position import Position,MARGIN_MODE_CROSSED,MARGIN_MODE_FIXED
from aioquant.fill import Fill
from aioquant.symbols import SymbolInfo
from aioquant.market import Orderbook,Ticker,Trade,Kline
from decimal import Decimal
import asyncio

__all__ = ("FtxRestAPI", "FtxTrade", "FtxMarket",)


class FtxRestAPI(ftx):
    """FTX REST API client.

    Attributes:
        access_key: Account's ACCESS KEY.
        secret_key: Account's SECRET KEY.
        host: HTTP request host.
    """

    def __init__(self, config={}):
        """Initialize REST API client."""
        super(ftx, self).__init__(config)  # 引用父类的父类初始化
        # 科学上网代理
        from aioquant.configure import config
        self.aiohttp_proxy = config.proxy
        # 其他配置参数
        # self.options.update({
        #     "defaultType": const.FUTURE,
        #     "adjustForTimeDifference": "True",
        #     "recvWindow": 10000
        # })
        self.rateLimit = 20  # 异步执行周期，避免网络不通
        self.enableRateLimit = True

    # ###自定隐身函数###
    # def describe(self):
    #     return self.deep_extend(super(okex5, self).describe(), {
    #         'api': {
    #             'public': {
    #                 'get': {
    #                     'market/tickers': 1,
    #                 },
    #             },
    #             'private': {
    #                 'get': {
    #                     'account/bills': 5 / 3,
    #                 },
    #                 'post': {
    #                     'account/set-position-mode': 4,
    #                 },
    #             },
    #         },
    #     })

class FtxTrade(ExchangeGateway):
    """Binance Trade module. You can initialize trade object with some attributes in kwargs.

    Attributes:
        account: Account name for this trade exchange.
        strategy: What's name would you want to created for your strategy.
        symbol: Symbol name for your trade.
        host: HTTP request host. (default "https://api.binance.com")
        wss: Websocket address. (default "wss://stream.binance.com:9443")
        access_key: Account's ACCESS KEY.
        secret_key Account's SECRET KEY.
        order_update_callback: You can use this param to specify a async callback function when you initializing Trade
            module. `order_update_callback` is like `async def on_order_update_callback(order: Order): pass` and this
            callback function will be executed asynchronous when some order state updated.
        init_callback: You can use this param to specify a async callback function when you initializing Trade
            module. `init_callback` is like `async def on_init_callback(success: bool, **kwargs): pass`
            and this callback function will be executed asynchronous after Trade module object initialized done.
        error_callback: You can use this param to specify a async callback function when you initializing Trade
            module. `error_callback` is like `async def on_error_callback(error: Error, **kwargs): pass`
            and this callback function will be executed asynchronous when some error occur while trade module is running.
    """
    websocket_channels = {
        # 公共频道
        const.L2_BOOK: 'orderbook',   # action: partial, action: update
        const.TICKER: 'ticker',
        const.TRADES: 'trades',  # {'op': 'unsubscribe', 'channel': 'trades', 'market': 'BTC-PERP'}
        # const.MARKET: 'markets',
        # 私有频道
        const.ORDERS: 'orders',  # {'op': 'subscribe', 'channel': 'orders'}
        const.FILLS: 'fills',  # {'op': 'subscribe', 'channel': 'fills'}
        # const.ACCOUNTS: 'ftxpay'  # {'op': 'subscribe', 'channel': 'ftxpay'}
        # 需要新增无websocket的频道
        const.BALANCES: 'balances',
        # const.CANDLES: 'kline',
        const.POSITIONS: 'positions'
    }
    def __init__(self, **kwargs):
        """Initialize Trade module."""
        e = None
        if not kwargs.get("account"):
            e = Error("param account miss")
        if not kwargs.get("strategy"):
            e = Error("param strategy miss")
        if not kwargs.get("symbol"):
            e = Error("param symbol miss")
        if not kwargs.get("host"):
            kwargs["host"] = "ftx.com"
        if not kwargs.get("wss"):
            kwargs["wss"] = "wss://ftx.com/ws/"
        if not kwargs.get("access_key"):
            e = Error("param access_key miss")
        if not kwargs.get("secret_key"):
            e = Error("param secret_key miss")
        if e:
            logger.error(e, caller=self)
            SingleTask.run(kwargs["error_callback"], e)
            SingleTask.run(kwargs["init_callback"], False)
            return

        self._account = kwargs["account"]
        self._strategy = kwargs["strategy"]
        self._platform = kwargs["platform"]
        self._symbol = kwargs["symbol"]
        self._host = kwargs["host"]
        self._wss = kwargs["wss"]
        self._access_key = kwargs["access_key"]
        self._secret_key = kwargs["secret_key"]
        self._fill_update_callback = kwargs.get("fill_update_callback")
        self._order_update_callback = kwargs.get("order_update_callback")
        self._position_update_callback = kwargs.get("position_update_callback")
        self._asset_update_callback = kwargs.get("asset_update_callback")
        self._init_callback = kwargs.get("init_callback")
        self._error_callback = kwargs.get("error_callback")
        # 通过websocket实现事件驱动，但回调结果通过RestAPI获取
        self._raw_symbol = None
        self._assets = {}  # Asset data. e.g. {"BTC": {"free": "1.1", "locked": "2.2", "total": "3.3"}, ... }
        self._orders = {}  # Order data. e.g. {order_id: order, ... }
        # self._fills = {}  # Order data. e.g. {fill_id: fill, ... }
        self._symbols = {} # Order data. e.g. {symbol: symboinfo, ... }
        # Initialize our REST API client.
        self._subaccount = self._account  # 子账户
        if self._subaccount:
            self._rest_api = FtxRestAPI({"apiKey": self._access_key, "secret": self._secret_key, "hostname": self._host,
                                         "headers": {"FTX-SUBACCOUNT": self._subaccount}})  # 子账户
        else:
            self._rest_api = FtxRestAPI({"apiKey": self._access_key, "secret": self._secret_key,"hostname": self._host})  # 主账户

        SingleTask.run(self._init_rest)  # 相当于ccxt.loadmarket

    @property
    def assets(self):
        return copy.copy(self._assets)

    @property
    def orders(self):
        return copy.copy(self._orders)

    # @property
    # def fills(self):
    #     return copy.copy(self._fills)

    @property
    def symbols(self):
        return copy.copy(self._symbols)

    @property
    def rest_api(self):
        return self._rest_api

    @classmethod
    # 判断需要身份验证的订阅
    def is_authenticated_channel(self, channel: str) -> bool:
        return channel in (const.ACCOUNTS,const.BALANCES,const.ORDERS,const.FILLS,const.POSITIONS)

    async def _parse_symbols(self, info):
        syminfo = {}
        for sym, raw_sym in info.items():
            exchange = await self._rest_api.load_markets()
            data = exchange[sym]
            info = {
                "platform": self._platform,
                "symbol": data['symbol'],
                "raw_symbol": data['id'],
                "price_tick": data['precision']['price'],
                "size_tick": data['precision']['amount'],
                "size_limit": data['limits']['amount']['min'],
                "value_tick": data['contractSize'],
                "value_limit": data['limits']['cost']['min'],
                "base_currency": data['base'],
                "quote_currency": data['quote'],
                "settlement_currency": data['quote'],
                "symbol_type": data['type'],
                "is_inverse": data['inverse'],
                # "multiplier": data['info']['multiplier']
            }
            syminfo[sym] = SymbolInfo(**info)
        return syminfo

    async def _init_rest(self):
        from aioquant.symbols import StdSymbols, RestExchange
        exchanges = await RestExchange()
        exchanges_symbol = StdSymbols(exchanges)
        exchange_symbol_mapping, std_symbol_mapping = exchanges_symbol.get(self._platform)
        self._symbols = await self._parse_symbols(std_symbol_mapping)
        self._raw_symbol = std_symbol_mapping[self._symbol]

        self._ws = Websocket(self._wss, self.connected_callback, process_callback=self.process)
        LoopRunTask.register(self._send_heartbeat_msg, 10)

    async def _send_heartbeat_msg(self, *args, **kwargs):
        """Send ping to server."""
        hb = {'op': 'ping'}
        try:
            await self._ws.send(hb)
        except Exception as e:
            logger.error(e, caller=self)

    async def create_order(self, action, price, quantity, *args, **kwargs):
        """Create an order.
        Args:
            action: Trade direction, `BUY` or `SELL`.
            price: Price of each order.
            quantity: The buying or selling quantity.
            type: limit or market.

        Returns:
            order_id: Order id if created successfully, otherwise it's None.
            error: Error information, otherwise it's None.
        """
        # buy open开多，sell open开空，buy close平空，sell close平多.
        # TRADE_TYPE_BUY_OPEN = 1  # Buy open, action = BUY & quantity > 0.
        # TRADE_TYPE_SELL_OPEN = 2  # Sell open, action = SELL & quantity < 0.
        # TRADE_TYPE_SELL_CLOSE = 3  # Sell close, action = SELL & quantity > 0.
        # TRADE_TYPE_BUY_CLOSE = 4  # Buy close, action = BUY & quantity < 0.
        if float(quantity) > 0:
            if action == const.ORDER_ACTION_BUY: #开多
                trade_type = const.TRADE_TYPE_BUY_OPEN
            elif action == const.ORDER_ACTION_SELL: #平多
                trade_type = const.TRADE_TYPE_SELL_CLOSE
            else:
                return None, "action error"
        elif float(quantity) < 0:
            if action == const.ORDER_ACTION_BUY: #平空
                trade_type = const.TRADE_TYPE_BUY_CLOSE
            elif action == const.ORDER_ACTION_SELL: #开空
                trade_type = const.TRADE_TYPE_SELL_OPEN
            else:
                return None, "action error"
        else:
            return None, "quantity error"
        order_type = kwargs.get("order_type", const.ORDER_TYPE_LIMIT)
        client_order_id = kwargs.get("client_order_id")
        params = kwargs.get("params", {})
        if order_type == const.ORDER_TYPE_POST_ONLY:
            params['postOnly'] = True
            order_type = const.ORDER_TYPE_LIMIT
        if client_order_id:
            params['clientOrderId'] = client_order_id + '/' + str(trade_type)
        result = await self._rest_api.create_order(self._symbol, order_type.lower(), action.lower(), abs(float(quantity)), price, params)
        if not result:
            SingleTask.run(self._error_callback, result)
            return None, result
        order_id = str(result["info"]["id"])
        return order_id, None

    async def edit_order(self, action, *args, **kwargs):
        """Edit order's price or quantity.

        Args:
            order_id: Order id or Client order id.

            Kwargs:
                price: Order price.
                quantity: Order quantity.
        Returns:
            success: True or False.
            error: Error information, otherwise it's None.
        """
        order_id = kwargs.get("order_id",None)
        price = kwargs.get("price",None)
        quantity = kwargs.get("quantity",None)
        client_order_id = kwargs.get("client_order_id")
        order_type = kwargs.get("order_type",const.ORDER_TYPE_LIMIT)
        params = kwargs.get("params", {})
        if order_id:
            id = order_id  # 返回后的order_id不是原ID
        if order_type == const.ORDER_TYPE_POST_ONLY:
            params['postOnly'] = True
            order_type = const.ORDER_TYPE_LIMIT    
        if client_order_id:
            params['clientId'] = client_order_id # 用order.client_order_id自带trade_type
        result = await self._rest_api.edit_order(id, self._symbol, order_type.lower(), action, quantity, price=price, params=params)
        if not result:
            SingleTask.run(self._error_callback, "something wrong.....")
            return False, "something wrong....."
        return True, None


    async def revoke_order(self, *order_ids):
        """Revoke (an) order(s).

        Args:
            order_ids: Order id tuple, you can set this param to 0 or multiple items. If you set 0 param, you can cancel
                all orders for this symbol(initialized in Trade object). If you set 1 param, you can cancel an order.
                If you set multiple param, you can cancel multiple orders. Do not set param length more than 100.
                e.g. "XRP/USDT",19307203619,19307205822

        Returns:
            Success or error, see bellow.
        """
        # If len(order_ids) == 0, you will cancel all orders for this symbol(initialized in Trade object).
        if len(order_ids) == 0:
            order_infos = await self._rest_api.fetch_open_orders(self._symbol)
            if not order_infos:
                SingleTask.run(self._error_callback, order_infos)
                return False, order_infos
            for order_info in order_infos:
                _ = await self._rest_api.cancel_order(order_info["info"]["id"], self._symbol)
                if not _:
                    SingleTask.run(self._error_callback, _)
                    return False, _
            return True, None

        # If len(order_ids) == 1, you will cancel an order.
        if len(order_ids) == 1:
            _content = await self._rest_api.cancel_order(order_ids[0], self._symbol)
            if not _content:
                SingleTask.run(self._error_callback, _content)
                return order_ids[0], _content
            else:
                return order_ids[0], None

        # If len(order_ids) > 1, you will cancel multiple orders.
        if len(order_ids) > 1:
            success, error = [], []
            for order_id in order_ids:
                _ = await self._rest_api.cancel_order(order_id, self._symbol)
                if not _:
                    SingleTask.run(self._error_callback, _)
                    error.append((order_id, _))
                else:
                    success.append(order_id)
            return success, error

    async def get_open_order_ids(self):
        """Get open order id list.
        """
        success = await self._rest_api.fetch_open_orders(self._symbol)
        if not success:
            SingleTask.run(self._error_callback, success)
            return None, success
        else:
            order_ids = []
            for order_info in success:
                order_id = str(order_info["info"]["id"])
                order_ids.append(order_id)
            return order_ids, None

    async def generate_token(self):
        ts = int(time.time() * 1000)
        msg = {
            'op': 'login',
            'args':
            {
                'key': self._access_key,
                'sign': hmac.new(self._secret_key.encode(), f'{ts}websocket_login'.encode(), 'sha256').hexdigest(),
                'time': ts,
            }
        }
        if self._subaccount:
            msg['args']['subaccount'] = self._subaccount
        await self._ws.send(msg)

    async def subscribe(self, subscription):
        for chan in subscription:
            # 根据机器配置,有些频道不订阅,对自动订阅的没作用
            # if chan == self.std_channel_to_raw_channel(const.L2_BOOK) and not self._orderbook_update_callback:
            #     continue
            # if chan == self.std_channel_to_raw_channel(const.TICKER) and not self._ticker_update_callback:
            #     continue
            # if chan == self.std_channel_to_raw_channel(const.TRADES) and not self._trade_update_callback:
            #     continue
            # if chan == self.std_channel_to_raw_channel(const.ORDERS) and not self._order_update_callback:
            #     continue
            # if chan == self.std_channel_to_raw_channel(const.FILLS) and not self._fill_update_callback:
            #     continue
            if chan == self.std_channel_to_raw_channel(const.BALANCES) and not self._asset_update_callback:
                continue
            if chan == self.std_channel_to_raw_channel(const.POSITIONS) and not self._position_update_callback:
                continue

            # 没有websokcet,自定需要restAPI的及过滤(过滤掉websocket channel 中有并且不需要的chan
            if chan == self.std_channel_to_raw_channel(const.BALANCES):
                SingleTask.run(self._fetch_balances)
                continue

            # if chan == self.std_channel_to_raw_channel(const.MARKET):
            #     continue

            # 没有websokcet,自定需要restAPI的及过滤(过滤掉websocket channel 中有并且不需要的chan
            if chan == self.std_channel_to_raw_channel(const.POSITIONS):
                SingleTask.run(self._fetch_position, self.raw_symbol_to_std_symbol(self._raw_symbol))
                continue

            if self.is_authenticated_channel(self.raw_channel_to_std_channel(chan)):
                await self._ws.send(
                    {
                        "op": "subscribe",
                        "channel": chan
                    }
                )

    async def connected_callback(self):
        if any(self.is_authenticated_channel(chan) for chan in self.websocket_channels.keys()):
            if not self._access_key or not self._secret_key:
                raise ValueError("Authenticated channel subscribed to, but no auth keys provided")
            await self.generate_token()

        raw_channels = list(set([self.std_channel_to_raw_channel(chan) for chan in self.websocket_channels.keys()]))
        sub = {chan: self._raw_symbol for chan in raw_channels}
        await self.subscribe(sub)
        SingleTask.run(self._init_callback, True)
        
    @async_method_locker("FtxTrade.process.locker")
    async def process(self, msg):
        """After websocket connection created successfully, pull back all open order information."""
        if 'type' in msg:
            if msg['type'] == 'subscribed':
                if 'market' in msg:
                    logger.info('{}: Subscribed to {} channel for {}'.format(self._platform, msg['channel'], msg['market']), caller=self)
                else:
                    logger.info('{}: Subscribed to {} channel'.format(self._platform, msg['channel']), caller=self)
            elif msg['type'] == 'error':
                logger.error('{}: Received error message {}'.format(self._platform, msg), caller=self)
                # raise Exception('Error from %s: %s', self._platform, msg)
            elif 'data' in msg:
                if msg['channel'] == self.std_channel_to_raw_channel(const.ORDERS):
                    await self._order(msg)
                elif msg['channel'] == self.std_channel_to_raw_channel(const.FILLS):
                    await self._fill(msg)
                # elif msg['channel'] == self.std_channel_to_raw_channel(const.TRADES):
                #     await self._trade(msg)
                # elif msg['channel'] == self.std_channel_to_raw_channel(const.TICKER):
                #     await self._ticker(msg)
                # elif msg['channel'] == self.std_channel_to_raw_channel(const.L2_BOOK):
                #     await self._book(msg)
                else:
                    logger.warn("{}: Invalid message type {}".format(self._platform, msg), caller=self)
        else:
            logger.warn("{}: Invalid message type {}".format(self._platform, msg), caller=self)

    async def _fetch_balances(self, *args, **kwargs):
        while True:
            await asyncio.sleep(20)  # 请求限制
            try:
                balance = await self._rest_api.fetch_balance()
                await self._process_asset(balance)
            except Exception as e:
                logger.error(e, caller=self)

    async def _process_asset(self, info):
        # {
        #     'info': {
        #         'success': True,
        #         'result': [
        #             {
        #                 'coin': 'ETH',
        #                 'total': '0.0',
        #                 'free': '0.0',
        #                 'availableForWithdrawal': '0.0',
        #                 'availableWithoutBorrow': '0.0',
        #                 'usdValue': '0.0',
        #                 'spotBorrow': '0.0'
        #             },
        #             {
        #                 'coin': 'USD',
        #                 'total': '5.0',
        #                 'free': '5.0',
        #                 'availableForWithdrawal': '5.0',
        #                 'availableWithoutBorrow': '5.0',
        #                 'usdValue': '5.0',
        #                 'spotBorrow': '0.0'
        #             }
        #         ]
        #     },
        #     'ETH': {
        #         'free': 0.0,
        #         'used': 0.0,
        #         'total': 0.0
        #     },
        #     'USD': {
        #         'free': 5.0,
        #         'used': 0.0,
        #         'total': 5.0
        #     },
        #     'free': {
        #         'ETH': 0.0,
        #         'USD': 5.0
        #     },
        #     'used': {
        #         'ETH': 0.0,
        #         'USD': 0.0
        #     },
        #     'total': {
        #         'ETH': 0.0,
        #         'USD': 5.0
        #     }
        # }
        assets = {}
        for data in info['info']['result']:
            total = Decimal(data['total'])
            free = Decimal(data['free'])
            locked = total - free
            assets[data['coin']] = {
                "total": "%.8f" % total,
                "free": "%.8f" % free,
                "locked": "%.8f" % locked
            }
        if assets == self._assets:
            update = False
        else:
            update = True
        if hasattr(self._assets, "assets") is False:
            info = {
                "platform": self._platform,
                "account": self._account,
                "assets": assets,
                "timestamp": tools.get_cur_timestamp_ms(),
                "update": update
            }
            asset = Asset(**info)
            self._assets = asset

        else:
            for sym in assets: # 相当于for symbol in assets.keys():
                self._assets.assets.update({
                    sym: assets[sym]
                })
            self._assets.timestamp = tools.get_cur_timestamp_ms()

        SingleTask.run(self._on_asset_update_callback, self._assets)

    async def _fetch_position(self, symbol, **kwargs):
        while True:
            await asyncio.sleep(15)  # 请求限制
            try:
                positions = await self._rest_api.fetch_positions([symbol])
                await self._process_positions(positions)
            except Exception as e:
                logger.error(e, caller=self)

    async def _process_positions(self, info):
        for data in info:
            update = False
            position = Position(self._platform, self._account, self._strategy, self._symbol)
            if not position.timestamp:
                update = True
                position.update()
            if Decimal(data['info']['netSize']) > 0:
                if float(position.long_quantity) != float(data['contracts']):
                    update = True
                    position.update(margin_mode=MARGIN_MODE_CROSSED if data['marginMode']=="cross" else MARGIN_MODE_FIXED,long_quantity=data['contracts'],long_avg_qty=str(Decimal(position.long_quantity) - Decimal(data['info']['shortOrderSize']) if Decimal(data['info']['shortOrderSize']) < Decimal(position.long_quantity) else 0),long_open_price=data['info']['recentAverageOpenPrice'],long_hold_price=data['info']['recentBreakEvenPrice'],long_liquid_price=data['info']['estimatedLiquidationPrice'],long_unrealised_pnl=data['info']['recentPnl'],long_leverage=data['leverage'],long_margin=data['info']['collateralUsed'])
            elif Decimal(data['info']['netSize']) < 0:
                if float(position.short_quantity) != float(data['contracts']):
                    update = True
                    position.update(MARGIN_MODE_CROSSED if data['marginMode']=="cross" else MARGIN_MODE_FIXED,short_quantity=data['contracts'],short_avg_qty=str(Decimal(position.short_quantity) - Decimal(data['info']['longOrderSize']) if Decimal(data['info']['longOrderSize']) < Decimal(position.short_quantity) else 0),short_open_price=data['info']['recentAverageOpenPrice'],short_hold_price=data['info']['recentBreakEvenPrice'],short_liquid_price=data['info']['estimatedLiquidationPrice'],short_unrealised_pnl=data['info']['recentPnl'],short_leverage=data['leverage'],short_margin=data['info']['collateralUsed'])
            elif Decimal(data['info']['netSize']) == 0:
                if position.long_quantity != 0 or position.short_quantity != 0:
                    update = True
                    position.update()

            # 此处与父类不同
            if not update or not self._position_update_callback:
                return

            SingleTask.run(self._on_position_update_callback, position)

    def status(self, trade_quantity, remain, quantity, status_info):
        if status_info == "new":
            return const.ORDER_STATUS_SUBMITTED
        elif status_info == "open":
            if float(remain) < float(quantity):
                return const.ORDER_STATUS_PARTIAL_FILLED
            else:
                return const.ORDER_STATUS_SUBMITTED
        elif status_info == "closed":
            if float(trade_quantity) < float(quantity):
                return const.ORDER_STATUS_CANCELED
            else:
                return const.ORDER_STATUS_FILLED
        else:
            logger.warn("unknown status:", status_info, caller=self)
            SingleTask.run(self._error_callback, "order status error.")
            return

    async def _order(self, msg: dict):
        """
        example message:
        {
            "channel": "orders",
            "data": {
                "id": 24852229,
                "clientId": null,
                "market": "XRP-PERP",
                "type": "limit",
                "side": "buy",
                "size": 42353.0,
                "price": 0.2977,
                "reduceOnly": false,
                "ioc": false,
                "postOnly": false,
                "status": "closed",
                "filledSize": 0.0,
                "remainingSize": 0.0,
                "avgFillPrice": 0.2978
            },
            "type": "update"
        }
        """
        pair = self.raw_symbol_to_std_symbol(msg['data']['market'])
        order = self._orders.get(msg['data']['id'])
        if not order:
            info = {
                "platform": self._platform,
                "account": self._account,
                "strategy": self._strategy,
                "symbol": pair,
                "order_id": str(msg['data']['id']),
                "client_order_id": str(msg['data']['clientId']),
                "action": const.ORDER_ACTION_BUY if msg['data']['side'] == 'buy' else const.ORDER_ACTION_SELL,
                "order_type": const.ORDER_TYPE_LIMIT if msg['data']['type'] == "limit" else const.ORDER_TYPE_MARKET,
                # "order_price_type": None,
                # "ctime": None,
            }
            order = Order(**info)
            self._orders[msg['data']['id']] = order
        order.remain = str(msg['data']['remainingSize'])
        order.avg_price = str(msg['data']['avgFillPrice'])
        order.trade_type = const.TRADE_TYPE_NONE if len(order.client_order_id.split("/")[-1]) > 1 else order.client_order_id.split("/")[-1]
        order.price = str(msg['data']['price'])
        order.quantity = str(msg['data']['size'])
        order.utime = tools.get_cur_timestamp_ms()
        order.status = self.status(Decimal(msg['data']['filledSize']), Decimal(msg['data']['remainingSize']), Decimal(msg['data']['size']), msg['data']['status'])
        if order.status in [const.ORDER_STATUS_FAILED, const.ORDER_STATUS_CANCELED, const.ORDER_STATUS_FILLED]:
            self._orders.pop(msg['data']['id'])

        SingleTask.run(self._on_order_update_callback, order)

    async def _fill(self, msg: dict):
        """
        example message:
        {
            "channel": "fills",
            "data": {
                "fee": 78.05799225,
                "feeRate": 0.0014,
                "future": "BTC-PERP",
                "id": 7828307,
                "liquidity": "taker",
                "market": "BTC-PERP",
                "orderId": 38065410,
                "tradeId": 19129310,
                "price": 3723.75,
                "side": "buy",
                "size": 14.973,
                "time": "2019-05-07T16:40:58.358438+00:00",
                "type": "order"
            },
            "type": "update"
        }
        """
        pair = self.raw_symbol_to_std_symbol(msg['data']['market'])
        info = {
            "platform": self._platform,
            "account": self._account,
            "strategy": self._strategy,
            "symbol": pair,
            "fill_id": msg['data']['id'],
            "order_id": msg['data']['orderId'],
            # "trade_type": None,   # websocket没有字段
            # "liquidity_price": None,
            "action": const.ORDER_ACTION_BUY if msg['data']["side"] == "buy" else const.ORDER_ACTION_SELL,
            "price": msg['data']['price'],
            "quantity": msg['data']['size'],
            "role": const.LIQUIDITY_TYPE_TAKER if msg['data']["liquidity"] == "taker" else const.LIQUIDITY_TYPE_MAKER,
            "fee": str(msg['data']['fee']),  # "_" + data['info']['feeCurrency'] websocket没有字段
            "ctime": tools.utctime_str_to_ms(msg['data']['time'], "%Y-%m-%dT%H:%M:%S.%f+00:00")
        }
        fill = Fill(**info)
        # self._fills[pair] = fill
        # fill 调用父类的回调函数
        SingleTask.run(self._on_fill_update_callback, fill)

class FtxMarket(ExchangeWebsocket):
    """Ftx Market module.
    """
    websocket_channels = {
        # 公共频道
        const.L2_BOOK: 'orderbook',   # action: partial, action: update
        const.TICKER: 'ticker',
        const.TRADES: 'trades',  # {'op': 'unsubscribe', 'channel': 'trades', 'market': 'BTC-PERP'}
        # const.MARKET: 'markets',
        # 私有频道
        const.ORDERS: 'orders',  # {'op': 'subscribe', 'channel': 'orders'}
        const.FILLS: 'fills',  # {'op': 'subscribe', 'channel': 'fills'}
        # const.ACCOUNTS: 'ftxpay'  # {'op': 'subscribe', 'channel': 'ftxpay'}
        # 需要新增无websocket的频道
        const.BALANCES: 'balances',
        # const.CANDLES: 'kline',  # api请求K线超限，只能通过tick合成
        const.POSITIONS: 'positions'
    }
    def __init__(self, **kwargs):
        """Initialize Market module."""
        e = None
        if not kwargs.get("account"):
            e = Error("param account miss")
        if not kwargs.get("host"):
            kwargs["host"] = "ftx.com"
        if not kwargs.get("wss"):
            kwargs["wss"] = "wss://ftx.com/ws/"
        if not kwargs.get("access_key"):
            e = Error("param access_key miss")
        if not kwargs.get("secret_key"):
            e = Error("param secret_key miss")
        if e:
            logger.error(e, caller=self)
            SingleTask.run(kwargs["error_callback"], e)
            SingleTask.run(kwargs["init_callback"], False)
            return

        self._account = kwargs["account"]
        self._platform = kwargs["platform"]
        self._host = kwargs["host"]
        self._wss = kwargs["wss"]
        self._access_key = kwargs["access_key"]
        self._secret_key = kwargs["secret_key"]
        self._fill_update_callback = kwargs.get("fill_update_callback")
        self._order_update_callback = kwargs.get("order_update_callback")
        self._position_update_callback = kwargs.get("position_update_callback")
        self._asset_update_callback = kwargs.get("asset_update_callback")
        self._kline_update_callback = kwargs.get("kline_update_callback")
        self._orderbook_update_callback = kwargs.get("orderbook_update_callback")
        self._trade_update_callback = kwargs.get("trade_update_callback")
        self._ticker_update_callback = kwargs.get("ticker_update_callback")
        self._init_callback = kwargs.get("init_callback")
        self._error_callback = kwargs.get("error_callback")
        # 通过websocket实现事件驱动，但回调结果通过websocket获取
        self._assets = {}  # Asset data. e.g. {"BTC": {"free": "1.1", "locked": "2.2", "total": "3.3"}, ... }
        self._orders = {}  # Order data. e.g. {order_id: order, ... }
        # self._fills = {}  # Order data. e.g. {fill_id: fill, ... }
        self._symbols = {}  # Order data. e.g. {symbol: symboinfo, ... }
        # self._klines = {}
        self._orderbooks = {}
        # self._trades = {}
        # self._tickers = {}
        # Initialize our REST API client.
        self._subaccount = self._account  # 子账户
        if self._subaccount:
            self._rest_api = FtxRestAPI({"apiKey": self._access_key, "secret": self._secret_key, "hostname": self._host,
                                         "headers": {"FTX-SUBACCOUNT": self._subaccount}})  # 子账户
        else:
            self._rest_api = FtxRestAPI({"apiKey": self._access_key, "secret": self._secret_key,"hostname": self._host})  # 主账户

        SingleTask.run(self._init_rest)  # 相当于ccxt.loadmarket

    @property
    def assets(self):
        return copy.copy(self._assets)

    @property
    def orders(self):
        return copy.copy(self._orders)

    # @property
    # def fills(self):
    #     return copy.copy(self._fills)

    @property
    def symbols(self):
        return copy.copy(self._symbols)

    @property
    def orderbooks(self):
        return copy.copy(self._orderbooks)

    # @property
    # def klines(self):
    #     return copy.copy(self._klines)
    #
    # @property
    # def trades(self):
    #     return copy.copy(self._trades)
    #
    # @property
    # def tickers(self):
    #     return copy.copy(self._tickers)

    @property
    def rest_api(self):
        return self._rest_api

    @classmethod
    # 判断需要身份验证的订阅
    def is_authenticated_channel(self, channel: str) -> bool:
        return channel in (const.ACCOUNTS,const.BALANCES,const.ORDERS,const.FILLS,const.POSITIONS)

    async def _parse_symbols(self, info):
        syminfo = {}
        for sym, raw_sym in info.items():
            exchange = await self._rest_api.load_markets()
            data = exchange[sym]
            info = {
                "platform": self._platform,
                "symbol": data['symbol'],
                "raw_symbol": data['id'],
                "price_tick": data['precision']['price'],
                "size_tick": data['precision']['amount'],
                "size_limit": data['limits']['amount']['min'],
                "value_tick": data['contractSize'],
                "value_limit": data['limits']['cost']['min'],
                "base_currency": data['base'],
                "quote_currency": data['quote'],
                "settlement_currency": data['quote'],
                "symbol_type": data['type'],
                "is_inverse": data['inverse'],
                # "multiplier": data['info']['multiplier']
            }
            syminfo[sym] = SymbolInfo(**info)
        return syminfo

    async def _init_rest(self):
        from aioquant.symbols import StdSymbols, RestExchange
        exchanges = await RestExchange()
        exchanges_symbol = StdSymbols(exchanges)
        exchange_symbol_mapping, std_symbol_mapping = exchanges_symbol.get(self._platform)
        self._symbols = await self._parse_symbols(std_symbol_mapping)

        # 根据机器配置筛选
        if config.white_symbol:
            self._symbols = {symbol: value for symbol, value in self._symbols.items() if
                             symbol in config.white_symbol}
        self._symbols = {symbol: value for symbol, value in self._symbols.items() if
                         symbol not in config.black_symbol}

        self._ws = Websocket(self._wss, self.connected_callback, process_callback=self.process)
        LoopRunTask.register(self._send_heartbeat_msg, 10)

    async def _send_heartbeat_msg(self, *args, **kwargs):
        """Send ping to server."""
        hb = {'op': 'ping'}
        try:
            await self._ws.send(hb)
        except Exception as e:
            logger.error(e, caller=self)

    async def generate_token(self):
        ts = int(time.time() * 1000)
        msg = {
            'op': 'login',
            'args':
            {
                'key': self._access_key,
                'sign': hmac.new(self._secret_key.encode(), f'{ts}websocket_login'.encode(), 'sha256').hexdigest(),
                'time': ts,
            }
        }
        if self._subaccount:
            msg['args']['subaccount'] = self._subaccount
        await self._ws.send(msg)

    async def subscribe(self, subscription):
        for chan in subscription:
            # 根据机器配置,有些频道不订阅,对自动订阅的没作用
            if chan == self.std_channel_to_raw_channel(const.L2_BOOK) and not self._orderbook_update_callback:
                continue
            if chan == self.std_channel_to_raw_channel(const.TICKER) and not self._ticker_update_callback:
                continue
            if chan == self.std_channel_to_raw_channel(const.TRADES) and not self._trade_update_callback:
                continue
            if chan == self.std_channel_to_raw_channel(const.ORDERS) and not self._order_update_callback:
                continue
            if chan == self.std_channel_to_raw_channel(const.FILLS) and not self._fill_update_callback:
                continue
            if chan == self.std_channel_to_raw_channel(const.BALANCES) and not self._asset_update_callback:
                continue
            if chan == self.std_channel_to_raw_channel(const.POSITIONS) and not self._position_update_callback:
                continue

            # 没有websokcet,自定需要restAPI的及过滤(过滤掉websocket channel 中有并且不需要的chan
            if chan == self.std_channel_to_raw_channel(const.BALANCES):
                SingleTask.run(self._fetch_balances)
                continue

            # if chan == self.std_channel_to_raw_channel(const.MARKET):
            #     continue
            for symbol in subscription[chan]:
                # 没有websokcet,自定需要restAPI的及过滤(过滤掉websocket channel 中有并且不需要的chan（最好不用restAPI要出问题
                if chan == self.std_channel_to_raw_channel(const.POSITIONS):
                    SingleTask.run(self._fetch_position, symbol)
                    continue

                # 有Websocket的频道
                # {'op': 'subscribe', 'channel': 'trades', 'market': 'BTC-PERP'} 公共
                # {'op': 'subscribe', 'channel': 'orders'}.  私有
                if not self.is_authenticated_channel(self.raw_channel_to_std_channel(chan)):
                    await self._ws.send(
                        {
                            "op": "subscribe",
                            "channel": chan,
                            "market": self.std_symbol_to_raw_symbol(symbol)
                        }
                    )
            # 因为position在上面没跳出整循环，这里再跳出云
            if chan == self.std_channel_to_raw_channel(const.POSITIONS):
                continue

            if self.is_authenticated_channel(self.raw_channel_to_std_channel(chan)):
                await self._ws.send(
                    {
                        "op": "subscribe",
                        "channel": chan
                    }
                )

    async def connected_callback(self):
        if any(self.is_authenticated_channel(chan) for chan in self.websocket_channels.keys()):
            if not self._access_key or not self._secret_key:
                raise ValueError("Authenticated channel subscribed to, but no auth keys provided")
            await self.generate_token()
        raw_channels = list(set([self.std_channel_to_raw_channel(chan) for chan in self.websocket_channels.keys()]))
        sub = {chan: self._symbols for chan in raw_channels}
        await self.subscribe(sub)
        SingleTask.run(self._init_callback, True)
        
    @async_method_locker("FtxMarket.process.locker")
    async def process(self, msg):
        """
        {'type': 'pong'}
        {'type': 'subscribed', 'channel': 'fills'}
        {'type': 'subscribed', 'channel': 'orderbook', 'market': 'ETH-PERP'}
        {'channel': 'ticker', 'market': 'ETH-PERP', 'type': 'update', 'data': {'bid': 1326.4, 'ask': 1326.5, 'bidSize': 136.234, 'askSize': 79.34, 'last': 1326.5, 'time': 1664011324.2990837}}
        """
        if 'type' in msg:
            if msg['type'] == 'subscribed':
                if 'market' in msg:
                    logger.info('{}: Subscribed to {} channel for {}'.format(self._platform, msg['channel'], msg['market']), caller=self)
                else:
                    logger.info('{}: Subscribed to {} channel'.format(self._platform, msg['channel']), caller=self)
            elif msg['type'] == 'error':
                logger.error('{}: Received error message {}'.format(self._platform, msg), caller=self)
                # raise Exception('Error from %s: %s', self._platform, msg)
            elif 'data' in msg:
                if msg['channel'] == self.std_channel_to_raw_channel(const.ORDERS):
                    await self._order(msg)
                elif msg['channel'] == self.std_channel_to_raw_channel(const.FILLS):
                    await self._fill(msg)
                elif msg['channel'] == self.std_channel_to_raw_channel(const.TRADES):
                    await self._trade(msg)
                elif msg['channel'] == self.std_channel_to_raw_channel(const.TICKER):
                    await self._ticker(msg)
                elif msg['channel'] == self.std_channel_to_raw_channel(const.L2_BOOK):
                    await self._book(msg)
                else:
                    logger.warn("{}: Invalid message type {}".format(self._platform, msg), caller=self)
        else:
            logger.warn("{}: Invalid message type {}".format(self._platform, msg), caller=self)

    # # API请求常常超限，只能tick合成
    # async def _fetch_candles(self, symbol):
    #     while True:
    #         try:
    #             # kline = await self._rest_api.publicGetMarketsMarketNameCandles(symbol)   # 私有方法symbol为交易所原生
    #             await asyncio.sleep(5)  # 请求限制
    #             kline = await self._rest_api.public_get_markets_market_name_candles({'market_name': symbol, 'resolution': 60})   # 私有方法
    #             await self._process_kline(kline, symbol)
    #             # break
    #         except Exception as e:
    #             logger.error(e, caller=self)
    # 
    # async def _process_kline(self, msg, pair):
    #     # {
    #     #     "success": true,
    #     #     "result": [
    #     #         {
    #     #             "close": 11055.25,
    #     #             "high": 11089.0,
    #     #             "low": 11043.5,
    #     #             "open": 11059.25,
    #     #             "startTime": "2019-06-24T17:15:00+00:00",
    #     #             "volume": null
    #     #         },
    #     #     ]
    #     # }
    # 
    #     for data in msg['result']:
    #         info = {
    #             "platform": self._platform,
    #             "symbol": pair,
    #             "start": data['startTime'],
    #             # "stop": None,
    #             "open": data['open'],
    #             "high": data['high'],
    #             "low": data['low'],
    #             "close": data['close'],
    #             "volume": data['volume'],
    #             "timestamp": tools.get_cur_timestamp_ms(),
    #             "kline_type": const.MARKET_TYPE_KLINE
    #          }
    #         kline = Kline(**info)
    #         # self._klines[pair] = kline
    #         SingleTask.run(self._on_kline_update_callback, kline)

    async def _fetch_balances(self, *args, **kwargs):
        while True:
            await asyncio.sleep(20)  # 请求限制
            try:
                balance = await self._rest_api.fetch_balance()
                await self._process_asset(balance)
            except Exception as e:
                logger.error(e, caller=self)

    async def _process_asset(self, info):
        # {
        #     'info': {
        #         'success': True,
        #         'result': [
        #             {
        #                 'coin': 'ETH',
        #                 'total': '0.0',
        #                 'free': '0.0',
        #                 'availableForWithdrawal': '0.0',
        #                 'availableWithoutBorrow': '0.0',
        #                 'usdValue': '0.0',
        #                 'spotBorrow': '0.0'
        #             },
        #             {
        #                 'coin': 'USD',
        #                 'total': '5.0',
        #                 'free': '5.0',
        #                 'availableForWithdrawal': '5.0',
        #                 'availableWithoutBorrow': '5.0',
        #                 'usdValue': '5.0',
        #                 'spotBorrow': '0.0'
        #             }
        #         ]
        #     },
        #     'ETH': {
        #         'free': 0.0,
        #         'used': 0.0,
        #         'total': 0.0
        #     },
        #     'USD': {
        #         'free': 5.0,
        #         'used': 0.0,
        #         'total': 5.0
        #     },
        #     'free': {
        #         'ETH': 0.0,
        #         'USD': 5.0
        #     },
        #     'used': {
        #         'ETH': 0.0,
        #         'USD': 0.0
        #     },
        #     'total': {
        #         'ETH': 0.0,
        #         'USD': 5.0
        #     }
        # }
        assets = {}
        for data in info['info']['result']:
            total = Decimal(data['total'])
            free = Decimal(data['free'])
            locked = total - free
            assets[data['coin']] = {
                "total": "%.8f" % total,
                "free": "%.8f" % free,
                "locked": "%.8f" % locked
            }
        if assets == self._assets:
            update = False
        else:
            update = True
        if hasattr(self._assets, "assets") is False:
            info = {
                "platform": self._platform,
                "account": self._account,
                "assets": assets,
                "timestamp": tools.get_cur_timestamp_ms(),
                "update": update
            }
            asset = Asset(**info)
            self._assets = asset

        else:
            for sym in assets: # 相当于for symbol in assets.keys():
                self._assets.assets.update({
                    sym: assets[sym]
                })
            self._assets.timestamp = tools.get_cur_timestamp_ms()

        SingleTask.run(self._on_asset_update_callback, self._assets)

    async def _fetch_position(self, symbol, **kwargs):
        while True:
            await asyncio.sleep(15)  # 请求限制
            try:
                positions = await self._rest_api.fetch_positions([symbol])
                await self._process_positions(positions)
            except Exception as e:
                logger.error(e, caller=self)

    async def _process_positions(self, info):
        for data in info:
            update = False
            position = Position(self._platform, self._account, data['symbol'])
            if not position.timestamp:
                update = True
                position.update()
            if Decimal(data['info']['netSize']) > 0:
                if float(position.long_quantity) != float(data['contracts']):
                    update = True
                    position.update(
                        margin_mode=MARGIN_MODE_CROSSED if data['marginMode'] == "cross" else MARGIN_MODE_FIXED,
                        long_quantity=data['contracts'], long_avg_qty=str(
                            Decimal(position.long_quantity) - Decimal(data['info']['shortOrderSize']) if Decimal(
                                data['info']['shortOrderSize']) < Decimal(position.long_quantity) else 0),
                        long_open_price=data['info']['recentAverageOpenPrice'],
                        long_hold_price=data['info']['recentBreakEvenPrice'],
                        long_liquid_price=data['info']['estimatedLiquidationPrice'],
                        long_unrealised_pnl=data['info']['recentPnl'], long_leverage=data['leverage'],
                        long_margin=data['info']['collateralUsed'])
            elif Decimal(data['info']['netSize']) < 0:
                if float(position.short_quantity) != float(data['contracts']):
                    update = True
                    position.update(MARGIN_MODE_CROSSED if data['marginMode'] == "cross" else MARGIN_MODE_FIXED,
                                    short_quantity=data['contracts'], short_avg_qty=str(
                            Decimal(position.short_quantity) - Decimal(data['info']['longOrderSize']) if Decimal(
                                data['info']['longOrderSize']) < Decimal(position.short_quantity) else 0),
                                    short_open_price=data['info']['recentAverageOpenPrice'],
                                    short_hold_price=data['info']['recentBreakEvenPrice'],
                                    short_liquid_price=data['info']['estimatedLiquidationPrice'],
                                    short_unrealised_pnl=data['info']['recentPnl'], short_leverage=data['leverage'],
                                    short_margin=data['info']['collateralUsed'])
            elif Decimal(data['info']['netSize']) == 0:
                if position.long_quantity != 0 or position.short_quantity != 0:
                    update = True
                    position.update()

            # 此处与父类不同
            if not update or not self._position_update_callback:
                return

            SingleTask.run(self._on_position_update_callback, position)

    async def _order(self, msg: dict):
        """
        example message:
        {
            "channel": "orders",
            "data": {
                "id": 24852229,
                "clientId": null,
                "market": "XRP-PERP",
                "type": "limit",
                "side": "buy",
                "size": 42353.0,
                "price": 0.2977,
                "reduceOnly": false,
                "ioc": false,
                "postOnly": false,
                "status": "closed",
                "filledSize": 0.0,
                "remainingSize": 0.0,
                "avgFillPrice": 0.2978
            },
            "type": "update"
        }
        """
        pair = self.raw_symbol_to_std_symbol(msg['data']['market'])
        order = self._orders.get(msg['data']['id'])
        if not order:
            info = {
                "platform": self._platform,
                "account": self._account,
                "symbol": pair,
                "order_id": str(msg['data']['id']),
                "client_order_id": str(msg['data']['clientId']),
                "action": const.ORDER_ACTION_BUY if msg['data']['side'] == 'buy' else const.ORDER_ACTION_SELL,
                "order_type": const.ORDER_TYPE_LIMIT if msg['data']['type'] == "limit" else const.ORDER_TYPE_MARKET,
                # "order_price_type": None,
                # "ctime": None,
            }
            order = Order(**info)
            self._orders[msg['data']['id']] = order
        order.remain = str(msg['data']['remainingSize'])
        order.avg_price = str(msg['data']['avgFillPrice'])
        order.trade_type = const.TRADE_TYPE_NONE if len(order.client_order_id.split("/")[-1]) > 1 else order.client_order_id.split("/")[-1]
        order.price = str(msg['data']['price'])
        order.quantity = str(msg['data']['size'])
        order.utime = tools.get_cur_timestamp_ms()
        order.status = self.status(Decimal(msg['data']['filledSize']), Decimal(msg['data']['remainingSize']), Decimal(msg['data']['size']), msg['data']['status'])
        if order.status in [const.ORDER_STATUS_FAILED, const.ORDER_STATUS_CANCELED, const.ORDER_STATUS_FILLED]:
            self._orders.pop(msg['data']['id'])

        SingleTask.run(self._on_order_update_callback, order)

    async def _fill(self, msg: dict):
        """
        example message:
        {
            "channel": "fills",
            "data": {
                "fee": 78.05799225,
                "feeRate": 0.0014,
                "future": "BTC-PERP",
                "id": 7828307,
                "liquidity": "taker",
                "market": "BTC-PERP",
                "orderId": 38065410,
                "tradeId": 19129310,
                "price": 3723.75,
                "side": "buy",
                "size": 14.973,
                "time": "2019-05-07T16:40:58.358438+00:00",
                "type": "order"
            },
            "type": "update"
        }
        """
        pair = self.raw_symbol_to_std_symbol(msg['data']['market'])
        info = {
            "platform": self._platform,
            "account": self._account,
            "symbol": pair,
            "fill_id": msg['data']['id'],
            "order_id": msg['data']['orderId'],
            # "trade_type": None,   # websocket没有字段
            # "liquidity_price": None,
            "action": const.ORDER_ACTION_BUY if msg['data']["side"] == "buy" else const.ORDER_ACTION_SELL,
            "price": msg['data']['price'],
            "quantity": msg['data']['size'],
            "role": const.LIQUIDITY_TYPE_TAKER if msg['data']["liquidity"] == "taker" else const.LIQUIDITY_TYPE_MAKER,
            "fee": str(msg['data']['fee']),  # "_" + data['info']['feeCurrency'] websocket没有字段
            "ctime": tools.utctime_str_to_ms(msg['data']['time'], "%Y-%m-%dT%H:%M:%S.%f+00:00")
        }
        fill = Fill(**info)
        # self._fills[pair] = fill
        # fill 调用父类的回调函数
        SingleTask.run(self._on_fill_update_callback, fill)

    async def _book(self, msg: dict):
        """
        example messages:

        snapshot:
        {"channel": "orderbook", "market": "BTC/USD", "type": "partial", "data": {"time": 1564834586.3382702,
        "checksum": 427503966, "bids": [[10717.5, 4.092], ...], "asks": [[10720.5, 15.3458], ...], "action": "partial"}}

        update:
        {"channel": "orderbook", "market": "BTC/USD", "type": "update", "data": {"time": 1564834587.1299787,
        "checksum": 3115602423, "bids": [], "asks": [[10719.0, 14.7461]], "action": "update"}}
        """
        if msg['type'] == 'partial':
            # snapshot
            pair = self.raw_symbol_to_std_symbol(msg['market'])
            info = {
                "platform": self._platform,
                "symbol": pair,
                "asks": {price: amount for price, amount in msg['data']['asks']},
                "bids": {price: amount for price, amount in msg['data']['bids']},
                "timestamp": int(round(msg['data']["time"] * 1000))  # Unix时间戳的毫秒数格式
            }
            orderbook = Orderbook(**info)
            self._orderbooks[pair] = orderbook
            SingleTask.run(self._on_orderbook_update_callback, orderbook)

        else:
            # update
            delta = {"bids": [], "asks": []}
            pair = self.raw_symbol_to_std_symbol(msg['market'])
            self._orderbooks[pair].timestamp = int(round(msg['data']["time"] * 1000))  # 无论是否reset,都需要更新
            for side in ('bids', 'asks'):
                s = "bids" if side == 'bids' else "asks"
                for price, amount in msg['data'][side]:
                    if float(amount) == 0:
                        delta[s].append((price, 0))
                        del getattr(self._orderbooks[pair], s)[price]  # 对类属性值操作

                    else:
                        delta[s].append((price, amount))
                        getattr(self._orderbooks[pair], s)[price] = amount  # 对类属性值操作
            SingleTask.run(self._on_orderbook_update_callback, self._orderbooks[pair])

    async def _trade(self, msg: dict):
        """
        example message:

        {"channel": "trades", "market": "BTC-PERP", "type": "update", "data": [{"id": null, "price": 10738.75,
        "size": 0.3616, "side": "buy", "liquidation": false, "time": "2019-08-03T12:20:19.170586+00:00"}]}
        """
        pair = self.raw_symbol_to_std_symbol(msg['market'])
        for data in msg['data']:
            info = {
                "platform": self._platform,
                "symbol": pair,
                "action": const.ORDER_ACTION_BUY if data["side"] == "buy" else const.ORDER_ACTION_SELL,
                "price": data['price'],
                "quantity": data['size'],
                "id": data['id'],
                "timestamp": int(tools.utctime_str_to_ms(data['time'], "%Y-%m-%dT%H:%M:%S.%f+00:00"))  # Unix时间戳的毫秒数格式
            }
            trade = Trade(**info)
            # self._trades[pair] = trade

            SingleTask.run(self._on_trade_update_callback, trade)

            # if bool(data['liquidation']):
            #     SingleTask.run(self._fetch_position, pair)

    async def _ticker(self, msg: dict):
        """
        example message:

        {"channel": "ticker", "market": "BTC/USD", "type": "update", "data": {"bid": 10717.5, "ask": 10719.0,
        "last": 10719.0, "time": 1564834587.1299787}}
        """
        pair = self.raw_symbol_to_std_symbol(msg['market'])
        info = {
            "platform": self._platform,
            "symbol": pair,
            "ask": msg['data']['ask'] if msg['data']['ask'] else 0.0,
            "bid": msg['data']['bid'] if msg['data']['bid'] else 0.0,
            "last": msg['data']['last'],
            "timestamp": int(round(msg['data']["time"] * 1000))  # Unix时间戳的毫秒数格式
        }
        ticker = Ticker(**info)
        # self._tickers[pair] = ticker
        SingleTask.run(self._on_ticker_update_callback, ticker)

    def status(self, trade_quantity, remain, quantity, status_info):
        if status_info == "new":
            return const.ORDER_STATUS_SUBMITTED
        elif status_info == "open":
            if float(remain) < float(quantity):
                return const.ORDER_STATUS_PARTIAL_FILLED
            else:
                return const.ORDER_STATUS_SUBMITTED
        elif status_info == "closed":
            if float(trade_quantity) < float(quantity):
                return const.ORDER_STATUS_CANCELED
            else:
                return const.ORDER_STATUS_FILLED
        else:
            logger.warn("unknown status:", status_info, caller=self)
            SingleTask.run(self._error_callback, "order status error.")
            return
