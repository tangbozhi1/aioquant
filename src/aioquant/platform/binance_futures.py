# -*- coding:utf-8 -*-

"""
Binance Trade module.
https://github.com/binance-exchange/binance-official-api-docs/blob/master/rest-api.md

Author: HuangTao
Date:   2018/08/09
Email:  huangtao@ifclover.com
"""



from aioquant import const
from aioquant.configure import config
from aioquant.Gateway import ExchangeGateway,ExchangeWebsocket
from aioquant.asset import Asset
from aioquant.position import Position,MARGIN_MODE_CROSSED,MARGIN_MODE_FIXED
from aioquant.fill import Fill
from aioquant.symbols import SymbolInfo
from aioquant.market import Orderbook,Ticker,Trade,Kline
from decimal import Decimal
import asyncio
import copy
from aioquant.error import Error
from aioquant.utils import tools
from aioquant.utils import logger
from aioquant.order import Order
from aioquant.tasks import SingleTask, LoopRunTask
from aioretry import retry
from aioquant.utils.decorator import async_method_locker
from aioquant.utils.web import Websocket
from ccxt.async_support.binance import binance

__all__ = ("BinanceRestAPI", "BinanceTrade", "BinanceMarket")


class BinanceRestAPI(binance):
    """Binance REST API client.

    Attributes:
        access_key: Account's ACCESS KEY.
        secret_key: Account's SECRET KEY.
        host: HTTP request host, default `https://api.binance.com`.
    """

    def __init__(self, config={}):
        """Initialize REST API client."""
        super(binance, self).__init__(config)  # 引用父类的父类初始化
        # 科学上网代理
        from aioquant.configure import config
        self.aiohttp_proxy = config.proxy
        # 其他配置参数
        self.options.update({
            "defaultType": "future",
            "adjustForTimeDifference": "True",
            "recvWindow": 10000
        })
        self.rateLimit = 20  # 异步执行周期，避免网络不通
        self.enableRateLimit = True

class BinanceTrade(ExchangeGateway):
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
    valid_depths = [5, 10, 20, 50, 100, 500, 1000, 5000]
    valid_candle_intervals = {'1m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d'}
    valid_depth_intervals = {'100ms', '1000ms'}
    websocket_channels = {
        # 公共频道
        const.L2_BOOK: 'depth',   # action: partial, action: update
        const.TICKER: 'bookTicker',
        const.TRADES: 'aggTrade',  # {'op': 'unsubscribe', 'channel': 'trades', 'market': 'BTC-PERP'}
        const.CANDLES: 'kline_',
        # 私有频道
        # 注册后不需要订阅
        # 需要CCXT获取
        const.POSITIONS: 'positions',
        const.FILLS: 'fills',
        const.ORDERS: 'orders',
        const.ACCOUNTS: 'accounts'
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
            kwargs["host"] = "https://fapi.binance.com"
        if not kwargs.get("wss"):
            kwargs["wss"] = "wss://fstream.binance.com"
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
        # self.requires_authentication = False
        self._raw_symbol = None
        self._listen_key = None  # Listen key for Websocket authentication.
        self._assets = {}  # Asset data. e.g. {"BTC": {"free": "1.1", "locked": "2.2", "total": "3.3"}, ... }
        self._orders = {}  # Order data. e.g. {order_id: order, ... }
        self._symbols = {} # Order data. e.g. {symbol: symboinfo, ... }
        self._position = {}
        # Initialize our REST API client.
        self._rest_api = BinanceRestAPI({"apiKey": self._access_key, "secret": self._secret_key,
                                         "hostname": self._host})  # 'spot', 'future'U本位, 'margin', 'delivery'币本位

        SingleTask.run(self._init_rest)  # 相当于ccxt.loadmarket

    async def _get_listen_key(self):
        while True:
            try:
                key = await self._rest_api.fapiPrivatePostListenKey()
                logger.info("get listen key success!",caller=self)
                self._listen_key = key["listenKey"]
                break
            except Exception as e:
                logger.error(e, caller=self)

    async def _reset_listen_key(self):
        """Reset listen key."""
        if not self._listen_key:
            logger.error("listen key not initialized!", caller=self)
            return
        while True:
            try:
                await self._rest_api.fapiPrivatePutListenkey(self._listen_key)
                logger.info("reset listen key success!", caller=self)
                break
            except Exception as e:
                logger.error(e, caller=self)


    @property
    def assets(self):
        return copy.copy(self._assets)

    @property
    def orders(self):
        return copy.copy(self._orders)

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
        # 私有与公共的听唯一区别是如果有订阅任何私有频道必须要有listen_key,address只是多?listenKey=<validateListenKey>
        await self._get_listen_key()
        url = self._wss + await self._address()
        self._ws = Websocket(url, self.connected_callback, process_callback=self.process)
        LoopRunTask.register(self._reset_listen_key, 60 * 30)


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
            if action == const.ORDER_ACTION_BUY:
                trade_type = const.TRADE_TYPE_BUY_OPEN  #开多
            elif action == const.ORDER_ACTION_SELL:
                trade_type = const.TRADE_TYPE_SELL_CLOSE   #平多
            else:
                return None, "action error"
        elif float(quantity) < 0:
            if action == const.ORDER_ACTION_BUY:
                trade_type = const.TRADE_TYPE_BUY_CLOSE  #平空
            elif action == const.ORDER_ACTION_SELL:
                trade_type = const.TRADE_TYPE_SELL_OPEN   #开空
            else:
                return None, "action error"
        else:
            return None, "quantity error"
        order_type = kwargs.get("order_type", const.ORDER_TYPE_LIMIT)
        params = kwargs.get("params", {})
        if order_type == const.ORDER_TYPE_POST_ONLY:
            params['timeInForce'] = 'GTX'
            order_type = const.ORDER_TYPE_LIMIT
        client_order_id = kwargs["client_order_id"] + '/' + str(trade_type)
        params["clientOrderId"] = client_order_id
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        result = await self._rest_api.create_order(self._symbol, order_type.lower(), action.lower(), abs(float(quantity)), price, params)
        if not result:
            SingleTask.run(self._error_callback, result)
            return None, result
        order_id = str(result["info"]["orderId"])
        return order_id, None

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
                _ = await self._rest_api.cancel_order(order_info["info"]["orderId"], self._symbol)
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
                order_id = str(order_info["info"]["orderId"])
                order_ids.append(order_id)
            return order_ids, None

    async def _address(self):
        """After websocket connection created successfully, pull back all open order information."""
        if not self._access_key or not self._secret_key:
            address = ""
            address += '/stream?streams='
        else:
            address = ""
            address += '/ws/' + self._listen_key
        # 最关键只订阅私有，有其他频道时只要发送listen_key后自动订阅私有频道，但address有变化
        return address

    async def connected_callback(self):
        if any(self.is_authenticated_channel(chan) for chan in self.websocket_channels.keys()):
            if not self._access_key or not self._secret_key:
                raise ValueError("Authenticated channel subscribed to, but no auth keys provided")

            raw_channels = list(set([self.std_channel_to_raw_channel(chan) for chan in self.websocket_channels.keys()]))
            subscription = {chan: self._raw_symbol for chan in raw_channels}
            for chan in subscription:
                # 根据机器配置,有些频道不订阅,对自动订阅的没作用
                if chan == self.std_channel_to_raw_channel(const.FILLS) and not self._fill_update_callback:
                    continue
                if chan == self.std_channel_to_raw_channel(const.ORDERS) and not self._order_update_callback:
                    continue
                if chan == self.std_channel_to_raw_channel(const.ACCOUNTS) and not self._asset_update_callback:
                    continue
                if chan == self.std_channel_to_raw_channel(const.POSITIONS) and not self._position_update_callback:
                    continue

                # 需要symbol作参数 (U本位最好不用)
                if chan == self.std_channel_to_raw_channel(const.ACCOUNTS):
                    # asyncio.create_task(self._fetch_balances())
                    # 确保手动追加不存在的chan不进入streams
                    continue

                # 需要symbol作参数 (U本位最好不用)
                if chan == self.std_channel_to_raw_channel(const.POSITIONS):
                    # asyncio.create_task(self._fetch_position(self.raw_symbol_to_std_symbol(self._raw_symbol)))  # 余额有变化时会推送，主动请求时，如果仓位空也不会请求到信息
                    # 确保手动追加不存在的chan不进入streams
                    continue
                    
        SingleTask.run(self._init_callback, True)
        
    @async_method_locker("BinanceTrade.process.locker")
    async def process(self, msg):
        """Process message that received from Websocket connection.

        Args:
            msg: message received from Websocket connection.
        """
        # Handle account updates from User Data Stream
        if 'e' in msg:
            msg_type = msg['e']
            if msg_type == 'ACCOUNT_UPDATE':
                await self._asset(msg)
            elif msg_type == 'ORDER_TRADE_UPDATE':
                await self._order(msg)
                return

    # async def _fetch_balances(self):
    #     while True:
    #         try:
    #             await asyncio.sleep(5)  # 请求限制
    #             balance = await self._rest_api.fetch_balance()
    #             await self._process_asset(balance)
    #             # break
    #         except Exception as e:
    #             logger.error(e, caller=self)
    # 
    # async def _process_asset(self, info):
    #     """
    #     {
    #         'asset': 'USDT',
    #         'walletBalance': '14.35545452',
    #         'unrealizedProfit': '0.28080000',
    #         'marginBalance': '14.63625452',        # total
    #         'maintMargin': '0.25440675',
    #         'initialMargin': '50.88135000',
    #         'positionInitialMargin': '50.88135000',    # usd
    #         'openOrderInitialMargin': '0.00000000',
    #         'maxWithdrawAmount': '14.35545452',
    #         'crossWalletBalance': '14.35545452',
    #         'crossUnPnl': '0.28080000',
    #         'availableBalance': '177.15271874',  # free
    #         'marginAvailable': True,
    #         'updateTime': '1663946592247'
    #     }
    #     """
    #     assets = {}
    #     for data in info['info']['assets']:
    #         total = Decimal(data['marginBalance'])
    #         free = Decimal(data['availableBalance'])
    #         locked = Decimal(data['positionInitialMargin'])
    #         assets[data['asset']] = {
    #             "total": "%.8f" % total,
    #             "free": "%.8f" % free,
    #             "locked": "%.8f" % locked
    #         }
    #     if assets == self._assets:
    #         update = False
    #     else:
    #         update = True
    #     if hasattr(self._assets, "assets") is False:
    #         info = {
    #             "platform": self._platform,
    #             "account": self._account,
    #             "assets": assets,
    #             "timestamp": tools.get_cur_timestamp_ms(),
    #             "update": update
    #         }
    #         asset = Asset(**info)
    #         self._assets = asset
    # 
    #     else:
    #         for sym in assets: # 相当于for symbol in assets.keys():
    #             self._assets.assets.update({
    #                 sym: assets[sym]
    #             })
    #         self._assets.timestamp = tools.get_cur_timestamp_ms()
    # 
    #     SingleTask.run(self._on_asset_update_callback, self._assets)


    # async def _fetch_order(self, symbol):
    #     while True:
    #         try:
    #             await asyncio.sleep(5)  # 请求限制
    #             orders = await self._rest_api.fetch_orders(symbol)
    #             await self._process_orders(orders)
    #         except Exception as e:
    #             logger.error(e, caller=self)
    # 
    # async def _process_orders(self, info):
    #     for data in info:   # 引用CCXT的格式化结果
    #         order = self._orders.get(data['id'])
    #         if not order:
    #             info = {
    #                 "platform": self._platform,
    #                 "account": self._account,
    #                 "strategy": self._strategy,
    #                 "symbol": data['symbol'],
    #                 "order_id": str(data['id']),
    #                 "client_order_id": str(data['clientOrderId']),
    #                 "action": const.ORDER_ACTION_BUY if data['side'] == 'buy' else const.ORDER_ACTION_SELL,
    #                 "order_type": const.ORDER_TYPE_LIMIT if data['type'] == "limit" else const.ORDER_TYPE_MARKET,
    #                 # "order_price_type": None,
    #                 "ctime": int(data['timestamp']),
    #             }
    #             order = Order(**info)
    #             self._orders[str(data['id'])] = order
    #         order.remain = str(data['remaining'])
    #         order.avg_price = str(data['average']) if data['average'] is not None else data['average']
    #         order.trade_type = const.TRADE_TYPE_NONE if len(order.client_order_id.split("/")[-1]) > 1 else order.client_order_id.split("/")[-1]
    #         order.price = str(data['price'])
    #         order.quantity = str(data['amount'])
    #         order.utime = int(data['timestamp'])
    #         order.status = self.status(Decimal(data['filled']), Decimal(data['remaining']), Decimal(data['amount']), data['info']['status'])
    #         if order.status in [const.ORDER_STATUS_FAILED, const.ORDER_STATUS_CANCELED, const.ORDER_STATUS_FILLED]:
    #             self._orders.pop(data['id'])
    #             await self._fetch_fills(self.raw_symbol_to_std_symbol(data['symbol']))
    # 
    #         SingleTask.run(self._on_order_update_callback, order)

    # async def _fetch_fills(self, symbol):
    #     while True:
    #         try:
    #             await asyncio.sleep(5)  # 请求限制
    #             fills = await self._rest_api.fetch_my_trades(symbol)
    #             await self._process_fills(fills)
    #         except Exception as e:
    #             logger.error(e, caller=self)
    # 
    # async def _process_fills(self, info):
    #     # [
    #     #     {
    #     #         'info': {
    #     #             'symbol': 'ETHUSDT',
    #     #             'id': '2268940884',
    #     #             'orderId': '8389765544207157214',
    #     #             'side': 'SELL',
    #     #             'price': '1251.92',
    #     #             'qty': '0.004',
    #     #             'realizedPnl': '0',
    #     #             'marginAsset': 'USDT',
    #     #             'quoteQty': '5.00768',
    #     #             'commission': '0.00200307',
    #     #             'commissionAsset': 'USDT',
    #     #             'time': '1663813646857',
    #     #             'positionSide': 'BOTH',
    #     #             'buyer': False,
    #     #             'maker': False
    #     #         },
    #     #         'timestamp': 1663813646857,
    #     #         'datetime': '2022-09-22T02:27:26.857Z',
    #     #         'symbol': 'ETH/USDT',
    #     #         'id': '2268940884',
    #     #         'order': '8389765544207157214',
    #     #         'type': None,
    #     #         'side': 'sell',
    #     #         'takerOrMaker': 'taker',
    #     #         'price': 1251.92,
    #     #         'amount': 0.004,
    #     #         'cost': 5.00768,
    #     #         'fee': {
    #     #             'cost': 0.00200307,
    #     #             'currency': 'USDT'
    #     #         },
    #     #         'fees': [
    #     #             {
    #     #                 'currency': 'USDT',
    #     #                 'cost': 0.00200307
    #     #             }
    #     #         ]
    #     #     },
    #     #     {
    #     #         'info': {
    #     #             'symbol': 'ETHUSDT',
    #     #             'id': '2268942027',
    #     #             'orderId': '8389765544207238595',
    #     #             'side': 'SELL',
    #     #             'price': '1252.12',
    #     #             'qty': '0.004',
    #     #             'realizedPnl': '0',
    #     #             'marginAsset': 'USDT',
    #     #             'quoteQty': '5.00848',
    #     #             'commission': '0.00200339',
    #     #             'commissionAsset': 'USDT',
    #     #             'time': '1663813679046',
    #     #             'positionSide': 'BOTH',
    #     #             'buyer': False,
    #     #             'maker': False
    #     #         },
    #     #         'timestamp': 1663813679046,
    #     #         'datetime': '2022-09-22T02:27:59.046Z',
    #     #         'symbol': 'ETH/USDT',
    #     #         'id': '2268942027',
    #     #         'order': '8389765544207238595',
    #     #         'type': None,
    #     #         'side': 'sell',
    #     #         'takerOrMaker': 'taker',
    #     #         'price': 1252.12,
    #     #         'amount': 0.004,
    #     #         'cost': 5.00848,
    #     #         'fee': {
    #     #             'cost': 0.00200339,
    #     #             'currency': 'USDT'
    #     #         },
    #     #         'fees': [
    #     #             {
    #     #                 'currency': 'USDT',
    #     #                 'cost': 0.00200339
    #     #             }
    #     #         ]
    #     #     }
    #     # ]
    #     for data in info:  # 引用CCXT的格式化结果
    #         info = {
    #             "platform": self._platform,
    #             "account": self._account,
    #             "strategy": self._strategy,
    #             "symbol": self.raw_symbol_to_std_symbol(data['symbol']),
    #             "fill_id": str(data['id']),
    #             "order_id": str(data['order']),
    #             "trade_type": data['type'],
    #             # "liquidity_price": None,
    #             "action": const.ORDER_ACTION_BUY if data['side'] == 'buy' else const.ORDER_ACTION_SELL,
    #             "price": str(data['price']),
    #             "quantity": str(data['amount']),
    #             "role": const.LIQUIDITY_TYPE_TAKER if data['takerOrMaker'] == "taker" else const.LIQUIDITY_TYPE_MAKER,
    #             "fee": str(data['info']['commission']) + "_" + data['info']['commissionAsset'],
    #             "ctime": int(data['timestamp'])
    #         }
    #         fill = Fill(**info)
    # 
    #         SingleTask.run(self._on_fill_update_callback, fill)

    # async def _fetch_position(self, symbol):
    #     while True:
    #         try:
    #             await asyncio.sleep(20)  # 请求限制
    #             positions = await self._rest_api.fetch_positions([symbol])
    #             await self._process_positions(positions)
    #             # break
    #         except Exception as e:
    #             logger.error(e, caller=self)
    # 
    # async def _process_positions(self, info):
    #     # [
    #     #     {
    #     #         'info': {
    #     #             'symbol': 'ETHUSDT',
    #     #             'positionAmt': '0.000',
    #     #             'entryPrice': '0.0',
    #     #             'markPrice': '1255.77236265',
    #     #             'unRealizedProfit': '0.00000000',
    #     #             'liquidationPrice': '0',
    #     #             'leverage': '50',
    #     #             'maxNotionalValue': '1000000',
    #     #             'marginType': 'cross',
    #     #             'isolatedMargin': '0.00000000',
    #     #             'isAutoAddMargin': 'false',
    #     #             'positionSide': 'BOTH',
    #     #             'notional': '0',
    #     #             'isolatedWallet': '0',
    #     #             'updateTime': '1661278904293'
    #     #         },
    #     #         'symbol': 'ETH/USDT',
    #     #         'contracts': 0.0,
    #     #         'contractSize': 1.0,
    #     #         'unrealizedPnl': 0.0,
    #     #         'leverage': 50.0,
    #     #         'liquidationPrice': None,
    #     #         'collateral': 0.0,
    #     #         'notional': 0.0,
    #     #         'markPrice': 1255.77236265,
    #     #         'entryPrice': 0.0,
    #     #         'timestamp': 1661278904293,
    #     #         'initialMargin': 0.0,
    #     #         'initialMarginPercentage': 0.02,
    #     #         'maintenanceMargin': 0.0,
    #     #         'maintenanceMarginPercentage': 0.005,
    #     #         'marginRatio': None,
    #     #         'datetime': '2022-08-23T18:21:44.293Z',
    #     #         'marginMode': 'cross',
    #     #         'marginType': 'cross',
    #     #         'side': None,
    #     #         'hedged': False,
    #     #         'percentage': None
    #     #     }
    #     # ]
    #     for data in info:
    #         update = False
    #         position = Position(self._platform, self._account, self._strategy, self.raw_symbol_to_std_symbol(data['info']['symbol']))
    #         if not position.timestamp:
    #             update = True
    #             position.update()
    #         if Decimal(data['info']['positionAmt']) > 0:
    #             if position.long_quantity != data['contracts']:
    #                 update = True
    #                 position.update(margin_mode=MARGIN_MODE_CROSSED if data['marginType']=="cross" else MARGIN_MODE_FIXED, long_quantity=data['contracts'], long_avg_qty=str(
    #                     Decimal(position.long_quantity) - Decimal(data['contractSize']) if Decimal(
    #                         data['contractSize']) < Decimal(position.long_quantity) else 0),
    #                                 long_open_price=data['entryPrice'],
    #                                 long_hold_price=data['info']['entryPrice'],
    #                                 long_liquid_price=data['info']['liquidationPrice'],
    #                                 long_unrealised_pnl=data['unrealizedPnl'],
    #                                 long_leverage=data['info']['leverage'],
    #                                 long_margin=data['initialMargin'])
    #         elif Decimal(data['info']['positionAmt']) < 0:
    #             if position.short_quantity != data['contracts']:
    #                 update = True
    #                 position.update(margin_mode=MARGIN_MODE_CROSSED if data['marginType']=="cross" else MARGIN_MODE_FIXED, short_quantity=data['contracts'], short_avg_qty=str(
    #                     Decimal(position.long_quantity) - Decimal(data['contractSize']) if Decimal(
    #                         data['contractSize']) < Decimal(position.long_quantity) else 0),
    #                                 short_open_price=data['entryPrice'],
    #                                 short_hold_price=data['info']['entryPrice'],
    #                                 short_liquid_price=data['info']['liquidationPrice'],
    #                                 short_unrealised_pnl=data['unrealizedPnl'],
    #                                 short_leverage=data['info']['leverage'],
    #                                 short_margin=data['initialMargin'])
    #         elif Decimal(data['info']['positionAmt']) == 0:
    #             if position.long_quantity != 0 or position.short_quantity != 0:
    #                 update = True
    #                 position.update()
    # 
    #         # 此处与父类不同
    #         if not update or not self._position_update_callback:
    #             return
    #         self._position[self.raw_symbol_to_std_symbol(data['info']['symbol'])] = position
    #         SingleTask.run(self._on_position_update_callback, position)

    # 根据Order返回的status修改
    def status(self, trade_quantity, remain, quantity, status_info):
        """
            NEW
            PARTIALLY_FILLED
            FILLED
            CANCELED
            EXPIRED
            NEW_INSURANCE
            风险保障基金(强平)
            NEW_ADL
            自动减仓序列(强平)
        """
        if status_info == "NEW":
            return const.ORDER_STATUS_SUBMITTED
        elif status_info == "FILLED":
            return const.ORDER_STATUS_FILLED
        elif status_info == "EXPIRED":
            return const.ORDER_STATUS_CANCELED
        elif status_info == "NEW_INSURANCE":
            return const.ORDER_STATUS_FILLED
        elif status_info == "NEW_ADL":
            return const.ORDER_STATUS_FILLED
        elif status_info == "PARTIALLY_FILLED":
            if float(remain) < float(quantity):
                return const.ORDER_STATUS_PARTIAL_FILLED
            else:
                return const.ORDER_STATUS_SUBMITTED
        elif status_info == "CANCELED":
            if float(trade_quantity) < float(quantity):
                return const.ORDER_STATUS_CANCELED
            else:
                return const.ORDER_STATUS_FILLED
        else:
            logger.warn("unknown status:", status_info, caller=self)
            SingleTask.run(self._error_callback, "order status error.")
            return

    async def _order(self, msg: dict):
        '''
       {
            "e":"ORDER_TRADE_UPDATE",     // Event Type
            "E":1568879465651,            // Event Time
            "T":1568879465650,            // Transaction Time
            "o":
            {
                "s":"BTCUSDT",              // Symbol
                "c":"TEST",                 // Client Order Id
                // special client order id:
                // starts with "autoclose-": liquidation order
                // "adl_autoclose": ADL auto close order
                "S":"SELL",                 // Side
                "o":"TRAILING_STOP_MARKET", // Order Type
                "f":"GTC",                  // Time in Force
                "q":"0.001",                // Original Quantity
                "p":"0",                    // Original Price
                "ap":"0",                   // Average Price
                "sp":"7103.04",             // Stop Price. Please ignore with TRAILING_STOP_MARKET order
                "x":"NEW",                  // Execution Type
                "X":"NEW",                  // Order Status
                "i":8886774,                // Order Id
                "l":"0",                    // Order Last Filled Quantity
                "z":"0",                    // Order Filled Accumulated Quantity
                "L":"0",                    // Last Filled Price
                "N":"USDT",             // Commission Asset, will not push if no commission
                "n":"0",                // Commission, will not push if no commission
                "T":1568879465651,          // Order Trade Time
                "t":0,                      // Trade Id
                "b":"0",                    // Bids Notional
                "a":"9.91",                 // Ask Notional
                "m":false,                  // Is this trade the maker side?
                "R":false,                  // Is this reduce only
                "wt":"CONTRACT_PRICE",      // Stop Price Working Type
                "ot":"TRAILING_STOP_MARKET",    // Original Order Type
                "ps":"LONG",                        // Position Side
                "cp":false,                     // If Close-All, pushed with conditional order
                "AP":"7476.89",             // Activation Price, only puhed with TRAILING_STOP_MARKET order
                "cr":"5.0",                 // Callback Rate, only puhed with TRAILING_STOP_MARKET order
                "rp":"0"                            // Realized Profit of the trade
            }
        }
        '''
        pair = self.raw_symbol_to_std_symbol(msg['o']['s'])
        order = self._orders.get(msg['o']['i'])
        if not order:
            info = {
                "platform": self._platform,
                "account": self._account,
                "strategy": self._strategy,
                "symbol": pair,
                "order_id": str(msg['o']['i']),
                "client_order_id": str(msg['o']['c']),
                "action": const.ORDER_ACTION_BUY if msg['o']['S'] == 'BUY' else const.ORDER_ACTION_SELL,
                "order_type": const.ORDER_TYPE_LIMIT if msg['o']['o'] == "LIMIT" else const.ORDER_TYPE_MARKET,
                "order_price_type": msg['o']['wt'],
                "ctime": msg['o']['T'],
            }
            order = Order(**info)
            self._orders[msg['o']['i']] = order
        order.remain = float(msg['o']['q']) - float(msg['o']['z'])
        order.avg_price = str(msg['o']['ap'])
        order.trade_type = const.TRADE_TYPE_NONE if len(order.client_order_id.split("/")[-1]) > 1 else \
            order.client_order_id.split("/")[-1]
        order.price = str(msg['o']['p'])
        order.quantity = str(msg['o']['q'])
        order.utime = msg['E']
        order.status = self.status(Decimal(msg['o']['z']), Decimal(order.remain), Decimal(msg['o']['q']),
                                   msg['o']['X'])
        if order.status in [const.ORDER_STATUS_FAILED, const.ORDER_STATUS_CANCELED, const.ORDER_STATUS_FILLED]:
            self._orders.pop(msg['o']['i'])

        SingleTask.run(self._on_order_update_callback, order)

        if msg['o']['t']:
            await self._fill(msg)

    async def _fill(self, data: dict):
        # {
        #
        # "e": "ORDER_TRADE_UPDATE", // 事件类型
        # "E": 1568879465651, // 事件时间
        # "T": 1568879465650, // 撮合时间
        # "o": {
        #          "s": "BTCUSDT", // 交易对
        # "c": "TEST", // 客户端自定订单ID
        #                 // 特殊的自定义订单ID:
        # // "autoclose-"
        # 开头的字符串: 系统强平订单
        #         // "adl_autoclose": ADL自动减仓订单
        #                             // "settlement_autoclose-": 下架或交割的结算订单
        # "S": "SELL", // 订单方向
        # "o": "TRAILING_STOP_MARKET", // 订单类型
        # "f": "GTC", // 有效方式
        # "q": "0.001", // 订单原始数量
        # "p": "0", // 订单原始价格
        # "ap": "0", // 订单平均价格
        # "sp": "7103.04", // 条件订单触发价格，对追踪止损单无效
        # "x": "NEW", // 本次事件的具体执行类型
        # "X": "NEW", // 订单的当前状态
        # "i": 8886774, // 订单ID
        # "l": "0", // 订单末次成交量
        # "z": "0", // 订单累计已成交量
        # "L": "0", // 订单末次成交价格
        # "N": "USDT", // 手续费资产类型
        # "n": "0", // 手续费数量
        # "T": 1568879465650, // 成交时间
        # "t": 0, // 成交ID
        # "b": "0", // 买单净值
        # "a": "9.91", // 卖单净值
        # "m": false, // 该成交是作为挂单成交吗？
        # "R": false, // 是否是只减仓单
        # "wt": "CONTRACT_PRICE", // 触发价类型
        # "ot": "TRAILING_STOP_MARKET", // 原始订单类型
        # "ps": "LONG" // 持仓方向
        # "cp": false, // 是否为触发平仓单;
        # 仅在条件订单情况下会推送此字段
        # "AP": "7476.89", // 追踪止损激活价格, 仅在追踪止损单时会推送此字段
        # "cr": "5.0", // 追踪止损回调比例, 仅在追踪止损单时会推送此字段
        # "pP": false, // 忽略
        # "si": 0, // 忽略
        # "ss": 0, // 忽略
        # "rp": "0" // 该交易实现盈亏
        # }
        #
        # }

        pair = self.raw_symbol_to_std_symbol(data['o']['s'])
        info = {
            "platform": self._platform,
            "account": self._account,
            "strategy": self._strategy,
            "symbol": pair,
            "fill_id": str(data['o']['t']),
            "order_id": str(data['o']['i']),
            "trade_type": data['o']['o'],
            # "liquidity_price": data['o']['AP'],
            "action": const.ORDER_ACTION_BUY if data['o']['S'] == 'BUY' else const.ORDER_ACTION_SELL,
            "price": str(data['o']['L']),
            "quantity": str(data['o']['l']),
            "role": const.LIQUIDITY_TYPE_TAKER if data['o']['m'] == False else const.LIQUIDITY_TYPE_MAKER,
            "fee": str(data['o']['n'] + "_" + data['o']['N']) if data['o'].get('n') else None,
            "ctime": data['o']['T']
        }
        fill = Fill(**info)

        SingleTask.run(self._on_fill_update_callback, fill)

    async def _asset(self, msg: dict):
        """
       {
        "e": "ACCOUNT_UPDATE",                // Event Type
        "E": 1564745798939,                   // Event Time
        "T": 1564745798938 ,                  // Transaction
        "a":                                  // Update Data
            {
            "m":"ORDER",                      // Event reason type
            "B":[                             // Balances
                {
                "a":"USDT",                   // Asset
                "wb":"122624.12345678",       // Wallet Balance
                "cw":"100.12345678",          // Cross Wallet Balance
                "bc":"50.12345678"            // Balance Change except PnL and Commission
                },
                {
                "a":"BUSD",
                "wb":"1.00000000",
                "cw":"0.00000000",
                "bc":"-49.12345678"
                }
            ],
            "P":[
                {
                "s":"BTCUSDT",            // Symbol
                "pa":"0",                 // Position Amount
                "ep":"0.00000",            // Entry Price
                "cr":"200",               // (Pre-fee) Accumulated Realized
                "up":"0",                     // Unrealized PnL
                "mt":"isolated",              // Margin Type
                "iw":"0.00000000",            // Isolated Wallet (if isolated position)
                "ps":"BOTH"                   // Position Side
                }，
                {
                    "s":"BTCUSDT",
                    "pa":"20",
                    "ep":"6563.66500",
                    "cr":"0",
                    "up":"2850.21200",
                    "mt":"isolated",
                    "iw":"13200.70726908",
                    "ps":"LONG"
                },
                {
                    "s":"BTCUSDT",
                    "pa":"-10",
                    "ep":"6563.86000",
                    "cr":"-45.04000000",
                    "up":"-1423.15600",
                    "mt":"isolated",
                    "iw":"6570.42511771",
                    "ps":"SHORT"
                }
            ]
            }
        }
        """
        assets = {}
        for data in msg['a']['B']:
            total = Decimal(data['wb']) + Decimal(data['bc'])
            free = Decimal(data['cw']) + Decimal(data['bc'])
            locked = total - free
            assets[data['a']] = {
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
            for sym in assets:  # 相当于for symbol in assets.keys():
                self._assets.assets.update({
                    sym: assets[sym]
                })
            self._assets.timestamp = tools.get_cur_timestamp_ms()

        SingleTask.run(self._on_asset_update_callback, self._assets)

        for position in msg['a']['P']:
            await self._positions(position)

    async def _positions(self, data):
        # {
        # "s": "BTCUSDT", // 交易对
        # "pa": "0", // 仓位
        # "ep": "0.00000", // 入仓价格
        # "cr": "200", // (费前)
        # 累计实现损益
        # "up": "0", // 持仓未实现盈亏
        # "mt": "isolated", // 保证金模式
        # "iw": "0.00000000", // 若为逐仓，仓位保证金
        # "ps": "BOTH" // 持仓方向
        # }
        update = False
        # position = Position(self._platform, self._account, self._strategy, self.raw_symbol_to_std_symbol(data['s']))
        # if not position.timestamp:
        #     update = True
        #     position.update()
        pair = self.raw_symbol_to_std_symbol(data['s'])
        if pair not in self._position:
            self._position[pair] = Position(self._platform, self._account, self._strategy, pair)
            update = True

        if Decimal(data['pa']) > 0:
            if self._position[pair].long_quantity != data['pa']:
                update = True
                self._position[pair].update(margin_mode=MARGIN_MODE_FIXED if data['mt']=="isolated" else MARGIN_MODE_CROSSED, long_quantity=data['pa'], long_avg_qty=data['pa'],
                                long_open_price=data['ep'],
                                long_hold_price=data['ep'],
                                long_unrealised_pnl=data['up'],
                                long_liquid_price=self._position[pair].long_liquid_price,
                                long_leverage=self._position[pair].long_leverage,
                                long_margin=self._position[pair].long_margin)
        elif Decimal(data['pa']) < 0:
            if self._position[pair].short_quantity != data['pa']:
                update = True
                self._position[pair].update(margin_mode=MARGIN_MODE_FIXED if data['mt']=="isolated" else MARGIN_MODE_CROSSED, short_quantity=abs(float(data['pa'])), short_avg_qty=abs(float(data['pa'])),
                                short_open_price=data['ep'],
                                short_hold_price=data['ep'],
                                short_unrealised_pnl=data['up'],
                                short_liquid_price=self._position[pair].short_liquid_price,
                                short_leverage=self._position[pair].short_leverage,
                                short_margin=self._position[pair].short_margin)
        elif Decimal(data['pa']) == 0 and data['ps'] == 'BOTH':
            if self._position[pair].long_quantity != 0 or self._position[pair].short_quantity != 0:
                update = True
                self._position[pair].update()

        # 此处与父类不同
        if not update or not self._position_update_callback:
            return

        SingleTask.run(self._on_position_update_callback, self._position[pair])
        

class BinanceMarket(ExchangeWebsocket):
    """OKx Market module.
    """
    valid_depths = [5, 10, 20, 50, 100, 500, 1000, 5000]
    valid_candle_intervals = {'1m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d'}
    valid_depth_intervals = {'100ms', '1000ms'}
    websocket_channels = {
        # 公共频道
        const.L2_BOOK: 'depth',   # action: partial, action: update
        const.TICKER: 'bookTicker',
        const.TRADES: 'aggTrade',  # {'op': 'unsubscribe', 'channel': 'trades', 'market': 'BTC-PERP'}
        const.CANDLES: 'kline_',
        # 私有频道
        # 注册后不需要订阅
        # 需要CCXT获取 （websocket只推送一次，不会变动
        const.POSITIONS: 'positions',
        const.FILLS: 'fills'
    }
    def __init__(self, **kwargs):
        """Initialize Market module."""
        e = None
        if not kwargs.get("account"):
            e = Error("param account miss")
        if not kwargs.get("host"):
            kwargs["host"] = "https://fapi.binance.com"
        if not kwargs.get("wss"):
            kwargs["wss"] = "wss://fstream.binance.com"
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
        self._symbols = {}  # Order data. e.g. {symbol: symboinfo, ... }
        self._orderbooks = {}
        self._position = {}
        # self.requires_authentication = False    # 因为币安的websocket chan是需要对应的url并且私有频道不用订阅，因此用不了
        self._listen_key = None  # Listen key for Websocket authentication.
        # Initialize our REST API client.
        self._rest_api = BinanceRestAPI({"apiKey": self._access_key, "secret": self._secret_key,
                                         "hostname": self._host})  # 'spot', 'future'U本位, 'margin', 'delivery'币本位

        SingleTask.run(self._init_rest)  # 相当于ccxt.loadmarket

    async def _get_listen_key(self):
        while True:
            try:
                key = await self._rest_api.fapiPrivatePostListenKey()
                logger.info("get listen key success!",caller=self)
                self._listen_key = key["listenKey"]
                break
            except Exception as e:
                logger.error(e, caller=self)

    async def _reset_listen_key(self):
        """Reset listen key."""
        if not self._listen_key:
            logger.error("listen key not initialized!", caller=self)
            return
        while True:
            try:
                await self._rest_api.fapiPrivatePutListenkey(self._listen_key)
                logger.info("reset listen key success!", caller=self)
                break
            except Exception as e:
                logger.error(e, caller=self)

    @property
    def assets(self):
        return copy.copy(self._assets)

    @property
    def orders(self):
        return copy.copy(self._orders)

    @property
    def symbols(self):
        return copy.copy(self._symbols)

    @property
    def orderbooks(self):
        return copy.copy(self._orderbooks)

    @property
    def rest_api(self):
        return self._rest_api

    @classmethod
    # 判断需要身份验证的订阅
    def is_authenticated_channel(self, channel: str) -> bool:
        return channel in (const.ACCOUNTS,const.BALANCES,const.ORDERS,const.FILLS,const.POSITIONS)

    def _reset(self):
        self._orderbooks = {}
        self.last_update_id = {}

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

        # 私有与公共的听唯一区别是如果有订阅任何私有频道必须要有listen_key,address只是多?listenKey=<validateListenKey>
        await self._get_listen_key()
        self._wsp = Websocket(self._wss + '/ws/' + self._listen_key, self.connected_callback, process_callback=self.process_private)
        LoopRunTask.register(self._reset_listen_key, 60 * 30)

        # 公共订阅url必须与subscrib一致，首先准备url，切割后将url与sub批配websocket发送,然后再来
        await self._address()

    async def _address(self):
        address = ""
        address += '/stream?streams='
        subs = []
        raw_channels = list(set([self.std_channel_to_raw_channel(chan) for chan in self.websocket_channels.keys()]))
        subscription = {chan: self._symbols for chan in raw_channels}

        for chan in subscription:
            streams = []
            # 根据机器配置,有些频道不订阅,对自动订阅的没作用
            # if chan == self.std_channel_to_raw_channel(const.FILLS) and not self._fill_update_callback:
            #     continue
            # if chan == self.std_channel_to_raw_channel(const.ORDERS) and not self._order_update_callback:
            #     continue
            # if chan == self.std_channel_to_raw_channel(const.ACCOUNTS) and not self._asset_update_callback:
            #     continue
            # if chan == self.std_channel_to_raw_channel(const.POSITIONS) and not self._position_update_callback:
            #     continue
            if chan == self.std_channel_to_raw_channel(const.L2_BOOK) and not self._orderbook_update_callback:
                continue
            if chan == self.std_channel_to_raw_channel(const.TICKER) and not self._ticker_update_callback:
                continue
            if chan == self.std_channel_to_raw_channel(const.TRADES) and not self._trade_update_callback:
                continue
            if chan == self.std_channel_to_raw_channel(const.CANDLES) and not self._kline_update_callback:
                continue

            # 对于没有websock频道通过RestAPI获取
            if chan == self.std_channel_to_raw_channel(const.FILLS):
                # asyncio.create_task(self._fetch_balances())
                # 确保手动追加不存在的chan不进入address
                continue


            elif chan == self.std_channel_to_raw_channel(const.CANDLES):
                streams.append([f"{chan}{candle_interval}" for candle_interval in self.valid_candle_intervals])

            elif chan == self.std_channel_to_raw_channel(const.L2_BOOK):
                streams.append([f"{chan}@{depth_interval}" for depth_interval in self.valid_depth_intervals])

            elif chan == self.std_channel_to_raw_channel(const.TICKER):
                streams.append([f"{chan}"])

            elif chan == self.std_channel_to_raw_channel(const.TRADES):
                streams.append([f"{chan}"])

            for symbol in subscription[chan]:
                # 市场模块还是不要RestAPI，要出问题
                if chan == self.std_channel_to_raw_channel(const.POSITIONS):
                    # asyncio.create_task(self._fetch_position(symbol))
                    # 确保手动追加不存在的chan不进入address
                    continue

                # for everything but premium index the symbols need to be lowercase.
                if symbol.startswith("p"):
                    if chan != const.CANDLES:
                        raise ValueError("Premium Index Symbols only allowed on Candle data feed")
                else:
                    pair = self.std_symbol_to_raw_symbol(symbol).lower()

                # ['kline_1m', 'kline_6h', 'kline_4h', 'kline_1d', 'kline_5m', 'kline_12h', 'kline_2h', 'kline_30m', 'kline_15m', 'kline_1h']
                # ['depth@100ms', 'depth@1000ms']
                ch = [item for sublist in streams for item in sublist]
                # 删除重复的频道
                ch = list(set(ch))
                if not ch:
                    continue
                subs.append([f"{pair}@{stream}" for stream in ch])

        # ['btcusdt@kline_30m', 'btcusdt@kline_4h', 'btcusdt@kline_5m', 'btcusdt@kline_15m', 'btcusdt@kline_6h', 'btcusdt@kline_1m', 'btcusdt@kline_1h', 'btcusdt@kline_2h', 'btcusdt@kline_12h', 'btcusdt@kline_1d', 'ethusdt@kline_30m', 'ethusdt@kline_4h', 'ethusdt@kline_5m', 'ethusdt@kline_15m', 'ethusdt@kline_6h', 'ethusdt@kline_1m', 'ethusdt@kline_1h', 'ethusdt@kline_2h', 'ethusdt@kline_12h', 'ethusdt@kline_1d', 'bchusdt@kline_30m', 'bchusdt@kline_4h', 'bchusdt@kline_5m', 'bchusdt@kline_15m', 'bchusdt@kline_6h', 'bchusdt@kline_1m', 'bchusdt@kline_1h', 'bchusdt@kline_2h', 'bchusdt@kline_12h', 'bchusdt@kline_1d', 'xrpusdt@kline_30m', 'xrpusdt@kline_4h', 'xrpusdt@kline_5m', 'xrpusdt@kline_15m', 'xrpusdt@kline_6h', 'xrpusdt@kline_1m', 'xrpusdt@kline_1h', 'xrpusdt@kline_2h', 'xrpusdt@kline_12h', 'xrpusdt@kline_1d', 'eosusdt@kline_30m', 'eosusdt@kline_4h', 'eosusdt@kline_5m', 'eosusdt@kline_15m', 'eosusdt@kline_6h', 'eosusdt@kline_1m', 'eosusdt@kline_1h', 'eosusdt@kline_2h', 'eosusdt@kline_12h', 'eosusdt@kline_1d', 'ltcusdt@kline_30m', 'ltcusdt@kline_4h', 'ltcusdt@kline_5m', 'ltcusdt@kline_15m', 'ltcusdt@kline_6h', 'ltcusdt@kline_1m', 'ltcusdt@kline_1h', 'ltcusdt@kline_2h', 'ltcusdt@kline_12h', 'ltcusdt@kline_1d', 'trxusdt@kline_30m', 'trxusdt@kline_4h', 'trxusdt@kline_5m', 'trxusdt@kline_15m', 'trxusdt@kline_6h', 'trxusdt@kline_1m', 'trxusdt@kline_1h', 'trxusdt@kline_2h', 'trxusdt@kline_12h', 'trxusdt@kline_1d', 'etcusdt@kline_30m', 'etcusdt@kline_4h', 'etcusdt@kline_5m', 'etcusdt@kline_15m', 'etcusdt@kline_6h', 'etcusdt@kline_1m', 'etcusdt@kline_1h', 'etcusdt@kline_2h', 'etcusdt@kline_12h', 'etcusdt@kline_1d', 'linkusdt@kline_30m', 'linkusdt@kline_4h', 'linkusdt@kline_5m', 'linkusdt@kline_15m', 'linkusdt@kline_6h', 'linkusdt@kline_1m', 'linkusdt@kline_1h', 'linkusdt@kline_2h', 'linkusdt@kline_12h', 'linkusdt@kline_1d', 'xlmusdt@kline_30m', 'xlmusdt@kline_4h', 'xlmusdt@kline_5m', 'xlmusdt@kline_15m', 'xlmusdt@kline_6h', 'xlmusdt@kline_1m', 'xlmusdt@kline_1h', 'xlmusdt@kline_2h', 'xlmusdt@kline_12h', 'xlmusdt@kline_1d', 'adausdt@kline_30m', 'adausdt@kline_4h', 'adausdt@kline_5m', 'adausdt@kline_15m', 'adausdt@kline_6h', 'adausdt@kline_1m', 'adausdt@kline_1h', 'adausdt@kline_2h', 'adausdt@kline_12h', 'adausdt@kline_1d', 'xmrusdt@kline_30m', 'xmrusdt@kline_4h', 'xmrusdt@kline_5m', 'xmrusdt@kline_15m', 'xmrusdt@kline_6h', 'xmrusdt@kline_1m', 'xmrusdt@kline_1h', 'xmrusdt@kline_2h', 'xmrusdt@kline_12h', 'xmrusdt@kline_1d', 'dashusdt@kline_30m', 'dashusdt@kline_4h', 'dashusdt@kline_5m', 'dashusdt@kline_15m', 'dashusdt@kline_6h', 'dashusdt@kline_1m', 'dashusdt@kline_1h', 'dashusdt@kline_2h', 'dashusdt@kline_12h', 'dashusdt@kline_1d', 'zecusdt@kline_30m', 'zecusdt@kline_4h', 'zecusdt@kline_5m', 'zecusdt@kline_15m', 'zecusdt@kline_6h', 'zecusdt@kline_1m', 'zecusdt@kline_1h', 'zecusdt@kline_2h', 'zecusdt@kline_12h', 'zecusdt@kline_1d', 'xtzusdt@kline_30m', 'xtzusdt@kline_4h', 'xtzusdt@kline_5m', 'xtzusdt@kline_15m', 'xtzusdt@kline_6h', 'xtzusdt@kline_1m', 'xtzusdt@kline_1h', 'xtzusdt@kline_2h', 'xtzusdt@kline_12h', 'xtzusdt@kline_1d', 'bnbusdt@kline_30m', 'bnbusdt@kline_4h', 'bnbusdt@kline_5m', 'bnbusdt@kline_15m', 'bnbusdt@kline_6h', 'bnbusdt@kline_1m', 'bnbusdt@kline_1h', 'bnbusdt@kline_2h', 'bnbusdt@kline_12h', 'bnbusdt@kline_1d', 'atomusdt@kline_30m', 'atomusdt@kline_4h', 'atomusdt@kline_5m', 'atomusdt@kline_15m', 'atomusdt@kline_6h', 'atomusdt@kline_1m', 'atomusdt@kline_1h', 'atomusdt@kline_2h', 'atomusdt@kline_12h', 'atomusdt@kline_1d', 'ontusdt@kline_30m', 'ontusdt@kline_4h', 'ontusdt@kline_5m', 'ontusdt@kline_15m', 'ontusdt@kline_6h', 'ontusdt@kline_1m', 'ontusdt@kline_1h', 'ontusdt@kline_2h', 'ontusdt@kline_12h', 'ontusdt@kline_1d', 'iotausdt@kline_30m', 'iotausdt@kline_4h', 'iotausdt@kline_5m', 'iotausdt@kline_15m', 'iotausdt@kline_6h', 'iotausdt@kline_1m', 'iotausdt@kline_1h', 'iotausdt@kline_2h', 'iotausdt@kline_12h', 'iotausdt@kline_1d', 'batusdt@kline_30m', 'batusdt@kline_4h', 'batusdt@kline_5m', 'batusdt@kline_15m', 'batusdt@kline_6h', 'batusdt@kline_1m', 'batusdt@kline_1h', 'batusdt@kline_2h', 'batusdt@kline_12h', 'batusdt@kline_1d', 'vetusdt@kline_30m', 'vetusdt@kline_4h', 'vetusdt@kline_5m', 'vetusdt@kline_15m', 'vetusdt@kline_6h', 'vetusdt@kline_1m', 'vetusdt@kline_1h', 'vetusdt@kline_2h', 'vetusdt@kline_12h', 'vetusdt@kline_1d', 'neousdt@kline_30m', 'neousdt@kline_4h', 'neousdt@kline_5m', 'neousdt@kline_15m', 'neousdt@kline_6h', 'neousdt@kline_1m', 'neousdt@kline_1h', 'neousdt@kline_2h', 'neousdt@kline_12h', 'neousdt@kline_1d', 'qtumusdt@kline_30m', 'qtumusdt@kline_4h', 'qtumusdt@kline_5m', 'qtumusdt@kline_15m', 'qtumusdt@kline_6h', 'qtumusdt@kline_1m', 'qtumusdt@kline_1h', 'qtumusdt@kline_2h', 'qtumusdt@kline_12h', 'qtumusdt@kline_1d', 'iostusdt@kline_30m', 'iostusdt@kline_4h', 'iostusdt@kline_5m', 'iostusdt@kline_15m', 'iostusdt@kline_6h', 'iostusdt@kline_1m', 'iostusdt@kline_1h', 'iostusdt@kline_2h', 'iostusdt@kline_12h', 'iostusdt@kline_1d', 'thetausdt@kline_30m', 'thetausdt@kline_4h', 'thetausdt@kline_5m', 'thetausdt@kline_15m', 'thetausdt@kline_6h', 'thetausdt@kline_1m', 'thetausdt@kline_1h', 'thetausdt@kline_2h', 'thetausdt@kline_12h', 'thetausdt@kline_1d', 'algousdt@kline_30m', 'algousdt@kline_4h', 'algousdt@kline_5m', 'algousdt@kline_15m', 'algousdt@kline_6h', 'algousdt@kline_1m', 'algousdt@kline_1h', 'algousdt@kline_2h', 'algousdt@kline_12h', 'algousdt@kline_1d', 'zilusdt@kline_30m', 'zilusdt@kline_4h', 'zilusdt@kline_5m', 'zilusdt@kline_15m', 'zilusdt@kline_6h', 'zilusdt@kline_1m', 'zilusdt@kline_1h', 'zilusdt@kline_2h', 'zilusdt@kline_12h', 'zilusdt@kline_1d', 'kncusdt@kline_30m', 'kncusdt@kline_4h', 'kncusdt@kline_5m', 'kncusdt@kline_15m', 'kncusdt@kline_6h', 'kncusdt@kline_1m', 'kncusdt@kline_1h', 'kncusdt@kline_2h', 'kncusdt@kline_12h', 'kncusdt@kline_1d', 'zrxusdt@kline_30m', 'zrxusdt@kline_4h', 'zrxusdt@kline_5m', 'zrxusdt@kline_15m', 'zrxusdt@kline_6h', 'zrxusdt@kline_1m', 'zrxusdt@kline_1h', 'zrxusdt@kline_2h', 'zrxusdt@kline_12h', 'zrxusdt@kline_1d', 'compusdt@kline_30m', 'compusdt@kline_4h', 'compusdt@kline_5m', 'compusdt@kline_15m', 'compusdt@kline_6h', 'compusdt@kline_1m', 'compusdt@kline_1h', 'compusdt@kline_2h', 'compusdt@kline_12h', 'compusdt@kline_1d', 'omgusdt@kline_30m', 'omgusdt@kline_4h', 'omgusdt@kline_5m', 'omgusdt@kline_15m', 'omgusdt@kline_6h', 'omgusdt@kline_1m', 'omgusdt@kline_1h', 'omgusdt@kline_2h', 'omgusdt@kline_12h', 'omgusdt@kline_1d', 'dogeusdt@kline_30m', 'dogeusdt@kline_4h', 'dogeusdt@kline_5m', 'dogeusdt@kline_15m', 'dogeusdt@kline_6h', 'dogeusdt@kline_1m', 'dogeusdt@kline_1h', 'dogeusdt@kline_2h', 'dogeusdt@kline_12h', 'dogeusdt@kline_1d', 'sxpusdt@kline_30m', 'sxpusdt@kline_4h', 'sxpusdt@kline_5m', 'sxpusdt@kline_15m', 'sxpusdt@kline_6h', 'sxpusdt@kline_1m', 'sxpusdt@kline_1h', 'sxpusdt@kline_2h', 'sxpusdt@kline_12h', 'sxpusdt@kline_1d', 'kavausdt@kline_30m', 'kavausdt@kline_4h', 'kavausdt@kline_5m', 'kavausdt@kline_15m', 'kavausdt@kline_6h', 'kavausdt@kline_1m', 'kavausdt@kline_1h', 'kavausdt@kline_2h', 'kavausdt@kline_12h', 'kavausdt@kline_1d', 'bandusdt@kline_30m', 'bandusdt@kline_4h', 'bandusdt@kline_5m', 'bandusdt@kline_15m', 'bandusdt@kline_6h', 'bandusdt@kline_1m', 'bandusdt@kline_1h', 'bandusdt@kline_2h', 'bandusdt@kline_12h', 'bandusdt@kline_1d', 'rlcusdt@kline_30m', 'rlcusdt@kline_4h', 'rlcusdt@kline_5m', 'rlcusdt@kline_15m', 'rlcusdt@kline_6h', 'rlcusdt@kline_1m', 'rlcusdt@kline_1h', 'rlcusdt@kline_2h', 'rlcusdt@kline_12h', 'rlcusdt@kline_1d', 'wavesusdt@kline_30m', 'wavesusdt@kline_4h', 'wavesusdt@kline_5m', 'wavesusdt@kline_15m', 'wavesusdt@kline_6h', 'wavesusdt@kline_1m', 'wavesusdt@kline_1h', 'wavesusdt@kline_2h', 'wavesusdt@kline_12h', 'wavesusdt@kline_1d', 'mkrusdt@kline_30m', 'mkrusdt@kline_4h', 'mkrusdt@kline_5m', 'mkrusdt@kline_15m', 'mkrusdt@kline_6h', 'mkrusdt@kline_1m', 'mkrusdt@kline_1h', 'mkrusdt@kline_2h', 'mkrusdt@kline_12h', 'mkrusdt@kline_1d', 'snxusdt@kline_30m', 'snxusdt@kline_4h', 'snxusdt@kline_5m', 'snxusdt@kline_15m', 'snxusdt@kline_6h', 'snxusdt@kline_1m', 'snxusdt@kline_1h', 'snxusdt@kline_2h', 'snxusdt@kline_12h', 'snxusdt@kline_1d', 'dotusdt@kline_30m', 'dotusdt@kline_4h', 'dotusdt@kline_5m', 'dotusdt@kline_15m', 'dotusdt@kline_6h', 'dotusdt@kline_1m', 'dotusdt@kline_1h', 'dotusdt@kline_2h', 'dotusdt@kline_12h', 'dotusdt@kline_1d', 'defiusdt@kline_30m', 'defiusdt@kline_4h', 'defiusdt@kline_5m', 'defiusdt@kline_15m', 'defiusdt@kline_6h', 'defiusdt@kline_1m', 'defiusdt@kline_1h', 'defiusdt@kline_2h', 'defiusdt@kline_12h', 'defiusdt@kline_1d', 'yfiusdt@kline_30m', 'yfiusdt@kline_4h', 'yfiusdt@kline_5m', 'yfiusdt@kline_15m', 'yfiusdt@kline_6h', 'yfiusdt@kline_1m', 'yfiusdt@kline_1h', 'yfiusdt@kline_2h', 'yfiusdt@kline_12h', 'yfiusdt@kline_1d', 'balusdt@kline_30m', 'balusdt@kline_4h', 'balusdt@kline_5m', 'balusdt@kline_15m', 'balusdt@kline_6h', 'balusdt@kline_1m', 'balusdt@kline_1h', 'balusdt@kline_2h', 'balusdt@kline_12h', 'balusdt@kline_1d', 'crvusdt@kline_30m', 'crvusdt@kline_4h', 'crvusdt@kline_5m', 'crvusdt@kline_15m', 'crvusdt@kline_6h', 'crvusdt@kline_1m', 'crvusdt@kline_1h', 'crvusdt@kline_2h', 'crvusdt@kline_12h', 'crvusdt@kline_1d', 'trbusdt@kline_30m', 'trbusdt@kline_4h', 'trbusdt@kline_5m', 'trbusdt@kline_15m', 'trbusdt@kline_6h', 'trbusdt@kline_1m', 'trbusdt@kline_1h', 'trbusdt@kline_2h', 'trbusdt@kline_12h', 'trbusdt@kline_1d', 'runeusdt@kline_30m', 'runeusdt@kline_4h', 'runeusdt@kline_5m', 'runeusdt@kline_15m', 'runeusdt@kline_6h', 'runeusdt@kline_1m', 'runeusdt@kline_1h', 'runeusdt@kline_2h', 'runeusdt@kline_12h', 'runeusdt@kline_1d', 'sushiusdt@kline_30m', 'sushiusdt@kline_4h', 'sushiusdt@kline_5m', 'sushiusdt@kline_15m', 'sushiusdt@kline_6h', 'sushiusdt@kline_1m', 'sushiusdt@kline_1h', 'sushiusdt@kline_2h', 'sushiusdt@kline_12h', 'sushiusdt@kline_1d', 'srmusdt@kline_30m', 'srmusdt@kline_4h', 'srmusdt@kline_5m', 'srmusdt@kline_15m', 'srmusdt@kline_6h', 'srmusdt@kline_1m', 'srmusdt@kline_1h', 'srmusdt@kline_2h', 'srmusdt@kline_12h', 'srmusdt@kline_1d', 'egldusdt@kline_30m', 'egldusdt@kline_4h', 'egldusdt@kline_5m', 'egldusdt@kline_15m', 'egldusdt@kline_6h', 'egldusdt@kline_1m', 'egldusdt@kline_1h', 'egldusdt@kline_2h', 'egldusdt@kline_12h', 'egldusdt@kline_1d', 'solusdt@kline_30m', 'solusdt@kline_4h', 'solusdt@kline_5m', 'solusdt@kline_15m', 'solusdt@kline_6h', 'solusdt@kline_1m', 'solusdt@kline_1h', 'solusdt@kline_2h', 'solusdt@kline_12h', 'solusdt@kline_1d', 'icxusdt@kline_30m', 'icxusdt@kline_4h', 'icxusdt@kline_5m', 'icxusdt@kline_15m', 'icxusdt@kline_6h', 'icxusdt@kline_1m', 'icxusdt@kline_1h', 'icxusdt@kline_2h', 'icxusdt@kline_12h', 'icxusdt@kline_1d', 'storjusdt@kline_30m', 'storjusdt@kline_4h', 'storjusdt@kline_5m', 'storjusdt@kline_15m', 'storjusdt@kline_6h', 'storjusdt@kline_1m', 'storjusdt@kline_1h', 'storjusdt@kline_2h', 'storjusdt@kline_12h', 'storjusdt@kline_1d', 'blzusdt@kline_30m', 'blzusdt@kline_4h', 'blzusdt@kline_5m', 'blzusdt@kline_15m', 'blzusdt@kline_6h', 'blzusdt@kline_1m', 'blzusdt@kline_1h', 'blzusdt@kline_2h', 'blzusdt@kline_12h', 'blzusdt@kline_1d', 'uniusdt@kline_30m', 'uniusdt@kline_4h', 'uniusdt@kline_5m', 'uniusdt@kline_15m', 'uniusdt@kline_6h', 'uniusdt@kline_1m', 'uniusdt@kline_1h', 'uniusdt@kline_2h', 'uniusdt@kline_12h', 'uniusdt@kline_1d', 'avaxusdt@kline_30m', 'avaxusdt@kline_4h', 'avaxusdt@kline_5m', 'avaxusdt@kline_15m', 'avaxusdt@kline_6h', 'avaxusdt@kline_1m', 'avaxusdt@kline_1h', 'avaxusdt@kline_2h', 'avaxusdt@kline_12h', 'avaxusdt@kline_1d', 'ftmusdt@kline_30m', 'ftmusdt@kline_4h', 'ftmusdt@kline_5m', 'ftmusdt@kline_15m', 'ftmusdt@kline_6h', 'ftmusdt@kline_1m', 'ftmusdt@kline_1h', 'ftmusdt@kline_2h', 'ftmusdt@kline_12h', 'ftmusdt@kline_1d', 'hntusdt@kline_30m', 'hntusdt@kline_4h', 'hntusdt@kline_5m', 'hntusdt@kline_15m', 'hntusdt@kline_6h', 'hntusdt@kline_1m', 'hntusdt@kline_1h', 'hntusdt@kline_2h', 'hntusdt@kline_12h', 'hntusdt@kline_1d', 'enjusdt@kline_30m', 'enjusdt@kline_4h', 'enjusdt@kline_5m', 'enjusdt@kline_15m', 'enjusdt@kline_6h', 'enjusdt@kline_1m', 'enjusdt@kline_1h', 'enjusdt@kline_2h', 'enjusdt@kline_12h', 'enjusdt@kline_1d', 'flmusdt@kline_30m', 'flmusdt@kline_4h', 'flmusdt@kline_5m', 'flmusdt@kline_15m', 'flmusdt@kline_6h', 'flmusdt@kline_1m', 'flmusdt@kline_1h', 'flmusdt@kline_2h', 'flmusdt@kline_12h', 'flmusdt@kline_1d', 'tomousdt@kline_30m', 'tomousdt@kline_4h', 'tomousdt@kline_5m', 'tomousdt@kline_15m', 'tomousdt@kline_6h', 'tomousdt@kline_1m', 'tomousdt@kline_1h', 'tomousdt@kline_2h', 'tomousdt@kline_12h', 'tomousdt@kline_1d', 'renusdt@kline_30m', 'renusdt@kline_4h', 'renusdt@kline_5m', 'renusdt@kline_15m', 'renusdt@kline_6h', 'renusdt@kline_1m', 'renusdt@kline_1h', 'renusdt@kline_2h', 'renusdt@kline_12h', 'renusdt@kline_1d', 'ksmusdt@kline_30m', 'ksmusdt@kline_4h', 'ksmusdt@kline_5m', 'ksmusdt@kline_15m', 'ksmusdt@kline_6h', 'ksmusdt@kline_1m', 'ksmusdt@kline_1h', 'ksmusdt@kline_2h', 'ksmusdt@kline_12h', 'ksmusdt@kline_1d', 'nearusdt@kline_30m', 'nearusdt@kline_4h', 'nearusdt@kline_5m', 'nearusdt@kline_15m', 'nearusdt@kline_6h', 'nearusdt@kline_1m', 'nearusdt@kline_1h', 'nearusdt@kline_2h', 'nearusdt@kline_12h', 'nearusdt@kline_1d', 'aaveusdt@kline_30m', 'aaveusdt@kline_4h', 'aaveusdt@kline_5m', 'aaveusdt@kline_15m', 'aaveusdt@kline_6h', 'aaveusdt@kline_1m', 'aaveusdt@kline_1h', 'aaveusdt@kline_2h', 'aaveusdt@kline_12h', 'aaveusdt@kline_1d', 'filusdt@kline_30m', 'filusdt@kline_4h', 'filusdt@kline_5m', 'filusdt@kline_15m', 'filusdt@kline_6h', 'filusdt@kline_1m', 'filusdt@kline_1h', 'filusdt@kline_2h', 'filusdt@kline_12h', 'filusdt@kline_1d', 'rsrusdt@kline_30m', 'rsrusdt@kline_4h', 'rsrusdt@kline_5m', 'rsrusdt@kline_15m', 'rsrusdt@kline_6h', 'rsrusdt@kline_1m', 'rsrusdt@kline_1h', 'rsrusdt@kline_2h', 'rsrusdt@kline_12h', 'rsrusdt@kline_1d', 'lrcusdt@kline_30m', 'lrcusdt@kline_4h', 'lrcusdt@kline_5m', 'lrcusdt@kline_15m', 'lrcusdt@kline_6h', 'lrcusdt@kline_1m', 'lrcusdt@kline_1h', 'lrcusdt@kline_2h', 'lrcusdt@kline_12h', 'lrcusdt@kline_1d', 'maticusdt@kline_30m', 'maticusdt@kline_4h', 'maticusdt@kline_5m', 'maticusdt@kline_15m', 'maticusdt@kline_6h', 'maticusdt@kline_1m', 'maticusdt@kline_1h', 'maticusdt@kline_2h', 'maticusdt@kline_12h', 'maticusdt@kline_1d', 'oceanusdt@kline_30m', 'oceanusdt@kline_4h', 'oceanusdt@kline_5m', 'oceanusdt@kline_15m', 'oceanusdt@kline_6h', 'oceanusdt@kline_1m', 'oceanusdt@kline_1h', 'oceanusdt@kline_2h', 'oceanusdt@kline_12h', 'oceanusdt@kline_1d', 'cvcusdt@kline_30m', 'cvcusdt@kline_4h', 'cvcusdt@kline_5m', 'cvcusdt@kline_15m', 'cvcusdt@kline_6h', 'cvcusdt@kline_1m', 'cvcusdt@kline_1h', 'cvcusdt@kline_2h', 'cvcusdt@kline_12h', 'cvcusdt@kline_1d', 'belusdt@kline_30m', 'belusdt@kline_4h', 'belusdt@kline_5m', 'belusdt@kline_15m', 'belusdt@kline_6h', 'belusdt@kline_1m', 'belusdt@kline_1h', 'belusdt@kline_2h', 'belusdt@kline_12h', 'belusdt@kline_1d', 'ctkusdt@kline_30m', 'ctkusdt@kline_4h', 'ctkusdt@kline_5m', 'ctkusdt@kline_15m', 'ctkusdt@kline_6h', 'ctkusdt@kline_1m', 'ctkusdt@kline_1h', 'ctkusdt@kline_2h', 'ctkusdt@kline_12h', 'ctkusdt@kline_1d', 'axsusdt@kline_30m', 'axsusdt@kline_4h', 'axsusdt@kline_5m', 'axsusdt@kline_15m', 'axsusdt@kline_6h', 'axsusdt@kline_1m', 'axsusdt@kline_1h', 'axsusdt@kline_2h', 'axsusdt@kline_12h', 'axsusdt@kline_1d', 'alphausdt@kline_30m', 'alphausdt@kline_4h', 'alphausdt@kline_5m', 'alphausdt@kline_15m', 'alphausdt@kline_6h', 'alphausdt@kline_1m', 'alphausdt@kline_1h', 'alphausdt@kline_2h', 'alphausdt@kline_12h', 'alphausdt@kline_1d', 'zenusdt@kline_30m', 'zenusdt@kline_4h', 'zenusdt@kline_5m', 'zenusdt@kline_15m', 'zenusdt@kline_6h', 'zenusdt@kline_1m', 'zenusdt@kline_1h', 'zenusdt@kline_2h', 'zenusdt@kline_12h', 'zenusdt@kline_1d', 'sklusdt@kline_30m', 'sklusdt@kline_4h', 'sklusdt@kline_5m', 'sklusdt@kline_15m', 'sklusdt@kline_6h', 'sklusdt@kline_1m', 'sklusdt@kline_1h', 'sklusdt@kline_2h', 'sklusdt@kline_12h', 'sklusdt@kline_1d', 'grtusdt@kline_30m', 'grtusdt@kline_4h', 'grtusdt@kline_5m', 'grtusdt@kline_15m', 'grtusdt@kline_6h', 'grtusdt@kline_1m', 'grtusdt@kline_1h', 'grtusdt@kline_2h', 'grtusdt@kline_12h', 'grtusdt@kline_1d', '1inchusdt@kline_30m', '1inchusdt@kline_4h', '1inchusdt@kline_5m', '1inchusdt@kline_15m', '1inchusdt@kline_6h', '1inchusdt@kline_1m', '1inchusdt@kline_1h', '1inchusdt@kline_2h', '1inchusdt@kline_12h', '1inchusdt@kline_1d', 'btcbusd@kline_30m', 'btcbusd@kline_4h', 'btcbusd@kline_5m', 'btcbusd@kline_15m', 'btcbusd@kline_6h', 'btcbusd@kline_1m', 'btcbusd@kline_1h', 'btcbusd@kline_2h', 'btcbusd@kline_12h', 'btcbusd@kline_1d', 'chzusdt@kline_30m', 'chzusdt@kline_4h', 'chzusdt@kline_5m', 'chzusdt@kline_15m', 'chzusdt@kline_6h', 'chzusdt@kline_1m', 'chzusdt@kline_1h', 'chzusdt@kline_2h', 'chzusdt@kline_12h', 'chzusdt@kline_1d', 'sandusdt@kline_30m', 'sandusdt@kline_4h', 'sandusdt@kline_5m', 'sandusdt@kline_15m', 'sandusdt@kline_6h', 'sandusdt@kline_1m', 'sandusdt@kline_1h', 'sandusdt@kline_2h', 'sandusdt@kline_12h', 'sandusdt@kline_1d', 'ankrusdt@kline_30m', 'ankrusdt@kline_4h', 'ankrusdt@kline_5m', 'ankrusdt@kline_15m', 'ankrusdt@kline_6h', 'ankrusdt@kline_1m', 'ankrusdt@kline_1h', 'ankrusdt@kline_2h', 'ankrusdt@kline_12h', 'ankrusdt@kline_1d', 'btsusdt@kline_30m', 'btsusdt@kline_4h', 'btsusdt@kline_5m', 'btsusdt@kline_15m', 'btsusdt@kline_6h', 'btsusdt@kline_1m', 'btsusdt@kline_1h', 'btsusdt@kline_2h', 'btsusdt@kline_12h', 'btsusdt@kline_1d', 'litusdt@kline_30m', 'litusdt@kline_4h', 'litusdt@kline_5m', 'litusdt@kline_15m', 'litusdt@kline_6h', 'litusdt@kline_1m', 'litusdt@kline_1h', 'litusdt@kline_2h', 'litusdt@kline_12h', 'litusdt@kline_1d', 'unfiusdt@kline_30m', 'unfiusdt@kline_4h', 'unfiusdt@kline_5m', 'unfiusdt@kline_15m', 'unfiusdt@kline_6h', 'unfiusdt@kline_1m', 'unfiusdt@kline_1h', 'unfiusdt@kline_2h', 'unfiusdt@kline_12h', 'unfiusdt@kline_1d', 'reefusdt@kline_30m', 'reefusdt@kline_4h', 'reefusdt@kline_5m', 'reefusdt@kline_15m', 'reefusdt@kline_6h', 'reefusdt@kline_1m', 'reefusdt@kline_1h', 'reefusdt@kline_2h', 'reefusdt@kline_12h', 'reefusdt@kline_1d', 'rvnusdt@kline_30m', 'rvnusdt@kline_4h', 'rvnusdt@kline_5m', 'rvnusdt@kline_15m', 'rvnusdt@kline_6h', 'rvnusdt@kline_1m', 'rvnusdt@kline_1h', 'rvnusdt@kline_2h', 'rvnusdt@kline_12h', 'rvnusdt@kline_1d', 'sfpusdt@kline_30m', 'sfpusdt@kline_4h', 'sfpusdt@kline_5m', 'sfpusdt@kline_15m', 'sfpusdt@kline_6h', 'sfpusdt@kline_1m', 'sfpusdt@kline_1h', 'sfpusdt@kline_2h', 'sfpusdt@kline_12h', 'sfpusdt@kline_1d', 'xemusdt@kline_30m', 'xemusdt@kline_4h', 'xemusdt@kline_5m', 'xemusdt@kline_15m', 'xemusdt@kline_6h', 'xemusdt@kline_1m', 'xemusdt@kline_1h', 'xemusdt@kline_2h', 'xemusdt@kline_12h', 'xemusdt@kline_1d', 'btcstusdt@kline_30m', 'btcstusdt@kline_4h', 'btcstusdt@kline_5m', 'btcstusdt@kline_15m', 'btcstusdt@kline_6h', 'btcstusdt@kline_1m', 'btcstusdt@kline_1h', 'btcstusdt@kline_2h', 'btcstusdt@kline_12h', 'btcstusdt@kline_1d', 'cotiusdt@kline_30m', 'cotiusdt@kline_4h', 'cotiusdt@kline_5m', 'cotiusdt@kline_15m', 'cotiusdt@kline_6h', 'cotiusdt@kline_1m', 'cotiusdt@kline_1h', 'cotiusdt@kline_2h', 'cotiusdt@kline_12h', 'cotiusdt@kline_1d', 'chrusdt@kline_30m', 'chrusdt@kline_4h', 'chrusdt@kline_5m', 'chrusdt@kline_15m', 'chrusdt@kline_6h', 'chrusdt@kline_1m', 'chrusdt@kline_1h', 'chrusdt@kline_2h', 'chrusdt@kline_12h', 'chrusdt@kline_1d', 'manausdt@kline_30m', 'manausdt@kline_4h', 'manausdt@kline_5m', 'manausdt@kline_15m', 'manausdt@kline_6h', 'manausdt@kline_1m', 'manausdt@kline_1h', 'manausdt@kline_2h', 'manausdt@kline_12h', 'manausdt@kline_1d', 'aliceusdt@kline_30m', 'aliceusdt@kline_4h', 'aliceusdt@kline_5m', 'aliceusdt@kline_15m', 'aliceusdt@kline_6h', 'aliceusdt@kline_1m', 'aliceusdt@kline_1h', 'aliceusdt@kline_2h', 'aliceusdt@kline_12h', 'aliceusdt@kline_1d', 'hbarusdt@kline_30m', 'hbarusdt@kline_4h', 'hbarusdt@kline_5m', 'hbarusdt@kline_15m', 'hbarusdt@kline_6h', 'hbarusdt@kline_1m', 'hbarusdt@kline_1h', 'hbarusdt@kline_2h', 'hbarusdt@kline_12h', 'hbarusdt@kline_1d', 'oneusdt@kline_30m', 'oneusdt@kline_4h', 'oneusdt@kline_5m', 'oneusdt@kline_15m', 'oneusdt@kline_6h', 'oneusdt@kline_1m', 'oneusdt@kline_1h', 'oneusdt@kline_2h', 'oneusdt@kline_12h', 'oneusdt@kline_1d', 'linausdt@kline_30m', 'linausdt@kline_4h', 'linausdt@kline_5m', 'linausdt@kline_15m', 'linausdt@kline_6h', 'linausdt@kline_1m', 'linausdt@kline_1h', 'linausdt@kline_2h', 'linausdt@kline_12h', 'linausdt@kline_1d', 'stmxusdt@kline_30m', 'stmxusdt@kline_4h', 'stmxusdt@kline_5m', 'stmxusdt@kline_15m', 'stmxusdt@kline_6h', 'stmxusdt@kline_1m', 'stmxusdt@kline_1h', 'stmxusdt@kline_2h', 'stmxusdt@kline_12h', 'stmxusdt@kline_1d', 'dentusdt@kline_30m', 'dentusdt@kline_4h', 'dentusdt@kline_5m', 'dentusdt@kline_15m', 'dentusdt@kline_6h', 'dentusdt@kline_1m', 'dentusdt@kline_1h', 'dentusdt@kline_2h', 'dentusdt@kline_12h', 'dentusdt@kline_1d', 'celrusdt@kline_30m', 'celrusdt@kline_4h', 'celrusdt@kline_5m', 'celrusdt@kline_15m', 'celrusdt@kline_6h', 'celrusdt@kline_1m', 'celrusdt@kline_1h', 'celrusdt@kline_2h', 'celrusdt@kline_12h', 'celrusdt@kline_1d', 'hotusdt@kline_30m', 'hotusdt@kline_4h', 'hotusdt@kline_5m', 'hotusdt@kline_15m', 'hotusdt@kline_6h', 'hotusdt@kline_1m', 'hotusdt@kline_1h', 'hotusdt@kline_2h', 'hotusdt@kline_12h', 'hotusdt@kline_1d', 'mtlusdt@kline_30m', 'mtlusdt@kline_4h', 'mtlusdt@kline_5m', 'mtlusdt@kline_15m', 'mtlusdt@kline_6h', 'mtlusdt@kline_1m', 'mtlusdt@kline_1h', 'mtlusdt@kline_2h', 'mtlusdt@kline_12h', 'mtlusdt@kline_1d', 'ognusdt@kline_30m', 'ognusdt@kline_4h', 'ognusdt@kline_5m', 'ognusdt@kline_15m', 'ognusdt@kline_6h', 'ognusdt@kline_1m', 'ognusdt@kline_1h', 'ognusdt@kline_2h', 'ognusdt@kline_12h', 'ognusdt@kline_1d', 'nknusdt@kline_30m', 'nknusdt@kline_4h', 'nknusdt@kline_5m', 'nknusdt@kline_15m', 'nknusdt@kline_6h', 'nknusdt@kline_1m', 'nknusdt@kline_1h', 'nknusdt@kline_2h', 'nknusdt@kline_12h', 'nknusdt@kline_1d', 'scusdt@kline_30m', 'scusdt@kline_4h', 'scusdt@kline_5m', 'scusdt@kline_15m', 'scusdt@kline_6h', 'scusdt@kline_1m', 'scusdt@kline_1h', 'scusdt@kline_2h', 'scusdt@kline_12h', 'scusdt@kline_1d', 'dgbusdt@kline_30m', 'dgbusdt@kline_4h', 'dgbusdt@kline_5m', 'dgbusdt@kline_15m', 'dgbusdt@kline_6h', 'dgbusdt@kline_1m', 'dgbusdt@kline_1h', 'dgbusdt@kline_2h', 'dgbusdt@kline_12h', 'dgbusdt@kline_1d', '1000shibusdt@kline_30m', '1000shibusdt@kline_4h', '1000shibusdt@kline_5m', '1000shibusdt@kline_15m', '1000shibusdt@kline_6h', '1000shibusdt@kline_1m', '1000shibusdt@kline_1h', '1000shibusdt@kline_2h', '1000shibusdt@kline_12h', '1000shibusdt@kline_1d', 'icpusdt@kline_30m', 'icpusdt@kline_4h', 'icpusdt@kline_5m', 'icpusdt@kline_15m', 'icpusdt@kline_6h', 'icpusdt@kline_1m', 'icpusdt@kline_1h', 'icpusdt@kline_2h', 'icpusdt@kline_12h', 'icpusdt@kline_1d', 'bakeusdt@kline_30m', 'bakeusdt@kline_4h', 'bakeusdt@kline_5m', 'bakeusdt@kline_15m', 'bakeusdt@kline_6h', 'bakeusdt@kline_1m', 'bakeusdt@kline_1h', 'bakeusdt@kline_2h', 'bakeusdt@kline_12h', 'bakeusdt@kline_1d', 'gtcusdt@kline_30m', 'gtcusdt@kline_4h', 'gtcusdt@kline_5m', 'gtcusdt@kline_15m', 'gtcusdt@kline_6h', 'gtcusdt@kline_1m', 'gtcusdt@kline_1h', 'gtcusdt@kline_2h', 'gtcusdt@kline_12h', 'gtcusdt@kline_1d', 'ethbusd@kline_30m', 'ethbusd@kline_4h', 'ethbusd@kline_5m', 'ethbusd@kline_15m', 'ethbusd@kline_6h', 'ethbusd@kline_1m', 'ethbusd@kline_1h', 'ethbusd@kline_2h', 'ethbusd@kline_12h', 'ethbusd@kline_1d', 'btcdomusdt@kline_30m', 'btcdomusdt@kline_4h', 'btcdomusdt@kline_5m', 'btcdomusdt@kline_15m', 'btcdomusdt@kline_6h', 'btcdomusdt@kline_1m', 'btcdomusdt@kline_1h', 'btcdomusdt@kline_2h', 'btcdomusdt@kline_12h', 'btcdomusdt@kline_1d', 'tlmusdt@kline_30m', 'tlmusdt@kline_4h', 'tlmusdt@kline_5m', 'tlmusdt@kline_15m', 'tlmusdt@kline_6h', 'tlmusdt@kline_1m', 'tlmusdt@kline_1h', 'tlmusdt@kline_2h', 'tlmusdt@kline_12h', 'tlmusdt@kline_1d', 'bnbbusd@kline_30m', 'bnbbusd@kline_4h', 'bnbbusd@kline_5m', 'bnbbusd@kline_15m', 'bnbbusd@kline_6h', 'bnbbusd@kline_1m', 'bnbbusd@kline_1h', 'bnbbusd@kline_2h', 'bnbbusd@kline_12h', 'bnbbusd@kline_1d', 'adabusd@kline_30m', 'adabusd@kline_4h', 'adabusd@kline_5m', 'adabusd@kline_15m', 'adabusd@kline_6h', 'adabusd@kline_1m', 'adabusd@kline_1h', 'adabusd@kline_2h', 'adabusd@kline_12h', 'adabusd@kline_1d', 'xrpbusd@kline_30m', 'xrpbusd@kline_4h', 'xrpbusd@kline_5m', 'xrpbusd@kline_15m', 'xrpbusd@kline_6h', 'xrpbusd@kline_1m', 'xrpbusd@kline_1h', 'xrpbusd@kline_2h', 'xrpbusd@kline_12h', 'xrpbusd@kline_1d', 'iotxusdt@kline_30m', 'iotxusdt@kline_4h', 'iotxusdt@kline_5m', 'iotxusdt@kline_15m', 'iotxusdt@kline_6h', 'iotxusdt@kline_1m', 'iotxusdt@kline_1h', 'iotxusdt@kline_2h', 'iotxusdt@kline_12h', 'iotxusdt@kline_1d', 'dogebusd@kline_30m', 'dogebusd@kline_4h', 'dogebusd@kline_5m', 'dogebusd@kline_15m', 'dogebusd@kline_6h', 'dogebusd@kline_1m', 'dogebusd@kline_1h', 'dogebusd@kline_2h', 'dogebusd@kline_12h', 'dogebusd@kline_1d', 'audiousdt@kline_30m', 'audiousdt@kline_4h', 'audiousdt@kline_5m', 'audiousdt@kline_15m', 'audiousdt@kline_6h', 'audiousdt@kline_1m', 'audiousdt@kline_1h', 'audiousdt@kline_2h', 'audiousdt@kline_12h', 'audiousdt@kline_1d', 'rayusdt@kline_30m', 'rayusdt@kline_4h', 'rayusdt@kline_5m', 'rayusdt@kline_15m', 'rayusdt@kline_6h', 'rayusdt@kline_1m', 'rayusdt@kline_1h', 'rayusdt@kline_2h', 'rayusdt@kline_12h', 'rayusdt@kline_1d', 'c98usdt@kline_30m', 'c98usdt@kline_4h', 'c98usdt@kline_5m', 'c98usdt@kline_15m', 'c98usdt@kline_6h', 'c98usdt@kline_1m', 'c98usdt@kline_1h', 'c98usdt@kline_2h', 'c98usdt@kline_12h', 'c98usdt@kline_1d', 'maskusdt@kline_30m', 'maskusdt@kline_4h', 'maskusdt@kline_5m', 'maskusdt@kline_15m', 'maskusdt@kline_6h', 'maskusdt@kline_1m', 'maskusdt@kline_1h', 'maskusdt@kline_2h', 'maskusdt@kline_12h', 'maskusdt@kline_1d', 'atausdt@kline_30m', 'atausdt@kline_4h', 'atausdt@kline_5m', 'atausdt@kline_15m', 'atausdt@kline_6h', 'atausdt@kline_1m', 'atausdt@kline_1h', 'atausdt@kline_2h', 'atausdt@kline_12h', 'atausdt@kline_1d', 'solbusd@kline_30m', 'solbusd@kline_4h', 'solbusd@kline_5m', 'solbusd@kline_15m', 'solbusd@kline_6h', 'solbusd@kline_1m', 'solbusd@kline_1h', 'solbusd@kline_2h', 'solbusd@kline_12h', 'solbusd@kline_1d', 'fttbusd@kline_30m', 'fttbusd@kline_4h', 'fttbusd@kline_5m', 'fttbusd@kline_15m', 'fttbusd@kline_6h', 'fttbusd@kline_1m', 'fttbusd@kline_1h', 'fttbusd@kline_2h', 'fttbusd@kline_12h', 'fttbusd@kline_1d', 'dydxusdt@kline_30m', 'dydxusdt@kline_4h', 'dydxusdt@kline_5m', 'dydxusdt@kline_15m', 'dydxusdt@kline_6h', 'dydxusdt@kline_1m', 'dydxusdt@kline_1h', 'dydxusdt@kline_2h', 'dydxusdt@kline_12h', 'dydxusdt@kline_1d', '1000xecusdt@kline_30m', '1000xecusdt@kline_4h', '1000xecusdt@kline_5m', '1000xecusdt@kline_15m', '1000xecusdt@kline_6h', '1000xecusdt@kline_1m', '1000xecusdt@kline_1h', '1000xecusdt@kline_2h', '1000xecusdt@kline_12h', '1000xecusdt@kline_1d', 'galausdt@kline_30m', 'galausdt@kline_4h', 'galausdt@kline_5m', 'galausdt@kline_15m', 'galausdt@kline_6h', 'galausdt@kline_1m', 'galausdt@kline_1h', 'galausdt@kline_2h', 'galausdt@kline_12h', 'galausdt@kline_1d', 'celousdt@kline_30m', 'celousdt@kline_4h', 'celousdt@kline_5m', 'celousdt@kline_15m', 'celousdt@kline_6h', 'celousdt@kline_1m', 'celousdt@kline_1h', 'celousdt@kline_2h', 'celousdt@kline_12h', 'celousdt@kline_1d', 'arusdt@kline_30m', 'arusdt@kline_4h', 'arusdt@kline_5m', 'arusdt@kline_15m', 'arusdt@kline_6h', 'arusdt@kline_1m', 'arusdt@kline_1h', 'arusdt@kline_2h', 'arusdt@kline_12h', 'arusdt@kline_1d', 'klayusdt@kline_30m', 'klayusdt@kline_4h', 'klayusdt@kline_5m', 'klayusdt@kline_15m', 'klayusdt@kline_6h', 'klayusdt@kline_1m', 'klayusdt@kline_1h', 'klayusdt@kline_2h', 'klayusdt@kline_12h', 'klayusdt@kline_1d', 'arpausdt@kline_30m', 'arpausdt@kline_4h', 'arpausdt@kline_5m', 'arpausdt@kline_15m', 'arpausdt@kline_6h', 'arpausdt@kline_1m', 'arpausdt@kline_1h', 'arpausdt@kline_2h', 'arpausdt@kline_12h', 'arpausdt@kline_1d', 'ctsiusdt@kline_30m', 'ctsiusdt@kline_4h', 'ctsiusdt@kline_5m', 'ctsiusdt@kline_15m', 'ctsiusdt@kline_6h', 'ctsiusdt@kline_1m', 'ctsiusdt@kline_1h', 'ctsiusdt@kline_2h', 'ctsiusdt@kline_12h', 'ctsiusdt@kline_1d', 'lptusdt@kline_30m', 'lptusdt@kline_4h', 'lptusdt@kline_5m', 'lptusdt@kline_15m', 'lptusdt@kline_6h', 'lptusdt@kline_1m', 'lptusdt@kline_1h', 'lptusdt@kline_2h', 'lptusdt@kline_12h', 'lptusdt@kline_1d', 'ensusdt@kline_30m', 'ensusdt@kline_4h', 'ensusdt@kline_5m', 'ensusdt@kline_15m', 'ensusdt@kline_6h', 'ensusdt@kline_1m', 'ensusdt@kline_1h', 'ensusdt@kline_2h', 'ensusdt@kline_12h', 'ensusdt@kline_1d', 'peopleusdt@kline_30m', 'peopleusdt@kline_4h', 'peopleusdt@kline_5m', 'peopleusdt@kline_15m', 'peopleusdt@kline_6h', 'peopleusdt@kline_1m', 'peopleusdt@kline_1h', 'peopleusdt@kline_2h', 'peopleusdt@kline_12h', 'peopleusdt@kline_1d', 'antusdt@kline_30m', 'antusdt@kline_4h', 'antusdt@kline_5m', 'antusdt@kline_15m', 'antusdt@kline_6h', 'antusdt@kline_1m', 'antusdt@kline_1h', 'antusdt@kline_2h', 'antusdt@kline_12h', 'antusdt@kline_1d', 'roseusdt@kline_30m', 'roseusdt@kline_4h', 'roseusdt@kline_5m', 'roseusdt@kline_15m', 'roseusdt@kline_6h', 'roseusdt@kline_1m', 'roseusdt@kline_1h', 'roseusdt@kline_2h', 'roseusdt@kline_12h', 'roseusdt@kline_1d', 'duskusdt@kline_30m', 'duskusdt@kline_4h', 'duskusdt@kline_5m', 'duskusdt@kline_15m', 'duskusdt@kline_6h', 'duskusdt@kline_1m', 'duskusdt@kline_1h', 'duskusdt@kline_2h', 'duskusdt@kline_12h', 'duskusdt@kline_1d', 'flowusdt@kline_30m', 'flowusdt@kline_4h', 'flowusdt@kline_5m', 'flowusdt@kline_15m', 'flowusdt@kline_6h', 'flowusdt@kline_1m', 'flowusdt@kline_1h', 'flowusdt@kline_2h', 'flowusdt@kline_12h', 'flowusdt@kline_1d', 'imxusdt@kline_30m', 'imxusdt@kline_4h', 'imxusdt@kline_5m', 'imxusdt@kline_15m', 'imxusdt@kline_6h', 'imxusdt@kline_1m', 'imxusdt@kline_1h', 'imxusdt@kline_2h', 'imxusdt@kline_12h', 'imxusdt@kline_1d', 'api3usdt@kline_30m', 'api3usdt@kline_4h', 'api3usdt@kline_5m', 'api3usdt@kline_15m', 'api3usdt@kline_6h', 'api3usdt@kline_1m', 'api3usdt@kline_1h', 'api3usdt@kline_2h', 'api3usdt@kline_12h', 'api3usdt@kline_1d', 'gmtusdt@kline_30m', 'gmtusdt@kline_4h', 'gmtusdt@kline_5m', 'gmtusdt@kline_15m', 'gmtusdt@kline_6h', 'gmtusdt@kline_1m', 'gmtusdt@kline_1h', 'gmtusdt@kline_2h', 'gmtusdt@kline_12h', 'gmtusdt@kline_1d', 'apeusdt@kline_30m', 'apeusdt@kline_4h', 'apeusdt@kline_5m', 'apeusdt@kline_15m', 'apeusdt@kline_6h', 'apeusdt@kline_1m', 'apeusdt@kline_1h', 'apeusdt@kline_2h', 'apeusdt@kline_12h', 'apeusdt@kline_1d', 'bnxusdt@kline_30m', 'bnxusdt@kline_4h', 'bnxusdt@kline_5m', 'bnxusdt@kline_15m', 'bnxusdt@kline_6h', 'bnxusdt@kline_1m', 'bnxusdt@kline_1h', 'bnxusdt@kline_2h', 'bnxusdt@kline_12h', 'bnxusdt@kline_1d', 'woousdt@kline_30m', 'woousdt@kline_4h', 'woousdt@kline_5m', 'woousdt@kline_15m', 'woousdt@kline_6h', 'woousdt@kline_1m', 'woousdt@kline_1h', 'woousdt@kline_2h', 'woousdt@kline_12h', 'woousdt@kline_1d', 'fttusdt@kline_30m', 'fttusdt@kline_4h', 'fttusdt@kline_5m', 'fttusdt@kline_15m', 'fttusdt@kline_6h', 'fttusdt@kline_1m', 'fttusdt@kline_1h', 'fttusdt@kline_2h', 'fttusdt@kline_12h', 'fttusdt@kline_1d', 'jasmyusdt@kline_30m', 'jasmyusdt@kline_4h', 'jasmyusdt@kline_5m', 'jasmyusdt@kline_15m', 'jasmyusdt@kline_6h', 'jasmyusdt@kline_1m', 'jasmyusdt@kline_1h', 'jasmyusdt@kline_2h', 'jasmyusdt@kline_12h', 'jasmyusdt@kline_1d', 'darusdt@kline_30m', 'darusdt@kline_4h', 'darusdt@kline_5m', 'darusdt@kline_15m', 'darusdt@kline_6h', 'darusdt@kline_1m', 'darusdt@kline_1h', 'darusdt@kline_2h', 'darusdt@kline_12h', 'darusdt@kline_1d', 'galusdt@kline_30m', 'galusdt@kline_4h', 'galusdt@kline_5m', 'galusdt@kline_15m', 'galusdt@kline_6h', 'galusdt@kline_1m', 'galusdt@kline_1h', 'galusdt@kline_2h', 'galusdt@kline_12h', 'galusdt@kline_1d', 'avaxbusd@kline_30m', 'avaxbusd@kline_4h', 'avaxbusd@kline_5m', 'avaxbusd@kline_15m', 'avaxbusd@kline_6h', 'avaxbusd@kline_1m', 'avaxbusd@kline_1h', 'avaxbusd@kline_2h', 'avaxbusd@kline_12h', 'avaxbusd@kline_1d', 'nearbusd@kline_30m', 'nearbusd@kline_4h', 'nearbusd@kline_5m', 'nearbusd@kline_15m', 'nearbusd@kline_6h', 'nearbusd@kline_1m', 'nearbusd@kline_1h', 'nearbusd@kline_2h', 'nearbusd@kline_12h', 'nearbusd@kline_1d', 'gmtbusd@kline_30m', 'gmtbusd@kline_4h', 'gmtbusd@kline_5m', 'gmtbusd@kline_15m', 'gmtbusd@kline_6h', 'gmtbusd@kline_1m', 'gmtbusd@kline_1h', 'gmtbusd@kline_2h', 'gmtbusd@kline_12h', 'gmtbusd@kline_1d', 'apebusd@kline_30m', 'apebusd@kline_4h', 'apebusd@kline_5m', 'apebusd@kline_15m', 'apebusd@kline_6h', 'apebusd@kline_1m', 'apebusd@kline_1h', 'apebusd@kline_2h', 'apebusd@kline_12h', 'apebusd@kline_1d', 'galbusd@kline_30m', 'galbusd@kline_4h', 'galbusd@kline_5m', 'galbusd@kline_15m', 'galbusd@kline_6h', 'galbusd@kline_1m', 'galbusd@kline_1h', 'galbusd@kline_2h', 'galbusd@kline_12h', 'galbusd@kline_1d', 'ftmbusd@kline_30m', 'ftmbusd@kline_4h', 'ftmbusd@kline_5m', 'ftmbusd@kline_15m', 'ftmbusd@kline_6h', 'ftmbusd@kline_1m', 'ftmbusd@kline_1h', 'ftmbusd@kline_2h', 'ftmbusd@kline_12h', 'ftmbusd@kline_1d', 'dodobusd@kline_30m', 'dodobusd@kline_4h', 'dodobusd@kline_5m', 'dodobusd@kline_15m', 'dodobusd@kline_6h', 'dodobusd@kline_1m', 'dodobusd@kline_1h', 'dodobusd@kline_2h', 'dodobusd@kline_12h', 'dodobusd@kline_1d', 'ancbusd@kline_30m', 'ancbusd@kline_4h', 'ancbusd@kline_5m', 'ancbusd@kline_15m', 'ancbusd@kline_6h', 'ancbusd@kline_1m', 'ancbusd@kline_1h', 'ancbusd@kline_2h', 'ancbusd@kline_12h', 'ancbusd@kline_1d', 'galabusd@kline_30m', 'galabusd@kline_4h', 'galabusd@kline_5m', 'galabusd@kline_15m', 'galabusd@kline_6h', 'galabusd@kline_1m', 'galabusd@kline_1h', 'galabusd@kline_2h', 'galabusd@kline_12h', 'galabusd@kline_1d', 'trxbusd@kline_30m', 'trxbusd@kline_4h', 'trxbusd@kline_5m', 'trxbusd@kline_15m', 'trxbusd@kline_6h', 'trxbusd@kline_1m', 'trxbusd@kline_1h', 'trxbusd@kline_2h', 'trxbusd@kline_12h', 'trxbusd@kline_1d', '1000luncbusd@kline_30m', '1000luncbusd@kline_4h', '1000luncbusd@kline_5m', '1000luncbusd@kline_15m', '1000luncbusd@kline_6h', '1000luncbusd@kline_1m', '1000luncbusd@kline_1h', '1000luncbusd@kline_2h', '1000luncbusd@kline_12h', '1000luncbusd@kline_1d', 'luna2busd@kline_30m', 'luna2busd@kline_4h', 'luna2busd@kline_5m', 'luna2busd@kline_15m', 'luna2busd@kline_6h', 'luna2busd@kline_1m', 'luna2busd@kline_1h', 'luna2busd@kline_2h', 'luna2busd@kline_12h', 'luna2busd@kline_1d', 'opusdt@kline_30m', 'opusdt@kline_4h', 'opusdt@kline_5m', 'opusdt@kline_15m', 'opusdt@kline_6h', 'opusdt@kline_1m', 'opusdt@kline_1h', 'opusdt@kline_2h', 'opusdt@kline_12h', 'opusdt@kline_1d', 'dotbusd@kline_30m', 'dotbusd@kline_4h', 'dotbusd@kline_5m', 'dotbusd@kline_15m', 'dotbusd@kline_6h', 'dotbusd@kline_1m', 'dotbusd@kline_1h', 'dotbusd@kline_2h', 'dotbusd@kline_12h', 'dotbusd@kline_1d', 'tlmbusd@kline_30m', 'tlmbusd@kline_4h', 'tlmbusd@kline_5m', 'tlmbusd@kline_15m', 'tlmbusd@kline_6h', 'tlmbusd@kline_1m', 'tlmbusd@kline_1h', 'tlmbusd@kline_2h', 'tlmbusd@kline_12h', 'tlmbusd@kline_1d', 'icpbusd@kline_30m', 'icpbusd@kline_4h', 'icpbusd@kline_5m', 'icpbusd@kline_15m', 'icpbusd@kline_6h', 'icpbusd@kline_1m', 'icpbusd@kline_1h', 'icpbusd@kline_2h', 'icpbusd@kline_12h', 'icpbusd@kline_1d', 'btcusdt_220930@kline_30m', 'btcusdt_220930@kline_4h', 'btcusdt_220930@kline_5m', 'btcusdt_220930@kline_15m', 'btcusdt_220930@kline_6h', 'btcusdt_220930@kline_1m', 'btcusdt_220930@kline_1h', 'btcusdt_220930@kline_2h', 'btcusdt_220930@kline_12h', 'btcusdt_220930@kline_1d', 'ethusdt_220930@kline_30m', 'ethusdt_220930@kline_4h', 'ethusdt_220930@kline_5m', 'ethusdt_220930@kline_15m', 'ethusdt_220930@kline_6h', 'ethusdt_220930@kline_1m', 'ethusdt_220930@kline_1h', 'ethusdt_220930@kline_2h', 'ethusdt_220930@kline_12h', 'ethusdt_220930@kline_1d', 'wavesbusd@kline_30m', 'wavesbusd@kline_4h', 'wavesbusd@kline_5m', 'wavesbusd@kline_15m', 'wavesbusd@kline_6h', 'wavesbusd@kline_1m', 'wavesbusd@kline_1h', 'wavesbusd@kline_2h', 'wavesbusd@kline_12h', 'wavesbusd@kline_1d', 'linkbusd@kline_30m', 'linkbusd@kline_4h', 'linkbusd@kline_5m', 'linkbusd@kline_15m', 'linkbusd@kline_6h', 'linkbusd@kline_1m', 'linkbusd@kline_1h', 'linkbusd@kline_2h', 'linkbusd@kline_12h', 'linkbusd@kline_1d', 'sandbusd@kline_30m', 'sandbusd@kline_4h', 'sandbusd@kline_5m', 'sandbusd@kline_15m', 'sandbusd@kline_6h', 'sandbusd@kline_1m', 'sandbusd@kline_1h', 'sandbusd@kline_2h', 'sandbusd@kline_12h', 'sandbusd@kline_1d', 'ltcbusd@kline_30m', 'ltcbusd@kline_4h', 'ltcbusd@kline_5m', 'ltcbusd@kline_15m', 'ltcbusd@kline_6h', 'ltcbusd@kline_1m', 'ltcbusd@kline_1h', 'ltcbusd@kline_2h', 'ltcbusd@kline_12h', 'ltcbusd@kline_1d', 'maticbusd@kline_30m', 'maticbusd@kline_4h', 'maticbusd@kline_5m', 'maticbusd@kline_15m', 'maticbusd@kline_6h', 'maticbusd@kline_1m', 'maticbusd@kline_1h', 'maticbusd@kline_2h', 'maticbusd@kline_12h', 'maticbusd@kline_1d', 'cvxbusd@kline_30m', 'cvxbusd@kline_4h', 'cvxbusd@kline_5m', 'cvxbusd@kline_15m', 'cvxbusd@kline_6h', 'cvxbusd@kline_1m', 'cvxbusd@kline_1h', 'cvxbusd@kline_2h', 'cvxbusd@kline_12h', 'cvxbusd@kline_1d', 'filbusd@kline_30m', 'filbusd@kline_4h', 'filbusd@kline_5m', 'filbusd@kline_15m', 'filbusd@kline_6h', 'filbusd@kline_1m', 'filbusd@kline_1h', 'filbusd@kline_2h', 'filbusd@kline_12h', 'filbusd@kline_1d', '1000shibbusd@kline_30m', '1000shibbusd@kline_4h', '1000shibbusd@kline_5m', '1000shibbusd@kline_15m', '1000shibbusd@kline_6h', '1000shibbusd@kline_1m', '1000shibbusd@kline_1h', '1000shibbusd@kline_2h', '1000shibbusd@kline_12h', '1000shibbusd@kline_1d', 'leverbusd@kline_30m', 'leverbusd@kline_4h', 'leverbusd@kline_5m', 'leverbusd@kline_15m', 'leverbusd@kline_6h', 'leverbusd@kline_1m', 'leverbusd@kline_1h', 'leverbusd@kline_2h', 'leverbusd@kline_12h', 'leverbusd@kline_1d', 'etcbusd@kline_30m', 'etcbusd@kline_4h', 'etcbusd@kline_5m', 'etcbusd@kline_15m', 'etcbusd@kline_6h', 'etcbusd@kline_1m', 'etcbusd@kline_1h', 'etcbusd@kline_2h', 'etcbusd@kline_12h', 'etcbusd@kline_1d', 'ldobusd@kline_30m', 'ldobusd@kline_4h', 'ldobusd@kline_5m', 'ldobusd@kline_15m', 'ldobusd@kline_6h', 'ldobusd@kline_1m', 'ldobusd@kline_1h', 'ldobusd@kline_2h', 'ldobusd@kline_12h', 'ldobusd@kline_1d', 'unibusd@kline_30m', 'unibusd@kline_4h', 'unibusd@kline_5m', 'unibusd@kline_15m', 'unibusd@kline_6h', 'unibusd@kline_1m', 'unibusd@kline_1h', 'unibusd@kline_2h', 'unibusd@kline_12h', 'unibusd@kline_1d', 'auctionbusd@kline_30m', 'auctionbusd@kline_4h', 'auctionbusd@kline_5m', 'auctionbusd@kline_15m', 'auctionbusd@kline_6h', 'auctionbusd@kline_1m', 'auctionbusd@kline_1h', 'auctionbusd@kline_2h', 'auctionbusd@kline_12h', 'auctionbusd@kline_1d', 'injusdt@kline_30m', 'injusdt@kline_4h', 'injusdt@kline_5m', 'injusdt@kline_15m', 'injusdt@kline_6h', 'injusdt@kline_1m', 'injusdt@kline_1h', 'injusdt@kline_2h', 'injusdt@kline_12h', 'injusdt@kline_1d', 'stgusdt@kline_30m', 'stgusdt@kline_4h', 'stgusdt@kline_5m', 'stgusdt@kline_15m', 'stgusdt@kline_6h', 'stgusdt@kline_1m', 'stgusdt@kline_1h', 'stgusdt@kline_2h', 'stgusdt@kline_12h', 'stgusdt@kline_1d', 'footballusdt@kline_30m', 'footballusdt@kline_4h', 'footballusdt@kline_5m', 'footballusdt@kline_15m', 'footballusdt@kline_6h', 'footballusdt@kline_1m', 'footballusdt@kline_1h', 'footballusdt@kline_2h', 'footballusdt@kline_12h', 'footballusdt@kline_1d', 'spellusdt@kline_30m', 'spellusdt@kline_4h', 'spellusdt@kline_5m', 'spellusdt@kline_15m', 'spellusdt@kline_6h', 'spellusdt@kline_1m', 'spellusdt@kline_1h', 'spellusdt@kline_2h', 'spellusdt@kline_12h', 'spellusdt@kline_1d', '1000luncusdt@kline_30m', '1000luncusdt@kline_4h', '1000luncusdt@kline_5m', '1000luncusdt@kline_15m', '1000luncusdt@kline_6h', '1000luncusdt@kline_1m', '1000luncusdt@kline_1h', '1000luncusdt@kline_2h', '1000luncusdt@kline_12h', '1000luncusdt@kline_1d', 'luna2usdt@kline_30m', 'luna2usdt@kline_4h', 'luna2usdt@kline_5m', 'luna2usdt@kline_15m', 'luna2usdt@kline_6h', 'luna2usdt@kline_1m', 'luna2usdt@kline_1h', 'luna2usdt@kline_2h', 'luna2usdt@kline_12h', 'luna2usdt@kline_1d', 'ambbusd@kline_30m', 'ambbusd@kline_4h', 'ambbusd@kline_5m', 'ambbusd@kline_15m', 'ambbusd@kline_6h', 'ambbusd@kline_1m', 'ambbusd@kline_1h', 'ambbusd@kline_2h', 'ambbusd@kline_12h', 'ambbusd@kline_1d', 'phbbusd@kline_30m', 'phbbusd@kline_4h', 'phbbusd@kline_5m', 'phbbusd@kline_15m', 'phbbusd@kline_6h', 'phbbusd@kline_1m', 'phbbusd@kline_1h', 'phbbusd@kline_2h', 'phbbusd@kline_12h', 'phbbusd@kline_1d', 'ldousdt@kline_30m', 'ldousdt@kline_4h', 'ldousdt@kline_5m', 'ldousdt@kline_15m', 'ldousdt@kline_6h', 'ldousdt@kline_1m', 'ldousdt@kline_1h', 'ldousdt@kline_2h', 'ldousdt@kline_12h', 'ldousdt@kline_1d', 'cvxusdt@kline_30m', 'cvxusdt@kline_4h', 'cvxusdt@kline_5m', 'cvxusdt@kline_15m', 'cvxusdt@kline_6h', 'cvxusdt@kline_1m', 'cvxusdt@kline_1h', 'cvxusdt@kline_2h', 'cvxusdt@kline_12h', 'cvxusdt@kline_1d', 'btcusdt_221230@kline_30m', 'btcusdt_221230@kline_4h', 'btcusdt_221230@kline_5m', 'btcusdt_221230@kline_15m', 'btcusdt_221230@kline_6h', 'btcusdt_221230@kline_1m', 'btcusdt_221230@kline_1h', 'btcusdt_221230@kline_2h', 'btcusdt_221230@kline_12h', 'btcusdt_221230@kline_1d', 'ethusdt_221230@kline_30m', 'ethusdt_221230@kline_4h', 'ethusdt_221230@kline_5m', 'ethusdt_221230@kline_15m', 'ethusdt_221230@kline_6h', 'ethusdt_221230@kline_1m', 'ethusdt_221230@kline_1h', 'ethusdt_221230@kline_2h', 'ethusdt_221230@kline_12h', 'ethusdt_221230@kline_1d', 'btcusdt@depth@100ms', 'btcusdt@depth@1000ms', 'ethusdt@depth@100ms', 'ethusdt@depth@1000ms', 'bchusdt@depth@100ms', 'bchusdt@depth@1000ms', 'xrpusdt@depth@100ms', 'xrpusdt@depth@1000ms', 'eosusdt@depth@100ms', 'eosusdt@depth@1000ms', 'ltcusdt@depth@100ms', 'ltcusdt@depth@1000ms', 'trxusdt@depth@100ms', 'trxusdt@depth@1000ms', 'etcusdt@depth@100ms', 'etcusdt@depth@1000ms', 'linkusdt@depth@100ms', 'linkusdt@depth@1000ms', 'xlmusdt@depth@100ms', 'xlmusdt@depth@1000ms', 'adausdt@depth@100ms', 'adausdt@depth@1000ms', 'xmrusdt@depth@100ms', 'xmrusdt@depth@1000ms', 'dashusdt@depth@100ms', 'dashusdt@depth@1000ms', 'zecusdt@depth@100ms', 'zecusdt@depth@1000ms', 'xtzusdt@depth@100ms', 'xtzusdt@depth@1000ms', 'bnbusdt@depth@100ms', 'bnbusdt@depth@1000ms', 'atomusdt@depth@100ms', 'atomusdt@depth@1000ms', 'ontusdt@depth@100ms', 'ontusdt@depth@1000ms', 'iotausdt@depth@100ms', 'iotausdt@depth@1000ms', 'batusdt@depth@100ms', 'batusdt@depth@1000ms', 'vetusdt@depth@100ms', 'vetusdt@depth@1000ms', 'neousdt@depth@100ms', 'neousdt@depth@1000ms', 'qtumusdt@depth@100ms', 'qtumusdt@depth@1000ms', 'iostusdt@depth@100ms', 'iostusdt@depth@1000ms', 'thetausdt@depth@100ms', 'thetausdt@depth@1000ms', 'algousdt@depth@100ms', 'algousdt@depth@1000ms', 'zilusdt@depth@100ms', 'zilusdt@depth@1000ms', 'kncusdt@depth@100ms', 'kncusdt@depth@1000ms', 'zrxusdt@depth@100ms', 'zrxusdt@depth@1000ms', 'compusdt@depth@100ms', 'compusdt@depth@1000ms', 'omgusdt@depth@100ms', 'omgusdt@depth@1000ms', 'dogeusdt@depth@100ms', 'dogeusdt@depth@1000ms', 'sxpusdt@depth@100ms', 'sxpusdt@depth@1000ms', 'kavausdt@depth@100ms', 'kavausdt@depth@1000ms', 'bandusdt@depth@100ms', 'bandusdt@depth@1000ms', 'rlcusdt@depth@100ms', 'rlcusdt@depth@1000ms', 'wavesusdt@depth@100ms', 'wavesusdt@depth@1000ms', 'mkrusdt@depth@100ms', 'mkrusdt@depth@1000ms', 'snxusdt@depth@100ms', 'snxusdt@depth@1000ms', 'dotusdt@depth@100ms', 'dotusdt@depth@1000ms', 'defiusdt@depth@100ms', 'defiusdt@depth@1000ms', 'yfiusdt@depth@100ms', 'yfiusdt@depth@1000ms', 'balusdt@depth@100ms', 'balusdt@depth@1000ms', 'crvusdt@depth@100ms', 'crvusdt@depth@1000ms', 'trbusdt@depth@100ms', 'trbusdt@depth@1000ms', 'runeusdt@depth@100ms', 'runeusdt@depth@1000ms', 'sushiusdt@depth@100ms', 'sushiusdt@depth@1000ms', 'srmusdt@depth@100ms', 'srmusdt@depth@1000ms', 'egldusdt@depth@100ms', 'egldusdt@depth@1000ms', 'solusdt@depth@100ms', 'solusdt@depth@1000ms', 'icxusdt@depth@100ms', 'icxusdt@depth@1000ms', 'storjusdt@depth@100ms', 'storjusdt@depth@1000ms', 'blzusdt@depth@100ms', 'blzusdt@depth@1000ms', 'uniusdt@depth@100ms', 'uniusdt@depth@1000ms', 'avaxusdt@depth@100ms', 'avaxusdt@depth@1000ms', 'ftmusdt@depth@100ms', 'ftmusdt@depth@1000ms', 'hntusdt@depth@100ms', 'hntusdt@depth@1000ms', 'enjusdt@depth@100ms', 'enjusdt@depth@1000ms', 'flmusdt@depth@100ms', 'flmusdt@depth@1000ms', 'tomousdt@depth@100ms', 'tomousdt@depth@1000ms', 'renusdt@depth@100ms', 'renusdt@depth@1000ms', 'ksmusdt@depth@100ms', 'ksmusdt@depth@1000ms', 'nearusdt@depth@100ms', 'nearusdt@depth@1000ms', 'aaveusdt@depth@100ms', 'aaveusdt@depth@1000ms', 'filusdt@depth@100ms', 'filusdt@depth@1000ms', 'rsrusdt@depth@100ms', 'rsrusdt@depth@1000ms', 'lrcusdt@depth@100ms', 'lrcusdt@depth@1000ms', 'maticusdt@depth@100ms', 'maticusdt@depth@1000ms', 'oceanusdt@depth@100ms', 'oceanusdt@depth@1000ms', 'cvcusdt@depth@100ms', 'cvcusdt@depth@1000ms', 'belusdt@depth@100ms', 'belusdt@depth@1000ms', 'ctkusdt@depth@100ms', 'ctkusdt@depth@1000ms', 'axsusdt@depth@100ms', 'axsusdt@depth@1000ms', 'alphausdt@depth@100ms', 'alphausdt@depth@1000ms', 'zenusdt@depth@100ms', 'zenusdt@depth@1000ms', 'sklusdt@depth@100ms', 'sklusdt@depth@1000ms', 'grtusdt@depth@100ms', 'grtusdt@depth@1000ms', '1inchusdt@depth@100ms', '1inchusdt@depth@1000ms', 'btcbusd@depth@100ms', 'btcbusd@depth@1000ms', 'chzusdt@depth@100ms', 'chzusdt@depth@1000ms', 'sandusdt@depth@100ms', 'sandusdt@depth@1000ms', 'ankrusdt@depth@100ms', 'ankrusdt@depth@1000ms', 'btsusdt@depth@100ms', 'btsusdt@depth@1000ms', 'litusdt@depth@100ms', 'litusdt@depth@1000ms', 'unfiusdt@depth@100ms', 'unfiusdt@depth@1000ms', 'reefusdt@depth@100ms', 'reefusdt@depth@1000ms', 'rvnusdt@depth@100ms', 'rvnusdt@depth@1000ms', 'sfpusdt@depth@100ms', 'sfpusdt@depth@1000ms', 'xemusdt@depth@100ms', 'xemusdt@depth@1000ms', 'btcstusdt@depth@100ms', 'btcstusdt@depth@1000ms', 'cotiusdt@depth@100ms', 'cotiusdt@depth@1000ms', 'chrusdt@depth@100ms', 'chrusdt@depth@1000ms', 'manausdt@depth@100ms', 'manausdt@depth@1000ms', 'aliceusdt@depth@100ms', 'aliceusdt@depth@1000ms', 'hbarusdt@depth@100ms', 'hbarusdt@depth@1000ms', 'oneusdt@depth@100ms', 'oneusdt@depth@1000ms', 'linausdt@depth@100ms', 'linausdt@depth@1000ms', 'stmxusdt@depth@100ms', 'stmxusdt@depth@1000ms', 'dentusdt@depth@100ms', 'dentusdt@depth@1000ms', 'celrusdt@depth@100ms', 'celrusdt@depth@1000ms', 'hotusdt@depth@100ms', 'hotusdt@depth@1000ms', 'mtlusdt@depth@100ms', 'mtlusdt@depth@1000ms', 'ognusdt@depth@100ms', 'ognusdt@depth@1000ms', 'nknusdt@depth@100ms', 'nknusdt@depth@1000ms', 'scusdt@depth@100ms', 'scusdt@depth@1000ms', 'dgbusdt@depth@100ms', 'dgbusdt@depth@1000ms', '1000shibusdt@depth@100ms', '1000shibusdt@depth@1000ms', 'icpusdt@depth@100ms', 'icpusdt@depth@1000ms', 'bakeusdt@depth@100ms', 'bakeusdt@depth@1000ms', 'gtcusdt@depth@100ms', 'gtcusdt@depth@1000ms', 'ethbusd@depth@100ms', 'ethbusd@depth@1000ms', 'btcdomusdt@depth@100ms', 'btcdomusdt@depth@1000ms', 'tlmusdt@depth@100ms', 'tlmusdt@depth@1000ms', 'bnbbusd@depth@100ms', 'bnbbusd@depth@1000ms', 'adabusd@depth@100ms', 'adabusd@depth@1000ms', 'xrpbusd@depth@100ms', 'xrpbusd@depth@1000ms', 'iotxusdt@depth@100ms', 'iotxusdt@depth@1000ms', 'dogebusd@depth@100ms', 'dogebusd@depth@1000ms', 'audiousdt@depth@100ms', 'audiousdt@depth@1000ms', 'rayusdt@depth@100ms', 'rayusdt@depth@1000ms', 'c98usdt@depth@100ms', 'c98usdt@depth@1000ms', 'maskusdt@depth@100ms', 'maskusdt@depth@1000ms', 'atausdt@depth@100ms', 'atausdt@depth@1000ms', 'solbusd@depth@100ms', 'solbusd@depth@1000ms', 'fttbusd@depth@100ms', 'fttbusd@depth@1000ms', 'dydxusdt@depth@100ms', 'dydxusdt@depth@1000ms', '1000xecusdt@depth@100ms', '1000xecusdt@depth@1000ms', 'galausdt@depth@100ms', 'galausdt@depth@1000ms', 'celousdt@depth@100ms', 'celousdt@depth@1000ms', 'arusdt@depth@100ms', 'arusdt@depth@1000ms', 'klayusdt@depth@100ms', 'klayusdt@depth@1000ms', 'arpausdt@depth@100ms', 'arpausdt@depth@1000ms', 'ctsiusdt@depth@100ms', 'ctsiusdt@depth@1000ms', 'lptusdt@depth@100ms', 'lptusdt@depth@1000ms', 'ensusdt@depth@100ms', 'ensusdt@depth@1000ms', 'peopleusdt@depth@100ms', 'peopleusdt@depth@1000ms', 'antusdt@depth@100ms', 'antusdt@depth@1000ms', 'roseusdt@depth@100ms', 'roseusdt@depth@1000ms', 'duskusdt@depth@100ms', 'duskusdt@depth@1000ms', 'flowusdt@depth@100ms', 'flowusdt@depth@1000ms', 'imxusdt@depth@100ms', 'imxusdt@depth@1000ms', 'api3usdt@depth@100ms', 'api3usdt@depth@1000ms', 'gmtusdt@depth@100ms', 'gmtusdt@depth@1000ms', 'apeusdt@depth@100ms', 'apeusdt@depth@1000ms', 'bnxusdt@depth@100ms', 'bnxusdt@depth@1000ms', 'woousdt@depth@100ms', 'woousdt@depth@1000ms', 'fttusdt@depth@100ms', 'fttusdt@depth@1000ms', 'jasmyusdt@depth@100ms', 'jasmyusdt@depth@1000ms', 'darusdt@depth@100ms', 'darusdt@depth@1000ms', 'galusdt@depth@100ms', 'galusdt@depth@1000ms', 'avaxbusd@depth@100ms', 'avaxbusd@depth@1000ms', 'nearbusd@depth@100ms', 'nearbusd@depth@1000ms', 'gmtbusd@depth@100ms', 'gmtbusd@depth@1000ms', 'apebusd@depth@100ms', 'apebusd@depth@1000ms', 'galbusd@depth@100ms', 'galbusd@depth@1000ms', 'ftmbusd@depth@100ms', 'ftmbusd@depth@1000ms', 'dodobusd@depth@100ms', 'dodobusd@depth@1000ms', 'ancbusd@depth@100ms', 'ancbusd@depth@1000ms', 'galabusd@depth@100ms', 'galabusd@depth@1000ms', 'trxbusd@depth@100ms', 'trxbusd@depth@1000ms', '1000luncbusd@depth@100ms', '1000luncbusd@depth@1000ms', 'luna2busd@depth@100ms', 'luna2busd@depth@1000ms', 'opusdt@depth@100ms', 'opusdt@depth@1000ms', 'dotbusd@depth@100ms', 'dotbusd@depth@1000ms', 'tlmbusd@depth@100ms', 'tlmbusd@depth@1000ms', 'icpbusd@depth@100ms', 'icpbusd@depth@1000ms', 'btcusdt_220930@depth@100ms', 'btcusdt_220930@depth@1000ms', 'ethusdt_220930@depth@100ms', 'ethusdt_220930@depth@1000ms', 'wavesbusd@depth@100ms', 'wavesbusd@depth@1000ms', 'linkbusd@depth@100ms', 'linkbusd@depth@1000ms', 'sandbusd@depth@100ms', 'sandbusd@depth@1000ms', 'ltcbusd@depth@100ms', 'ltcbusd@depth@1000ms', 'maticbusd@depth@100ms', 'maticbusd@depth@1000ms', 'cvxbusd@depth@100ms', 'cvxbusd@depth@1000ms', 'filbusd@depth@100ms', 'filbusd@depth@1000ms', '1000shibbusd@depth@100ms', '1000shibbusd@depth@1000ms', 'leverbusd@depth@100ms', 'leverbusd@depth@1000ms', 'etcbusd@depth@100ms', 'etcbusd@depth@1000ms', 'ldobusd@depth@100ms', 'ldobusd@depth@1000ms', 'unibusd@depth@100ms', 'unibusd@depth@1000ms', 'auctionbusd@depth@100ms', 'auctionbusd@depth@1000ms', 'injusdt@depth@100ms', 'injusdt@depth@1000ms', 'stgusdt@depth@100ms', 'stgusdt@depth@1000ms', 'footballusdt@depth@100ms', 'footballusdt@depth@1000ms', 'spellusdt@depth@100ms', 'spellusdt@depth@1000ms', '1000luncusdt@depth@100ms', '1000luncusdt@depth@1000ms', 'luna2usdt@depth@100ms', 'luna2usdt@depth@1000ms', 'ambbusd@depth@100ms', 'ambbusd@depth@1000ms', 'phbbusd@depth@100ms', 'phbbusd@depth@1000ms', 'ldousdt@depth@100ms', 'ldousdt@depth@1000ms', 'cvxusdt@depth@100ms', 'cvxusdt@depth@1000ms', 'btcusdt_221230@depth@100ms', 'btcusdt_221230@depth@1000ms', 'ethusdt_221230@depth@100ms', 'ethusdt_221230@depth@1000ms', 'btcusdt@aggTrade', 'ethusdt@aggTrade', 'bchusdt@aggTrade', 'xrpusdt@aggTrade', 'eosusdt@aggTrade', 'ltcusdt@aggTrade', 'trxusdt@aggTrade', 'etcusdt@aggTrade', 'linkusdt@aggTrade', 'xlmusdt@aggTrade', 'adausdt@aggTrade', 'xmrusdt@aggTrade', 'dashusdt@aggTrade', 'zecusdt@aggTrade', 'xtzusdt@aggTrade', 'bnbusdt@aggTrade', 'atomusdt@aggTrade', 'ontusdt@aggTrade', 'iotausdt@aggTrade', 'batusdt@aggTrade', 'vetusdt@aggTrade', 'neousdt@aggTrade', 'qtumusdt@aggTrade', 'iostusdt@aggTrade', 'thetausdt@aggTrade', 'algousdt@aggTrade', 'zilusdt@aggTrade', 'kncusdt@aggTrade', 'zrxusdt@aggTrade', 'compusdt@aggTrade', 'omgusdt@aggTrade', 'dogeusdt@aggTrade', 'sxpusdt@aggTrade', 'kavausdt@aggTrade', 'bandusdt@aggTrade', 'rlcusdt@aggTrade', 'wavesusdt@aggTrade', 'mkrusdt@aggTrade', 'snxusdt@aggTrade', 'dotusdt@aggTrade', 'defiusdt@aggTrade', 'yfiusdt@aggTrade', 'balusdt@aggTrade', 'crvusdt@aggTrade', 'trbusdt@aggTrade', 'runeusdt@aggTrade', 'sushiusdt@aggTrade', 'srmusdt@aggTrade', 'egldusdt@aggTrade', 'solusdt@aggTrade', 'icxusdt@aggTrade', 'storjusdt@aggTrade', 'blzusdt@aggTrade', 'uniusdt@aggTrade', 'avaxusdt@aggTrade', 'ftmusdt@aggTrade', 'hntusdt@aggTrade', 'enjusdt@aggTrade', 'flmusdt@aggTrade', 'tomousdt@aggTrade', 'renusdt@aggTrade', 'ksmusdt@aggTrade', 'nearusdt@aggTrade', 'aaveusdt@aggTrade', 'filusdt@aggTrade', 'rsrusdt@aggTrade', 'lrcusdt@aggTrade', 'maticusdt@aggTrade', 'oceanusdt@aggTrade', 'cvcusdt@aggTrade', 'belusdt@aggTrade', 'ctkusdt@aggTrade', 'axsusdt@aggTrade', 'alphausdt@aggTrade', 'zenusdt@aggTrade', 'sklusdt@aggTrade', 'grtusdt@aggTrade', '1inchusdt@aggTrade', 'btcbusd@aggTrade', 'chzusdt@aggTrade', 'sandusdt@aggTrade', 'ankrusdt@aggTrade', 'btsusdt@aggTrade', 'litusdt@aggTrade', 'unfiusdt@aggTrade', 'reefusdt@aggTrade', 'rvnusdt@aggTrade', 'sfpusdt@aggTrade', 'xemusdt@aggTrade', 'btcstusdt@aggTrade', 'cotiusdt@aggTrade', 'chrusdt@aggTrade', 'manausdt@aggTrade', 'aliceusdt@aggTrade', 'hbarusdt@aggTrade', 'oneusdt@aggTrade', 'linausdt@aggTrade', 'stmxusdt@aggTrade', 'dentusdt@aggTrade', 'celrusdt@aggTrade', 'hotusdt@aggTrade', 'mtlusdt@aggTrade', 'ognusdt@aggTrade', 'nknusdt@aggTrade', 'scusdt@aggTrade', 'dgbusdt@aggTrade', '1000shibusdt@aggTrade', 'icpusdt@aggTrade', 'bakeusdt@aggTrade', 'gtcusdt@aggTrade', 'ethbusd@aggTrade', 'btcdomusdt@aggTrade', 'tlmusdt@aggTrade', 'bnbbusd@aggTrade', 'adabusd@aggTrade', 'xrpbusd@aggTrade', 'iotxusdt@aggTrade', 'dogebusd@aggTrade', 'audiousdt@aggTrade', 'rayusdt@aggTrade', 'c98usdt@aggTrade', 'maskusdt@aggTrade', 'atausdt@aggTrade', 'solbusd@aggTrade', 'fttbusd@aggTrade', 'dydxusdt@aggTrade', '1000xecusdt@aggTrade', 'galausdt@aggTrade', 'celousdt@aggTrade', 'arusdt@aggTrade', 'klayusdt@aggTrade', 'arpausdt@aggTrade', 'ctsiusdt@aggTrade', 'lptusdt@aggTrade', 'ensusdt@aggTrade', 'peopleusdt@aggTrade', 'antusdt@aggTrade', 'roseusdt@aggTrade', 'duskusdt@aggTrade', 'flowusdt@aggTrade', 'imxusdt@aggTrade', 'api3usdt@aggTrade', 'gmtusdt@aggTrade', 'apeusdt@aggTrade', 'bnxusdt@aggTrade', 'woousdt@aggTrade', 'fttusdt@aggTrade', 'jasmyusdt@aggTrade', 'darusdt@aggTrade', 'galusdt@aggTrade', 'avaxbusd@aggTrade', 'nearbusd@aggTrade', 'gmtbusd@aggTrade', 'apebusd@aggTrade', 'galbusd@aggTrade', 'ftmbusd@aggTrade', 'dodobusd@aggTrade', 'ancbusd@aggTrade', 'galabusd@aggTrade', 'trxbusd@aggTrade', '1000luncbusd@aggTrade', 'luna2busd@aggTrade', 'opusdt@aggTrade', 'dotbusd@aggTrade', 'tlmbusd@aggTrade', 'icpbusd@aggTrade', 'btcusdt_220930@aggTrade', 'ethusdt_220930@aggTrade', 'wavesbusd@aggTrade', 'linkbusd@aggTrade', 'sandbusd@aggTrade', 'ltcbusd@aggTrade', 'maticbusd@aggTrade', 'cvxbusd@aggTrade', 'filbusd@aggTrade', '1000shibbusd@aggTrade', 'leverbusd@aggTrade', 'etcbusd@aggTrade', 'ldobusd@aggTrade', 'unibusd@aggTrade', 'auctionbusd@aggTrade', 'injusdt@aggTrade', 'stgusdt@aggTrade', 'footballusdt@aggTrade', 'spellusdt@aggTrade', '1000luncusdt@aggTrade', 'luna2usdt@aggTrade', 'ambbusd@aggTrade', 'phbbusd@aggTrade', 'ldousdt@aggTrade', 'cvxusdt@aggTrade', 'btcusdt_221230@aggTrade', 'ethusdt_221230@aggTrade', 'btcusdt@bookTicker', 'ethusdt@bookTicker', 'bchusdt@bookTicker', 'xrpusdt@bookTicker', 'eosusdt@bookTicker', 'ltcusdt@bookTicker', 'trxusdt@bookTicker', 'etcusdt@bookTicker', 'linkusdt@bookTicker', 'xlmusdt@bookTicker', 'adausdt@bookTicker', 'xmrusdt@bookTicker', 'dashusdt@bookTicker', 'zecusdt@bookTicker', 'xtzusdt@bookTicker', 'bnbusdt@bookTicker', 'atomusdt@bookTicker', 'ontusdt@bookTicker', 'iotausdt@bookTicker', 'batusdt@bookTicker', 'vetusdt@bookTicker', 'neousdt@bookTicker', 'qtumusdt@bookTicker', 'iostusdt@bookTicker', 'thetausdt@bookTicker', 'algousdt@bookTicker', 'zilusdt@bookTicker', 'kncusdt@bookTicker', 'zrxusdt@bookTicker', 'compusdt@bookTicker', 'omgusdt@bookTicker', 'dogeusdt@bookTicker', 'sxpusdt@bookTicker', 'kavausdt@bookTicker', 'bandusdt@bookTicker', 'rlcusdt@bookTicker', 'wavesusdt@bookTicker', 'mkrusdt@bookTicker', 'snxusdt@bookTicker', 'dotusdt@bookTicker', 'defiusdt@bookTicker', 'yfiusdt@bookTicker', 'balusdt@bookTicker', 'crvusdt@bookTicker', 'trbusdt@bookTicker', 'runeusdt@bookTicker', 'sushiusdt@bookTicker', 'srmusdt@bookTicker', 'egldusdt@bookTicker', 'solusdt@bookTicker', 'icxusdt@bookTicker', 'storjusdt@bookTicker', 'blzusdt@bookTicker', 'uniusdt@bookTicker', 'avaxusdt@bookTicker', 'ftmusdt@bookTicker', 'hntusdt@bookTicker', 'enjusdt@bookTicker', 'flmusdt@bookTicker', 'tomousdt@bookTicker', 'renusdt@bookTicker', 'ksmusdt@bookTicker', 'nearusdt@bookTicker', 'aaveusdt@bookTicker', 'filusdt@bookTicker', 'rsrusdt@bookTicker', 'lrcusdt@bookTicker', 'maticusdt@bookTicker', 'oceanusdt@bookTicker', 'cvcusdt@bookTicker', 'belusdt@bookTicker', 'ctkusdt@bookTicker', 'axsusdt@bookTicker', 'alphausdt@bookTicker', 'zenusdt@bookTicker', 'sklusdt@bookTicker', 'grtusdt@bookTicker', '1inchusdt@bookTicker', 'btcbusd@bookTicker', 'chzusdt@bookTicker', 'sandusdt@bookTicker', 'ankrusdt@bookTicker', 'btsusdt@bookTicker', 'litusdt@bookTicker', 'unfiusdt@bookTicker', 'reefusdt@bookTicker', 'rvnusdt@bookTicker', 'sfpusdt@bookTicker', 'xemusdt@bookTicker', 'btcstusdt@bookTicker', 'cotiusdt@bookTicker', 'chrusdt@bookTicker', 'manausdt@bookTicker', 'aliceusdt@bookTicker', 'hbarusdt@bookTicker', 'oneusdt@bookTicker', 'linausdt@bookTicker', 'stmxusdt@bookTicker', 'dentusdt@bookTicker', 'celrusdt@bookTicker', 'hotusdt@bookTicker', 'mtlusdt@bookTicker', 'ognusdt@bookTicker', 'nknusdt@bookTicker', 'scusdt@bookTicker', 'dgbusdt@bookTicker', '1000shibusdt@bookTicker', 'icpusdt@bookTicker', 'bakeusdt@bookTicker', 'gtcusdt@bookTicker', 'ethbusd@bookTicker', 'btcdomusdt@bookTicker', 'tlmusdt@bookTicker', 'bnbbusd@bookTicker', 'adabusd@bookTicker', 'xrpbusd@bookTicker', 'iotxusdt@bookTicker', 'dogebusd@bookTicker', 'audiousdt@bookTicker', 'rayusdt@bookTicker', 'c98usdt@bookTicker', 'maskusdt@bookTicker', 'atausdt@bookTicker', 'solbusd@bookTicker', 'fttbusd@bookTicker', 'dydxusdt@bookTicker', '1000xecusdt@bookTicker', 'galausdt@bookTicker', 'celousdt@bookTicker', 'arusdt@bookTicker', 'klayusdt@bookTicker', 'arpausdt@bookTicker', 'ctsiusdt@bookTicker', 'lptusdt@bookTicker', 'ensusdt@bookTicker', 'peopleusdt@bookTicker', 'antusdt@bookTicker', 'roseusdt@bookTicker', 'duskusdt@bookTicker', 'flowusdt@bookTicker', 'imxusdt@bookTicker', 'api3usdt@bookTicker', 'gmtusdt@bookTicker', 'apeusdt@bookTicker', 'bnxusdt@bookTicker', 'woousdt@bookTicker', 'fttusdt@bookTicker', 'jasmyusdt@bookTicker', 'darusdt@bookTicker', 'galusdt@bookTicker', 'avaxbusd@bookTicker', 'nearbusd@bookTicker', 'gmtbusd@bookTicker', 'apebusd@bookTicker', 'galbusd@bookTicker', 'ftmbusd@bookTicker', 'dodobusd@bookTicker', 'ancbusd@bookTicker', 'galabusd@bookTicker', 'trxbusd@bookTicker', '1000luncbusd@bookTicker', 'luna2busd@bookTicker', 'opusdt@bookTicker', 'dotbusd@bookTicker', 'tlmbusd@bookTicker', 'icpbusd@bookTicker', 'btcusdt_220930@bookTicker', 'ethusdt_220930@bookTicker', 'wavesbusd@bookTicker', 'linkbusd@bookTicker', 'sandbusd@bookTicker', 'ltcbusd@bookTicker', 'maticbusd@bookTicker', 'cvxbusd@bookTicker', 'filbusd@bookTicker', '1000shibbusd@bookTicker', 'leverbusd@bookTicker', 'etcbusd@bookTicker', 'ldobusd@bookTicker', 'unibusd@bookTicker', 'auctionbusd@bookTicker', 'injusdt@bookTicker', 'stgusdt@bookTicker', 'footballusdt@bookTicker', 'spellusdt@bookTicker', '1000luncusdt@bookTicker', 'luna2usdt@bookTicker', 'ambbusd@bookTicker', 'phbbusd@bookTicker', 'ldousdt@bookTicker', 'cvxusdt@bookTicker', 'btcusdt_221230@bookTicker', 'ethusdt_221230@bookTicker']
        chs = [item for sublist in subs for item in sublist]
        await self.subscribe(address, chs)

    async def subscribe(self, address, chan):
        def split_list(_list: list, n: int):
            for i in range(0, len(_list), n):
                yield _list[i:i + n]

        for channel in split_list(chan, 20):
            data = {
                "method": "SUBSCRIBE",
                "params": channel,
                "id": 1
            }
            self._reset()
            self._ws = Websocket(self._wss + address + '/'.join(channel), self.connected_callback, process_callback=self.process)
            await self._ws.send(data)

    async def connected_callback(self):
        """After websocket connection created successfully, pull back all open order information."""
        logger.info("Websocket connection authorized successfully", caller=self)
        SingleTask.run(self._init_callback, True)
        
    @async_method_locker("BinanceMarket.process.locker")
    async def process(self, msg):
        """Process message that received from Websocket connection.

        Args:
            msg: message received from Websocket connection.
        """
        # Handle REST endpoint messages first
        # if 'openInterest' in msg:
        #     return await self._open_interest(msg)

        # Combined stream events are wrapped as follows: {"stream":"<streamName>","data":<rawPayload>}
        # streamName is of format <symbol>@<channel>
        if 'stream' in msg:
            pair, _ = msg.get('stream').split('@', 1)
            msg = msg.get('data')
            if 'e' in msg:
                if msg['e'] == 'depthUpdate':
                    await self._book(msg, pair.upper())
                elif msg['e'] == 'aggTrade':
                    await self._trade(msg)
                elif msg['e'] == 'bookTicker':
                    await self._ticker(msg)
                elif msg['e'] == 'kline':
                    await self._candle(msg)
                else:
                    logger.warn("{}: Unexpected message received: {}".format(self._platform, msg))
        # elif 'A' in msg:
        #     await self._ticker(msg)
        else:
            logger.warn("{}: Unexpected message received: {}".format(self._platform, msg))

    @async_method_locker("BinanceMarket.process_private.locker")
    async def process_private(self, msg):
        """Process message that received from Websocket connection.

        Args:
            msg: message received from Websocket connection.
        """
        # Handle account updates from User Data Stream
        msg_type = msg.get('e')
        if msg_type == 'ACCOUNT_UPDATE':
            await self._asset(msg)
        elif msg_type == 'ORDER_TRADE_UPDATE':
            await self._order(msg)
            return

    # async def _fetch_position(self, symbol):
    #     while True:
    #         try:
    #             await asyncio.sleep(20)  # 请求限制
    #             positions = await self._rest_api.fetch_positions([symbol])
    #             await self._process_positions(positions)
    #             # break
    #         except Exception as e:
    #             logger.error(e, caller=self)
    # 
    # async def _process_positions(self, info):
    #     # [
    #     #     {
    #     #         'info': {
    #     #             'symbol': 'ETHUSDT',
    #     #             'positionAmt': '0.000',
    #     #             'entryPrice': '0.0',
    #     #             'markPrice': '1255.77236265',
    #     #             'unRealizedProfit': '0.00000000',
    #     #             'liquidationPrice': '0',
    #     #             'leverage': '50',
    #     #             'maxNotionalValue': '1000000',
    #     #             'marginType': 'cross',
    #     #             'isolatedMargin': '0.00000000',
    #     #             'isAutoAddMargin': 'false',
    #     #             'positionSide': 'BOTH',
    #     #             'notional': '0',
    #     #             'isolatedWallet': '0',
    #     #             'updateTime': '1661278904293'
    #     #         },
    #     #         'symbol': 'ETH/USDT',
    #     #         'contracts': 0.0,
    #     #         'contractSize': 1.0,
    #     #         'unrealizedPnl': 0.0,
    #     #         'leverage': 50.0,
    #     #         'liquidationPrice': None,
    #     #         'collateral': 0.0,
    #     #         'notional': 0.0,
    #     #         'markPrice': 1255.77236265,
    #     #         'entryPrice': 0.0,
    #     #         'timestamp': 1661278904293,
    #     #         'initialMargin': 0.0,
    #     #         'initialMarginPercentage': 0.02,
    #     #         'maintenanceMargin': 0.0,
    #     #         'maintenanceMarginPercentage': 0.005,
    #     #         'marginRatio': None,
    #     #         'datetime': '2022-08-23T18:21:44.293Z',
    #     #         'marginMode': 'cross',
    #     #         'marginType': 'cross',
    #     #         'side': None,
    #     #         'hedged': False,
    #     #         'percentage': None
    #     #     }
    #     # ]
    #     for data in info:
    #         update = False
    #         position = Position(self._platform, self._account, self.raw_symbol_to_std_symbol(data['info']['symbol']))
    #         if not position.timestamp:
    #             update = True
    #             position.update()
    #         if Decimal(data['info']['positionAmt']) > 0:
    #             if position.long_quantity != data['contracts']:
    #                 update = True
    #                 position.update(margin_mode=MARGIN_MODE_CROSSED if data['marginType']=="cross" else MARGIN_MODE_FIXED, long_quantity=data['contracts'], long_avg_qty=str(
    #                     Decimal(position.long_quantity) - Decimal(data['contractSize']) if Decimal(
    #                         data['contractSize']) < Decimal(position.long_quantity) else 0),
    #                                 long_open_price=data['entryPrice'],
    #                                 long_hold_price=data['info']['entryPrice'],
    #                                 long_liquid_price=data['info']['liquidationPrice'],
    #                                 long_unrealised_pnl=data['unrealizedPnl'],
    #                                 long_leverage=data['info']['leverage'],
    #                                 long_margin=data['initialMargin'])
    #         elif Decimal(data['info']['positionAmt']) < 0:
    #             if position.short_quantity != data['contracts']:
    #                 update = True
    #                 position.update(margin_mode=MARGIN_MODE_CROSSED if data['marginType']=="cross" else MARGIN_MODE_FIXED, short_quantity=data['contracts'], short_avg_qty=str(
    #                     Decimal(position.long_quantity) - Decimal(data['contractSize']) if Decimal(
    #                         data['contractSize']) < Decimal(position.long_quantity) else 0),
    #                                 short_open_price=data['entryPrice'],
    #                                 short_hold_price=data['info']['entryPrice'],
    #                                 short_liquid_price=data['info']['liquidationPrice'],
    #                                 short_unrealised_pnl=data['unrealizedPnl'],
    #                                 short_leverage=data['info']['leverage'],
    #                                 short_margin=data['initialMargin'])
    #         elif Decimal(data['info']['positionAmt']) == 0:
    #             if position.long_quantity != 0 or position.short_quantity != 0:
    #                 update = True
    #                 position.update()
    # 
    #         # 此处与父类不同
    #         if not update or not self._position_update_callback:
    #             return
    #         self._position[self.raw_symbol_to_std_symbol(data['info']['symbol'])] = position
    #         SingleTask.run(self._on_position_update_callback, position)

    # async def _fetch_fills(self, symbol):
    #     while True:
    #         try:
    #             await asyncio.sleep(5)  # 请求限制
    #             fills = await self._rest_api.fetch_my_trades(symbol)
    #             await self._process_fills(fills)
    #         except Exception as e:
    #             logger.error(e, caller=self)
    #
    # async def _process_fills(self, info):
    #     # [
    #     #     {
    #     #         'info': {
    #     #             'symbol': 'ETHUSDT',
    #     #             'id': '2268940884',
    #     #             'orderId': '8389765544207157214',
    #     #             'side': 'SELL',
    #     #             'price': '1251.92',
    #     #             'qty': '0.004',
    #     #             'realizedPnl': '0',
    #     #             'marginAsset': 'USDT',
    #     #             'quoteQty': '5.00768',
    #     #             'commission': '0.00200307',
    #     #             'commissionAsset': 'USDT',
    #     #             'time': '1663813646857',
    #     #             'positionSide': 'BOTH',
    #     #             'buyer': False,
    #     #             'maker': False
    #     #         },
    #     #         'timestamp': 1663813646857,
    #     #         'datetime': '2022-09-22T02:27:26.857Z',
    #     #         'symbol': 'ETH/USDT',
    #     #         'id': '2268940884',
    #     #         'order': '8389765544207157214',
    #     #         'type': None,
    #     #         'side': 'sell',
    #     #         'takerOrMaker': 'taker',
    #     #         'price': 1251.92,
    #     #         'amount': 0.004,
    #     #         'cost': 5.00768,
    #     #         'fee': {
    #     #             'cost': 0.00200307,
    #     #             'currency': 'USDT'
    #     #         },
    #     #         'fees': [
    #     #             {
    #     #                 'currency': 'USDT',
    #     #                 'cost': 0.00200307
    #     #             }
    #     #         ]
    #     #     },
    #     #     {
    #     #         'info': {
    #     #             'symbol': 'ETHUSDT',
    #     #             'id': '2268942027',
    #     #             'orderId': '8389765544207238595',
    #     #             'side': 'SELL',
    #     #             'price': '1252.12',
    #     #             'qty': '0.004',
    #     #             'realizedPnl': '0',
    #     #             'marginAsset': 'USDT',
    #     #             'quoteQty': '5.00848',
    #     #             'commission': '0.00200339',
    #     #             'commissionAsset': 'USDT',
    #     #             'time': '1663813679046',
    #     #             'positionSide': 'BOTH',
    #     #             'buyer': False,
    #     #             'maker': False
    #     #         },
    #     #         'timestamp': 1663813679046,
    #     #         'datetime': '2022-09-22T02:27:59.046Z',
    #     #         'symbol': 'ETH/USDT',
    #     #         'id': '2268942027',
    #     #         'order': '8389765544207238595',
    #     #         'type': None,
    #     #         'side': 'sell',
    #     #         'takerOrMaker': 'taker',
    #     #         'price': 1252.12,
    #     #         'amount': 0.004,
    #     #         'cost': 5.00848,
    #     #         'fee': {
    #     #             'cost': 0.00200339,
    #     #             'currency': 'USDT'
    #     #         },
    #     #         'fees': [
    #     #             {
    #     #                 'currency': 'USDT',
    #     #                 'cost': 0.00200339
    #     #             }
    #     #         ]
    #     #     }
    #     # ]
    #     for data in info:  # 引用CCXT的格式化结果
    #         info = {
    #             "platform": self._platform,
    #             "account": self._account,
    #             "symbol": self.raw_symbol_to_std_symbol(data['symbol']),
    #             "fill_id": str(data['id']),
    #             "order_id": str(data['order']),
    #             "trade_type": data['type'],
    #             # "liquidity_price": None,
    #             "action": const.ORDER_ACTION_BUY if data['side'] == 'buy' else const.ORDER_ACTION_SELL,
    #             "price": str(data['price']),
    #             "quantity": str(data['amount']),
    #             "role": const.LIQUIDITY_TYPE_TAKER if data['takerOrMaker'] == "taker" else const.LIQUIDITY_TYPE_MAKER,
    #             "fee": str(data['info']['commission']) + "_" + data['info']['commissionAsset'],
    #             "ctime": data['timestamp']
    #         }
    #         fill = Fill(**info)
    #
    #         SingleTask.run(self._on_fill_update_callback, fill)


    # 根据Order返回的status修改
    def status(self, trade_quantity, remain, quantity, status_info):
        """
            NEW
            PARTIALLY_FILLED
            FILLED
            CANCELED
            EXPIRED
            NEW_INSURANCE
            风险保障基金(强平)
            NEW_ADL
            自动减仓序列(强平)
        """
        if status_info == "NEW":
            return const.ORDER_STATUS_SUBMITTED
        elif status_info == "FILLED":
            return const.ORDER_STATUS_FILLED
        elif status_info == "EXPIRED":
            return const.ORDER_STATUS_FILLED
        elif status_info == "NEW_INSURANCE":
            return const.ORDER_STATUS_FILLED
        elif status_info == "NEW_ADL":
            return const.ORDER_STATUS_FILLED
        elif status_info == "PARTIALLY_FILLED":
            if float(remain) < float(quantity):
                return const.ORDER_STATUS_PARTIAL_FILLED
            else:
                return const.ORDER_STATUS_SUBMITTED
        elif status_info == "CANCELED":
            if float(trade_quantity) < float(quantity):
                return const.ORDER_STATUS_CANCELED
            else:
                return const.ORDER_STATUS_FILLED
        else:
            logger.warn("unknown status:", status_info, caller=self)
            SingleTask.run(self._error_callback, "order status error.")
            return

    async def _order(self, msg: dict):
        '''
       {
            "e":"ORDER_TRADE_UPDATE",     // Event Type
            "E":1568879465651,            // Event Time
            "T":1568879465650,            // Transaction Time
            "o":
            {
                "s":"BTCUSDT",              // Symbol
                "c":"TEST",                 // Client Order Id
                // special client order id:
                // starts with "autoclose-": liquidation order
                // "adl_autoclose": ADL auto close order
                "S":"SELL",                 // Side
                "o":"TRAILING_STOP_MARKET", // Order Type
                "f":"GTC",                  // Time in Force
                "q":"0.001",                // Original Quantity
                "p":"0",                    // Original Price
                "ap":"0",                   // Average Price
                "sp":"7103.04",             // Stop Price. Please ignore with TRAILING_STOP_MARKET order
                "x":"NEW",                  // Execution Type
                "X":"NEW",                  // Order Status
                "i":8886774,                // Order Id
                "l":"0",                    // Order Last Filled Quantity
                "z":"0",                    // Order Filled Accumulated Quantity
                "L":"0",                    // Last Filled Price
                "N":"USDT",             // Commission Asset, will not push if no commission
                "n":"0",                // Commission, will not push if no commission
                "T":1568879465651,          // Order Trade Time
                "t":0,                      // Trade Id
                "b":"0",                    // Bids Notional
                "a":"9.91",                 // Ask Notional
                "m":false,                  // Is this trade the maker side?
                "R":false,                  // Is this reduce only
                "wt":"CONTRACT_PRICE",      // Stop Price Working Type
                "ot":"TRAILING_STOP_MARKET",    // Original Order Type
                "ps":"LONG",                        // Position Side
                "cp":false,                     // If Close-All, pushed with conditional order
                "AP":"7476.89",             // Activation Price, only puhed with TRAILING_STOP_MARKET order
                "cr":"5.0",                 // Callback Rate, only puhed with TRAILING_STOP_MARKET order
                "rp":"0"                            // Realized Profit of the trade
            }
        }
        '''
        pair = self.raw_symbol_to_std_symbol(msg['o']['s'])
        order = self._orders.get(msg['o']['i'])
        if not order:
            info = {
                "platform": self._platform,
                "account": self._account,
                "symbol": pair,
                "order_id": str(msg['o']['i']),
                "client_order_id": str(msg['o']['c']),
                "action": const.ORDER_ACTION_BUY if msg['o']['S'] == 'BUY' else const.ORDER_ACTION_SELL,
                "order_type": const.ORDER_TYPE_LIMIT if msg['o']['o'] == "LIMIT" else const.ORDER_TYPE_MARKET,
                "order_price_type": msg['o']['wt'],
                "ctime": msg['o']['T'],
            }
            order = Order(**info)
            self._orders[msg['o']['i']] = order
        order.remain = float(msg['o']['q']) - float(msg['o']['z'])
        order.avg_price = str(msg['o']['ap'])
        order.trade_type = const.TRADE_TYPE_NONE if len(order.client_order_id.split("/")[-1]) > 1 else \
            order.client_order_id.split("/")[-1]
        order.price = str(msg['o']['p'])
        order.quantity = str(msg['o']['q'])
        order.utime = msg['E']
        order.status = self.status(Decimal(msg['o']['z']), Decimal(order.remain), Decimal(msg['o']['q']),
                                   msg['o']['X'])
        if order.status in [const.ORDER_STATUS_FAILED, const.ORDER_STATUS_CANCELED, const.ORDER_STATUS_FILLED]:
            self._orders.pop(msg['o']['i'])

        SingleTask.run(self._on_order_update_callback, order)

        if msg['o']['t']:
            await self._fill(msg)

    async def _fill(self, data: dict):
        # {
        #
        # "e": "ORDER_TRADE_UPDATE", // 事件类型
        # "E": 1568879465651, // 事件时间
        # "T": 1568879465650, // 撮合时间
        # "o": {
        #          "s": "BTCUSDT", // 交易对
        # "c": "TEST", // 客户端自定订单ID
        #                 // 特殊的自定义订单ID:
        # // "autoclose-"
        # 开头的字符串: 系统强平订单
        #         // "adl_autoclose": ADL自动减仓订单
        #                             // "settlement_autoclose-": 下架或交割的结算订单
        # "S": "SELL", // 订单方向
        # "o": "TRAILING_STOP_MARKET", // 订单类型
        # "f": "GTC", // 有效方式
        # "q": "0.001", // 订单原始数量
        # "p": "0", // 订单原始价格
        # "ap": "0", // 订单平均价格
        # "sp": "7103.04", // 条件订单触发价格，对追踪止损单无效
        # "x": "NEW", // 本次事件的具体执行类型
        # "X": "NEW", // 订单的当前状态
        # "i": 8886774, // 订单ID
        # "l": "0", // 订单末次成交量
        # "z": "0", // 订单累计已成交量
        # "L": "0", // 订单末次成交价格
        # "N": "USDT", // 手续费资产类型
        # "n": "0", // 手续费数量
        # "T": 1568879465650, // 成交时间
        # "t": 0, // 成交ID
        # "b": "0", // 买单净值
        # "a": "9.91", // 卖单净值
        # "m": false, // 该成交是作为挂单成交吗？
        # "R": false, // 是否是只减仓单
        # "wt": "CONTRACT_PRICE", // 触发价类型
        # "ot": "TRAILING_STOP_MARKET", // 原始订单类型
        # "ps": "LONG" // 持仓方向
        # "cp": false, // 是否为触发平仓单;
        # 仅在条件订单情况下会推送此字段
        # "AP": "7476.89", // 追踪止损激活价格, 仅在追踪止损单时会推送此字段
        # "cr": "5.0", // 追踪止损回调比例, 仅在追踪止损单时会推送此字段
        # "pP": false, // 忽略
        # "si": 0, // 忽略
        # "ss": 0, // 忽略
        # "rp": "0" // 该交易实现盈亏
        # }
        #
        # }

        pair = self.raw_symbol_to_std_symbol(data['o']['s'])
        info = {
            "platform": self._platform,
            "account": self._account,
            "symbol": pair,
            "fill_id": str(data['o']['t']),
            "order_id": str(data['o']['i']),
            "trade_type": data['o']['o'],
            # "liquidity_price": data['o']['AP'],
            "action": const.ORDER_ACTION_BUY if data['o']['S'] == 'BUY' else const.ORDER_ACTION_SELL,
            "price": str(data['o']['L']),
            "quantity": str(data['o']['l']),
            "role": const.LIQUIDITY_TYPE_TAKER if data['o']['m'] == False else const.LIQUIDITY_TYPE_MAKER,
            "fee": str(data['o']['n'] + "_" + data['o']['N']) if data['o'].get('n') else None,
            "ctime": data['o']['T']
        }
        fill = Fill(**info)

        SingleTask.run(self._on_fill_update_callback, fill)

    async def _asset(self, msg: dict):
        """
       {
        "e": "ACCOUNT_UPDATE",                // Event Type
        "E": 1564745798939,                   // Event Time
        "T": 1564745798938 ,                  // Transaction
        "a":                                  // Update Data
            {
            "m":"ORDER",                      // Event reason type
            "B":[                             // Balances
                {
                "a":"USDT",                   // Asset
                "wb":"122624.12345678",       // Wallet Balance
                "cw":"100.12345678",          // Cross Wallet Balance
                "bc":"50.12345678"            // Balance Change except PnL and Commission
                },
                {
                "a":"BUSD",
                "wb":"1.00000000",
                "cw":"0.00000000",
                "bc":"-49.12345678"
                }
            ],
            "P":[
                {
                "s":"BTCUSDT",            // Symbol
                "pa":"0",                 // Position Amount
                "ep":"0.00000",            // Entry Price
                "cr":"200",               // (Pre-fee) Accumulated Realized
                "up":"0",                     // Unrealized PnL
                "mt":"isolated",              // Margin Type
                "iw":"0.00000000",            // Isolated Wallet (if isolated position)
                "ps":"BOTH"                   // Position Side
                }，
                {
                    "s":"BTCUSDT",
                    "pa":"20",
                    "ep":"6563.66500",
                    "cr":"0",
                    "up":"2850.21200",
                    "mt":"isolated",
                    "iw":"13200.70726908",
                    "ps":"LONG"
                },
                {
                    "s":"BTCUSDT",
                    "pa":"-10",
                    "ep":"6563.86000",
                    "cr":"-45.04000000",
                    "up":"-1423.15600",
                    "mt":"isolated",
                    "iw":"6570.42511771",
                    "ps":"SHORT"
                }
            ]
            }
        }
        """
        assets = {}
        for data in msg['a']['B']:
            total = Decimal(data['wb']) + Decimal(data['bc'])
            free = Decimal(data['cw']) + Decimal(data['bc'])
            locked = total - free
            assets[data['a']] = {
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
            for sym in assets:  # 相当于for symbol in assets.keys():
                self._assets.assets.update({
                    sym: assets[sym]
                })
            self._assets.timestamp = tools.get_cur_timestamp_ms()

        SingleTask.run(self._on_asset_update_callback, self._assets)

        for position in msg['a']['P']:
            await self._positions(position)

    async def _positions(self, data):
        # {
        # "s": "BTCUSDT", // 交易对
        # "pa": "0", // 仓位
        # "ep": "0.00000", // 入仓价格
        # "cr": "200", // (费前)
        # 累计实现损益
        # "up": "0", // 持仓未实现盈亏
        # "mt": "isolated", // 保证金模式
        # "iw": "0.00000000", // 若为逐仓，仓位保证金
        # "ps": "BOTH" // 持仓方向
        # }
        update = False
        # position = Position(self._platform, self._account, self._strategy, self.raw_symbol_to_std_symbol(data['s']))
        # if not position.timestamp:
        #     update = True
        #     position.update()
        pair = self.raw_symbol_to_std_symbol(data['s'])
        if pair not in self._position:
            self._position[pair] = Position(self._platform, self._account, pair)
            update = True

        if Decimal(data['pa']) > 0:
            if self._position[pair].long_quantity != data['pa']:
                update = True
                self._position[pair].update(margin_mode=MARGIN_MODE_FIXED if data['mt']=="isolated" else MARGIN_MODE_CROSSED, long_quantity=data['pa'], long_avg_qty=data['pa'],
                                long_open_price=data['ep'],
                                long_hold_price=data['ep'],
                                long_unrealised_pnl=data['up'],
                                long_liquid_price=self._position[pair].long_liquid_price,
                                long_leverage=self._position[pair].long_leverage,
                                long_margin=self._position[pair].long_margin)
        elif Decimal(data['pa']) < 0:
            if self._position[pair].short_quantity != data['pa']:
                update = True
                self._position[pair].update(margin_mode=MARGIN_MODE_FIXED if data['mt']=="isolated" else MARGIN_MODE_CROSSED, short_quantity=abs(float(data['pa'])), short_avg_qty=abs(float(data['pa'])),
                                short_open_price=data['ep'],
                                short_hold_price=data['ep'],
                                short_unrealised_pnl=data['up'],
                                short_liquid_price=self._position[pair].short_liquid_price,
                                short_leverage=self._position[pair].short_leverage,
                                short_margin=self._position[pair].short_margin)
        elif Decimal(data['pa']) == 0 and data['ps'] == 'BOTH':
            if self._position[pair].long_quantity != 0 or self._position[pair].short_quantity != 0:
                update = True
                self._position[pair].update()

        # 此处与父类不同
        if not update or not self._position_update_callback:
            return

        SingleTask.run(self._on_position_update_callback, self._position[pair])

    async def _trade(self, msg: dict):
        """
            {
              "e": "aggTrade",  // 事件类型
              "E": 123456789,   // 事件时间
              "s": "BNBUSDT",    // 交易对
              "a": 5933014,     // 归集成交 ID
              "p": "0.001",     // 成交价格
              "q": "100",       // 成交量
              "f": 100,         // 被归集的首个交易ID
              "l": 105,         // 被归集的末次交易ID
              "T": 123456785,   // 成交时间
              "m": true         // 买方是否是做市方。如true，则此次成交是一个主动卖出单，否则是一个主动买入单。
            }
        """
        pair = self.raw_symbol_to_std_symbol(msg['s'])
        info = {
            "platform": self._platform,
            "symbol": pair,
            "action": const.ORDER_ACTION_BUY if msg["m"] == False else const.ORDER_ACTION_SELL,
            "price": msg['p'],
            "quantity": msg['q'],
            "id": msg['a'],
            "timestamp": msg['T']  # Unix时间戳的毫秒数格式
        }
        trade = Trade(**info)
        # self._trades[pair] = trade

        SingleTask.run(self._on_trade_update_callback, trade)

    async def _ticker(self, msg: dict):
        """
            {
              "e":"bookTicker",     // 事件类型
              "u":400900217,        // 更新ID
              "E": 1568014460893,   // 事件推送时间
              "T": 1568014460891,   // 撮合时间
              "s":"BNBUSDT",        // 交易对
              "b":"25.35190000",    // 买单最优挂单价格
              "B":"31.21000000",    // 买单最优挂单数量
              "a":"25.36520000",    // 卖单最优挂单价格
              "A":"40.66000000"     // 卖单最优挂单数量
            }
        """

        pair = self.raw_symbol_to_std_symbol(msg['s'])
        info = {
            "platform": self._platform,
            "symbol": pair,
            "ask": {msg['a']: msg['A']},
            "bid": {msg['b']: msg['B']},
            "timestamp": msg["T"]  # Unix时间戳的毫秒数格式
        }
        ticker = Ticker(**info)
        # self._tickers[pair] = ticker
        SingleTask.run(self._on_ticker_update_callback, ticker)

    def _check_update_id(self, std_pair: str, msg: dict) -> bool:
        """
        Messages will be queued while fetching snapshot and we can return a book_callback
        using this msg's data instead of waiting for the next update.
        """
        if self._orderbooks[std_pair] is not None and msg['u'] <= self.last_update_id[std_pair]:
            return True
        elif msg['U'] <= self.last_update_id[std_pair] and msg['u'] <= self.last_update_id[std_pair]:
            # Old message, can ignore it
            return True
        elif msg['U'] <= self.last_update_id[std_pair] + 1 <= msg['u']:
            self.last_update_id[std_pair] = msg['u']
            return False
        elif self.last_update_id[std_pair] + 1 == msg['U']:
            self.last_update_id[std_pair] = msg['u']
            return False
        else:
            self._reset()
            # logger.warn("{}: Missing book update detected, resetting book".format(self._platform), caller=self)
            return True

    async def _book(self, msg: dict, pair: str):
        """
          {
              "e": "depthUpdate", // Event type
              "E": 123456789,     // Event time
              "s": "BNBBTC",      // Symbol
              "U": 157,           // First update ID in event
              "u": 160,           // Final update ID in event
              "b": [              // Bids to be updated
                      [
                          "0.0024",       // Price level to be updated
                          "10"            // Quantity
                      ]
              ],
              "a": [              // Asks to be updated
                      [
                          "0.0026",       // Price level to be updated
                          "100"           // Quantity
                      ]
              ]
          }
        # snapshot
            {
                "lastUpdateId": 1027024,
                "E": 1589436922972, // 消息时间
            "T": 1589436922959, // 撮合引擎时间
            "bids": [ // 买单
            [
                "4.00000000", // 价格
            "431.00000000" // 数量
            ]
            ],
            "asks": [ // 卖单
            [
                "4.00000200", // 价格
            "12.00000000" // 数量
            ]
            ]
            }

          """
        pair = self.raw_symbol_to_std_symbol(pair)
        # 无法通过回调数据确定是否partial,只能通过新增self._orderbook来判断，reset后又要重新赋值snapshot
        if pair not in self._orderbooks:
            self.last_update_id[pair] = msg.get('u')
            bids = {price: amount for price, amount, *_ in msg['b']}
            asks = {price: amount for price, amount, *_ in msg['a']}
            info = {
                "platform": self._platform,
                "symbol": pair,
                "asks": asks,
                "bids": bids,
                "timestamp": msg["T"]  # Unix时间戳的毫秒数格式
            }
            orderbook = Orderbook(**info)
            self._orderbooks[pair] = orderbook
            SingleTask.run(self._on_orderbook_update_callback, orderbook)

        skip_update = self._check_update_id(pair, msg)
        if skip_update:
            return

        delta = {"bids": [], "asks": []}
        self._orderbooks[pair].timestamp = msg["T"]  # 无论是否reset,都需要更新
        for side in ('b', 'a'):
            s = "bids" if side == 'bids' else "asks"
            for price, amount, *_ in msg[side]:
                if float(amount) == 0:
                    if price in getattr(self._orderbooks[pair], s):
                        delta[s].append((price, 0))
                        del getattr(self._orderbooks[pair], s)[price]
                else:
                    delta[s].append((price, amount))
                    getattr(self._orderbooks[pair], s)[price] = amount  # 对类属性值操作

            SingleTask.run(self._on_orderbook_update_callback, self._orderbooks[pair])

    async def _candle(self, msg: dict):
        """
        {
            'e': 'kline',
            'E': 1615927655524,
            's': 'BTCUSDT',
            'k': {
                't': 1615927620000,
                'T': 1615927679999,
                's': 'BTCUSDT',
                'i': '1m',
                'f': 710917276,
                'L': 710917780,
                'o': '56215.99000000',
                'c': '56232.07000000',
                'h': '56238.59000000',
                'l': '56181.99000000',
                'v': '13.80522200',
                'n': 505,
                'x': False,
                'q': '775978.37383076',
                'V': '7.19660600',
                'Q': '404521.60814919',
                'B': '0'
            }
        }
        """
        pair = self.raw_symbol_to_std_symbol(msg['s'])
        kline_type = const.MARKET_TYPE_KLINE if msg['k']['i'] == '1m' else "kline_" + msg['k']['i'].lower()
        info = {
            "platform": self._platform,
            "symbol": pair,
            "start": msg['k']['t'],
            "stop": msg['k']['T'],
            "open": msg['k']['o'],
            "high": msg['k']['h'],
            "low": msg['k']['l'],
            "close": msg['k']['c'],
            "volume": msg['k']['v'],
            "timestamp": int(msg['k']['T']),
            "kline_type": kline_type
        }
        kline = Kline(**info)
        # self._tickers[pair] = ticker
        SingleTask.run(self._on_kline_update_callback, kline)




