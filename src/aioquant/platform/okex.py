# -*- coding:utf-8 -*-

"""
OKEx Trade module.
https://www.okex.me/docs/zh/

Author: HuangTao
Date:   2019/01/19
Email:  huangtao@ifclover.com
"""

from aioquant import const
from aioquant.Gateway import ExchangeGateway,ExchangeWebsocket
from aioquant.configure import config
from aioquant.asset import Asset
from aioquant.position import Position, MARGIN_MODE_CROSSED,MARGIN_MODE_FIXED
from aioquant.fill import Fill
from aioquant.symbols import SymbolInfo
from aioquant.market import Orderbook,Ticker,Trade,Kline
from aioquant.error import Error
from aioquant.utils import tools
from aioquant.utils import logger
from aioquant.order import Order
from aioquant.tasks import SingleTask, LoopRunTask
from aioquant.utils.decorator import async_method_locker
from aioquant.utils.web import Websocket
from ccxt.async_support.okx import okx
from decimal import Decimal
import asyncio
import time
import copy
import hmac
import base64


__all__ = ("OKExRestAPI", "OKExTrade", "OKExMarket",)


class OKExRestAPI(okx):
    """ OKEx REST API client.

    Attributes:
        access_key: Account's ACCESS KEY.
        secret_key: Account's SECRET KEY.
        passphrase: API KEY Passphrase.
        host: HTTP request host, default `https://www.okex.com`
    """

    def __init__(self, config={}):
        """Initialize."""
        super(okx, self).__init__(config)  # 引用父类的父类初始化
        # 科学上网代理
        from aioquant.configure import config
        self.aiohttp_proxy = config.proxy
        # 其他配置参数
        self.rateLimit = 20  # 异步执行周期，避免网络不通
        self.enableRateLimit = True

class OKExTrade(ExchangeGateway):
    """OKEx Trade module. You can initialize trade object with some attributes in kwargs.

    Attributes:
        account: Account name for this trade exchange.
        strategy: What's name would you want to created for your strategy.
        symbol: Symbol name for your trade.
        host: HTTP request host. (default "https://www.okex.com")
        wss: Websocket address. (default "wss://real.okex.com:8443")
        access_key: Account's ACCESS KEY.
        secret_key Account's SECRET KEY.
        passphrase API KEY Passphrase.
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
    valid_candle_intervals = {'1D', '12H', '6H', '4H', '2H', '1H', '30m', '15m', '5m', '1m'}
    candle_interval_map = {'1D': 86400, '12H': 43200, '6H': 21600, '4H': 14400, '2H': 7200, '1H': 3600, '30m': 1800, '15m': 900, '5m': 300, '1m': 60}
    # OKX的频道多只取需要的(不要的不回调process中设置）
    websocket_channels = {
        # 公共频道
        const.L2_BOOK: 'books',   # action: partial, action: update
        const.TICKER: 'tickers',
        const.CANDLES: 'candle',  # 完整字段candle1M
        const.TRADES: 'trades',
        # 私有频道
        const.ORDERS: 'orders',
        const.ACCOUNTS: 'account',     # 用CCXT结果好格式化
        const.POSITIONS: 'positions',
        # 需要CCXT获取
        const.FILLS: 'fills'
    }
    def __init__(self, **kwargs):
        """Initialize."""
        e = None
        if not kwargs.get("account"):
            e = Error("param account miss")
        if not kwargs.get("strategy"):
            e = Error("param strategy miss")
        if not kwargs.get("symbol"):
            e = Error("param symbol miss")
        if not kwargs.get("host"):
            kwargs["host"] = "www.okx.com"
        if not kwargs.get("wss"):
            kwargs["wss"] = "wss://ws.okx.com:8443/ws/v5/private"
        if not kwargs.get("access_key"):
            e = Error("param access_key miss")
        if not kwargs.get("secret_key"):
            e = Error("param secret_key miss")
        if not kwargs.get("passphrase"):
            e = Error("param passphrase miss")
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
        self._passphrase = kwargs["passphrase"]
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
        self._symbols = {} # Order data. e.g. {symbol: symboinfo, ... }
        # Initialize our REST API client.
        self._rest_api = OKExRestAPI({"apiKey":self._access_key,"secret":self._secret_key, "password": self._passphrase,"hostname":self._host})  # 'funding', 'spot', 'margin', 'futures', 'swap', 'option'

        # Create a loop run task to send ping message to server per 5 seconds.
        SingleTask.run(self._init_rest)  # 相当于ccxt.loadmarket

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
        # {
        #     'id': 'HEGIC-ETH',
        #     'symbol': 'HEGIC/ETH',
        #     'base': 'HEGIC',
        #     'quote': 'ETH',
        #     'baseId': 'HEGIC',
        #     'quoteId': 'ETH',
        #     'active': True,
        #     'type': 'spot',
        #     'linear': None,
        #     'inverse': None,
        #     'spot': True,
        #     'swap': False,
        #     'future': False,
        #     'option': False,
        #     'margin': False,
        #     'contract': False,
        #     'contractSize': None,
        #     'expiry': None,
        #     'expiryDatetime': None,
        #     'optionType': None,
        #     'strike': None,
        #     'settle': None,
        #     'settleId': None,
        #     'precision': {
        #         'amount': 1.0,
        #         'price': 1e-08
        #     },
        #     'limits': {
        #         'amount': {
        #             'min': 10.0,
        #             'max': None
        #         },
        #         'price': {
        #             'min': 1e-08,
        #             'max': None
        #         },
        #         'cost': {
        #             'min': None,
        #             'max': None
        #         },
        #         'leverage': {
        #             'min': 1.0,
        #             'max': 1.0
        #         }
        #     },
        #     'info': {
        #         'alias': '',
        #         'baseCcy': 'HEGIC',
        #         'category': '1',
        #         'ctMult': '',
        #         'ctType': '',
        #         'ctVal': '',
        #         'ctValCcy': '',
        #         'expTime': '',
        #         'instId': 'HEGIC-ETH',
        #         'instType': 'SPOT',
        #         'lever': '',
        #         'listTime': '1607468408000',
        #         'lotSz': '1',
        #         'maxIcebergSz': '9999999999999999',
        #         'maxLmtSz': '9999999999999999',
        #         'maxMktSz': '1000000',
        #         'maxStopSz': '1000000',
        #         'maxTriggerSz': '9999999999999999',
        #         'maxTwapSz': '9999999999999999',
        #         'minSz': '10',
        #         'optType': '',
        #         'quoteCcy': 'ETH',
        #         'settleCcy': '',
        #         'state': 'live',
        #         'stk': '',
        #         'tickSz': '0.00000001',
        #         'uly': ''
        #     },
        #     'percentage': True,
        #     'taker': 0.0015,
        #     'maker': 0.001
        # }
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
                "value_tick": data['info']['ctVal'],
                "value_limit": data['limits']['cost']['min'],
                "base_currency": data['base'],
                "quote_currency": data['quote'],
                "settlement_currency": data['quote'],
                "symbol_type": data['type'],
                "is_inverse": data['inverse'],
                "multiplier": data['info']['ctMult']
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
        LoopRunTask.register(self._send_heartbeat_msg, 20)

    async def _send_heartbeat_msg(self, *args, **kwargs):
        """Send ping to server."""
        hb = "ping"
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
            order_type: limit or market.
            tdmode: cash, cross, isolated

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
            if action == const.ORDER_ACTION_BUY:  #开多
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
        # 默认保证金模式为现货cash，判断全仓模式cross，逐仓模式isolated
        margin_mode = kwargs.get("margin_mode", MARGIN_MODE_CROSSED)
        if margin_mode:
            tdmode = "cross" if margin_mode == MARGIN_MODE_CROSSED else "isolated"
        else:
            tdmode = "cash"
            trade_type = const.TRADE_TYPE_NONE
        params = kwargs.get("params", {})
        params["tdMode"] = tdmode
        if order_type == const.ORDER_TYPE_POST_ONLY:
            params['ordType'] = 'post_only'
            order_type = const.ORDER_TYPE_LIMIT
        # params.update({
        #     "tag":trade_type,
        #     "tdMode": tdmode,  # cash, cross, isolated
        # })
        if client_order_id:
            params["clOrdId"] = client_order_id
            params["tag"] = trade_type
        result = await self._rest_api.create_order(self._symbol, order_type.lower(), action.lower(), abs(float(quantity)), price, params)
        if not result:
            SingleTask.run(self._error_callback, result)
            return None, result
        order_id = str(result["info"]["ordId"])
        return order_id, None

    async def edit_order(self, *args, **kwargs):
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
        params = kwargs.get("params", {})
        params["instId"] = self.std_symbol_to_raw_symbol(self._symbol)
        if order_id:
            params["ordId"] = order_id
        if client_order_id:
            params["clOrdId"] = client_order_id
        if price:
            params["newPx"] = price
        if quantity:
            params["newSz"] = quantity
        result = await self._rest_api.private_post_trade_amend_order(params)
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
                _ = await self._rest_api.cancel_order(order_info["info"]["ordId"], self._symbol)
                if not _:
                    SingleTask.run(self._error_callback, _)
                    return False, _
            return True, None

        # If len(order_ids) == 1, you will cancel an order.
        if len(order_ids) == 1:
            _content = await self._rest_api.cancel_order(order_ids[0],self._symbol)
            if not _content:
                SingleTask.run(self._error_callback, _content)
                return order_ids[0], _content
            else:
                return order_ids[0], None

        # If len(order_ids) > 1, you will cancel multiple orders.
        if len(order_ids) > 1:
            success, error = [], []
            for order_id in order_ids:
                _ = await self._rest_api.cancel_order(order_id,self._symbol)
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
                order_id = str(order_info["info"]["ordId"])
                order_ids.append(order_id)
            return order_ids, None

    async def generate_token(self):
        timestamp = int(time.time())
        message = str(timestamp) + 'GET' + '/users/self/verify'
        mac = hmac.new(bytes(self._secret_key, encoding="utf8"), bytes(message, encoding="utf8"), digestmod="sha256")
        d = mac.digest()
        sign = base64.b64encode(d).decode()
        params = {
            "apiKey": self._access_key,
            "passphrase": self._passphrase,
            "timestamp": timestamp,
            'sign': sign,
        }
        data = {"op": "login", "args": [params]}
        await self._ws.send(data)

    def inst_type_to_okx_type(self, ticker):
        sym = self.raw_symbol_to_std_symbol(ticker)
        # 根据symbol确定交易类型
        instrument_type = self._symbols[sym].symbol_type
        instrument_type_map = {
            'spot': 'SPOT',
            'margin': 'MARGIN',
            'swap': 'SWAP',
            'future': 'FUTURES',
            'option': 'OPTION'
        }
        return instrument_type_map.get(instrument_type, 'MARGIN')

    def build_subscription(self, channel: str, ticker: str, candle_interval: str) -> dict:
        # 没使用的频道,固定为资金费率
        if channel in ['positions', 'orders']:
            subscription_dict = {"channel": channel,
                                 "instType": self.inst_type_to_okx_type(ticker),
                                 "instId": ticker}
        elif channel in ['candle']:
            subscription_dict = {"channel": f"{channel}{candle_interval}",
                                 "instId": ticker}
        else:
            subscription_dict = {"channel": channel,
                                 "instId": ticker}
        return subscription_dict

    async def subscribe(self, subscription: dict):
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
            # if chan == self.std_channel_to_raw_channel(const.L2_BOOK) and not self._orderbook_update_callback:
            #     continue
            # if chan == self.std_channel_to_raw_channel(const.TICKER) and not self._ticker_update_callback:
            #     continue
            # if chan == self.std_channel_to_raw_channel(const.TRADES) and not self._trade_update_callback:
            #     continue
            # if chan == self.std_channel_to_raw_channel(const.CANDLES) and not self._kline_update_callback:
            #     continue

            # 需要symbol作参数
            # Fill是自定义大多需要CCXT获取，但OKX可通过 order websockt间接获取
            if chan == self.std_channel_to_raw_channel(const.FILLS):
            #     asyncio.create_task(self._fetch_fills(self._symbol))
                continue

            # elif chan == self.std_channel_to_raw_channel(const.ACCOUNTS):
            #     asyncio.create_task(self._fetch_balances())
            #     continue

            # 没有websokcet,自定需要restAPI的及过滤(过滤掉websocket channel 中有并且不需要的chan
            # elif chan == self.std_channel_to_raw_channel(const.POSITIONS):
            #     asyncio.create_task(self._fetch_position(self._symbol))
            #     continue

            # 私有频道订阅，先过滤出chan,过滤出自定义chan
            if self.is_authenticated_channel(self.raw_channel_to_std_channel(chan)):
                channels = [self.build_subscription(chan, self._raw_symbol, candle_interval) for candle_interval in self.valid_candle_intervals]

                # 删除重复的频道
                chs = [dict(t) for t in set([tuple(d.items()) for d in channels])]
                # 现货不存在position
                spot_position = [channel for channel in chs if
                                 channel.get('channel') == 'positions' and channel.get('instType') in ['MARGIN',
                                                                                                       'SPOT']]
                ch = [channel for channel in chs if channel not in spot_position]
                if not ch:
                    continue

                msg = {"op": "subscribe", "args": ch}
                await self._ws.send(msg)

    async def connected_callback(self):
        # 要在CCXT获取交易所load_market后，但websocket_channels有些会自动订阅不一定要chan
        if self._raw_symbol and self.websocket_channels.keys():
            if any(self.is_authenticated_channel(chan) for chan in self.websocket_channels.keys()):
                if not self._access_key or not self._secret_key:
                    raise ValueError("Authenticated channel subscribed to, but no auth keys provided")
                await self.generate_token()
                
        SingleTask.run(self._init_callback, True)
        
    # 回调信息操作
    @async_method_locker("OkexTrade.process.locker")
    async def process(self, msg):
        """Process message that received from Websocket connection.

        Args:
            msg: message received from Websocket connection.
        """
        if 'event' in msg:
            if msg['event'] == 'error':
                logger.error("{}: Error: {}".format(self._platform, msg), caller=self)
            elif msg['event'] == 'subscribe':
                pass
            elif msg['event'] == 'login':
                # websocket注册成功后才能订阅
                raw_channels = list(set([self.std_channel_to_raw_channel(chan) for chan in self.websocket_channels.keys()]))
                sub = {chan: self._raw_symbol for chan in raw_channels}
                await self.subscribe(sub)
                logger.debug('{}: Websocket logged in? {}'.format(self._platform, msg['code']), caller=self)
            else:
                logger.warn("{}: Unhandled event {}".format(self._platform, msg), caller=self)
        elif 'arg' in msg:
            if self.websocket_channels[const.ORDERS] in msg['arg']['channel']:
                await self._order(msg)
            elif self.websocket_channels[const.POSITIONS] in msg['arg']['channel']:
                await self._position(msg)
            elif self.websocket_channels[const.ACCOUNTS] in msg['arg']['channel']:
                await self._asset(msg)

        else:
            logger.warn("{}: Unhandled message {}".format(self._platform, msg), caller=self)

    # # 如果没有仓位，获取到空字典，没有使用
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
    # # okex是仓位有变化时才推送，没有仓位，获取到空字典，没有使用
    # async def _process_positions(self, info):
    #     """
    #         {
    #           'info': {
    #             'adl': '4',
    #             'availPos': '',
    #             'avgPx': '1338.67',
    #             'baseBal': '',
    #             'cTime': '1664526175010',
    #             'ccy': 'ETH',
    #             'deltaBS': '',
    #             'deltaPA': '',
    #             'gammaBS': '',
    #             'gammaPA': '',
    #             'imr': '0.0024871538503629',
    #             'instId': 'ETH-USD-SWAP',
    #             'instType': 'SWAP',
    #             'interest': '0',
    #             'last': '1340.33',
    #             'lever': '3',
    #             'liab': '',
    #             'liabCcy': '',
    #             'liqPx': '250.2305332057643',
    #             'margin': '',
    #             'markPx': '1340.22',
    #             'mgnMode': 'cross',
    #             'mgnRatio': '973.3428546449297',
    #             'mmr': '0.0000298458462044',
    #             'notionalUsd': '9.998731551536315',
    #             'optVal': '',
    #             'pendingCloseOrdLiabVal': '',
    #             'pos': '1',
    #             'posCcy': '',
    #             'posId': '337443544378007557',
    #             'posSide': 'net',
    #             'quoteBal': '',
    #             'spotInUseAmt': '',
    #             'spotInUseCcy': '',
    #             'thetaBS': '',
    #             'thetaPA': '',
    #             'tradeId': '193860531',
    #             'uTime': '1664526175010',
    #             'upl': '0.0000086393699748',
    #             'uplRatio': '0.0034695796212563',
    #             'usdPx': '',
    #             'vegaBS': '',
    #             'vegaPA': ''
    #           },
    #           'symbol': 'ETH/USD:ETH',
    #           'notional': 0.007461461551088627,
    #           'marginMode': 'cross',
    #           'liquidationPrice': 250.2305332057643,
    #           'entryPrice': 1338.67,
    #           'unrealizedPnl': 8.6393699748e-06,
    #           'percentage': 0.34695796212563,
    #           'contracts': 1.0,
    #           'contractSize': 10.0,
    #           'markPrice': 1340.22,
    #           'side': 'long',
    #           'hedged': False,
    #           'timestamp': 1664526175010,
    #           'datetime': '2022-09-30T08:22:55.010Z',
    #           'maintenanceMargin': 2.98458462044e-05,
    #           'maintenanceMarginPercentage': 0.004,
    #           'collateral': 0.0024957932203377,
    #           'initialMargin': 0.0024871538503629,
    #           'initialMarginPercentage': 0.3333,
    #           'leverage': 3.0,
    #           'marginRatio': 0.0119
    #         }
    #     """
    #     for data in info:
    #         update = False
    #         position = Position(self._platform, self._account, self._strategy, data['symbol'])
    #         if not position.timestamp:
    #             update = True
    #             position.update()
    #         if Decimal(data['info']['pos']) > 0:
    #             if position.long_quantity != data['contracts']:
    #                 update = True
    #                 position.update(margin_mode=MARGIN_MODE_CROSSED if data['marginMode']=="cross" else MARGIN_MODE_FIXED, long_quantity=data['contracts'], long_avg_qty=str(
    #                     Decimal(position.long_quantity) - Decimal(data['contractSize']) if Decimal(
    #                         data['contractSize']) < Decimal(position.long_quantity) else 0),
    #                                 long_open_price=data['entryPrice'],
    #                                 long_hold_price=data['info']['avgPx'],
    #                                 long_liquid_price=data['liquidationPrice'],
    #                                 long_unrealised_pnl=data['unrealizedPnl'],
    #                                 long_leverage=data['leverage'],
    #                                 long_margin=data['initialMargin'])
    #         elif Decimal(data['info']['pos']) < 0:
    #             if position.short_quantity != data['contracts']:
    #                 update = True
    #                 position.update(margin_mode=MARGIN_MODE_CROSSED if data['marginMode']=="cross" else MARGIN_MODE_FIXED, short_quantity=data['contracts'], short_avg_qty=str(
    #                     Decimal(position.long_quantity) - Decimal(data['contractSize']) if Decimal(
    #                         data['contractSize']) < Decimal(position.long_quantity) else 0),
    #                                 short_open_price=data['entryPrice'],
    #                                 short_hold_price=data['info']['avgPx'],
    #                                 short_liquid_price=data['liquidationPrice'],
    #                                 short_unrealised_pnl=data['unrealizedPnl'],
    #                                 short_leverage=data['leverage'],
    #                                 short_margin=data['initialMargin'])
    #         elif Decimal(data['info']['pos']) == 0:
    #             if position.long_quantity != 0 or position.short_quantity != 0:
    #                 update = True
    #                 position.update()
    # 
    #         # 此处与父类不同
    #         if not update or not self._position_update_callback:
    #             return
    #         SingleTask.run(self._on_position_update_callback, position)

    async def _asset(self, msg: dict):
        # {
        #     'arg': {
        #         'channel': 'account',
        #         'uid': '16009888698347520'
        #     },
        #     'data': [
        #         {
        #             'adjEq': '',
        #             'details': [
        #                 {
        #                     'availBal': '',
        #                     'availEq': '0.0373542405526773',
        #                     'cashBal': '0.0380898566614526',
        #                     'ccy': 'ETH',
        #                     'coinUsdPrice': '1356.4',
        #                     'crossLiab': '',
        #                     'disEq': '51.546585287444536',
        #                     'eq': '0.0380024957884433',
        #                     'eqUsd': '51.546585287444536',
        #                     'fixedBal': '0',
        #                     'frozenBal': '0.000648255235766',
        #                     'interest': '',
        #                     'isoEq': '0',
        #                     'isoLiab': '',
        #                     'isoUpl': '0',
        #                     'liab': '',
        #                     'maxLoan': '',
        #                     'mgnRatio': '104.21819799565878',
        #                     'notionalLever': '2.1322784935455004',
        #                     'ordFrozen': '0',
        #                     'spotInUseAmt': '',
        #                     'stgyEq': '0',
        #                     'twap': '0',
        #                     'uTime': '1663681041633',
        #                     'upl': '-0.0000873608730093'
        #                 },
        assets = {}
        for datas in msg['data']:
            for data in datas['details']:
                total = Decimal(data['eq'])
                free = Decimal(data['availEq'])
                locked = Decimal(data['frozenBal'])
                assets[data['ccy']] = {
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
    # 
    # async def _process_asset(self, info):
    #     # {'info': {
    #     #     'code': '0',
    #     #     'data': [
    #     #         {
    #     #             'adjEq': '',
    #     #             'details': [
    #     #                 {
    #     #                     'availBal': '',
    #     #                     'availEq': '0.037824340416646',
    #     #                     'cashBal': '0.0380935836102741',
    #     #                     'ccy': 'ETH',
    #     #                     'crossLiab': '',
    #     #                     'disEq': '51.924548751605',
    #     #                     'eq': '0.0384162446465416',
    #     #                     'eqUsd': '51.924548751605',
    #     #                     'fixedBal': '0',
    #     #                     'frozenBal': '0.0005919042298956',
    #     #                     'interest': '',
    #     #                     'isoEq': '0',
    #     #                     'isoLiab': '',
    #     #                     'isoUpl': '0',
    #     #                     'liab': '',
    #     #                     'maxLoan': '',
    #     #                     'mgnRatio': '115.38276394871686',
    #     #                     'notionalLever': '1.925956829401104',
    #     #                     'ordFrozen': '0',
    #     #                     'spotInUseAmt': '',
    #     #                     'stgyEq': '0',
    #     #                     'twap': '0',
    #     #                     'uTime': '1663660807531',
    #     #                     'upl': '0.0003226610362675',
    #     #                     'uplLiab': ''
    #     #                 },}
    #     assets = {}
    #     for datas in info['info']['data']:
    #         for data in datas['details']:
    #             total = Decimal(data['eq'])
    #             free = Decimal(data['availEq'])
    #             locked = Decimal(data['frozenBal'])
    #             assets[data['ccy']] = {
    #                 "total": "%.8f" % total,
    #                 "free": "%.8f" % free,
    #                 "locked": "%.8f" % locked
    #             }
    #         if assets == self._assets:
    #             update = False
    #         else:
    #             update = True
    #         if hasattr(self._assets, "assets") is False:
    #             info = {
    #                 "platform": self._platform,
    #                 "account": self._account,
    #                 "assets": assets,
    #                 "timestamp": tools.get_cur_timestamp_ms(),
    #                 "update": update
    #             }
    #             asset = Asset(**info)
    #             self._assets = asset
    # 
    #         else:
    #             for sym in assets: # 相当于for symbol in assets.keys():
    #                 self._assets.assets.update({
    #                     sym: assets[sym]
    #                 })
    #             self._assets.timestamp = tools.get_cur_timestamp_ms()
    # 
    #         SingleTask.run(self._on_asset_update_callback, self._assets)

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
    #       #   {
    #       #   'info': {
    #       #     'side': 'sell',
    #       #     'fillSz': '1',
    #       #     'fillPx': '1534.23',
    #       #     'fee': '-0.000001303585512',
    #       #     'ordId': '484985422280548367',
    #       #     'instType': 'SWAP',
    #       #     'instId': 'ETH-USD-SWAP',
    #       #     'clOrdId': 'O484985422276993024',
    #       #     'posSide': 'net',
    #       #     'billId': '484985445252751361',
    #       #     'tag': '',
    #       #     'execType': 'M',
    #       #     'tradeId': '187496777',
    #       #     'feeCcy': 'ETH',
    #       #     'ts': '1661901540742'
    #       #   },
    #       #   'timestamp': 1661901540742,
    #       #   'datetime': '2022-08-30T23:19:00.742Z',
    #       #   'symbol': 'ETH/USD:ETH',
    #       #   'id': '187496777',
    #       #   'order': '484985422280548367',
    #       #   'type': None,
    #       #   'takerOrMaker': 'maker',
    #       #   'side': 'sell',
    #       #   'price': 1534.23,
    #       #   'amount': 1.0,
    #       #   'cost': 0.0065179275597531,
    #       #   'fee': {
    #       #     'cost': 1.303585512e-06,
    #       #     'currency': 'ETH'
    #       #   },
    #       #   'fees': [
    #       #     {
    #       #       'currency': 'ETH',
    #       #       'cost': 1.303585512e-06
    #       #     }
    #       #   ]
    #       # }
    #     for data in info:   # 引用CCXT的格式化结果
    #         info = {
    #             "platform": self._platform,
    #             "account": self._account,
    #             "strategy": self._strategy,
    #             "symbol": data['symbol'],
    #             "fill_id": str(data['id']),
    #             "order_id": str(data['order']),
    #             "trade_type": data['category'],    # normal：普通委托订单种类 twap：TWAP订单种类 adl：ADL订单种类 full_liquidation：爆仓订单种类 partial_liquidation：减仓订单种类 delivery：交割 ddh：对冲减仓类型订单
    #             # "liquidity_price": None,
    #             "action": const.ORDER_ACTION_BUY if data['side'] == 'buy' else const.ORDER_ACTION_SELL,
    #             "price": str(data['price']),
    #             "quantity": str(data['amount']),
    #             "role": const.LIQUIDITY_TYPE_TAKER if data['takerOrMaker'] == "taker" else const.LIQUIDITY_TYPE_MAKER,
    #             "fee": str(data['info']['fee']) + "_" + data['info']['feeCcy'],
    #             "ctime": int(data['timestamp'])
    #         }
    #         fill = Fill(**info)
    # 
    #         SingleTask.run(self._on_fill_update_callback, fill)

    async def _position(self, info):
        # {
        #     'arg': {
        #         'channel': 'positions',
        #         'instType': 'SWAP',
        #         'instId': 'ETH-USD-SWAP',
        #         'uid': '16009888698347520'
        #     },
        #     'data': [
        #         {
        #             'adl': '2',
        #             'availPos': '',
        #             'avgPx': '1357.49',
        #             'baseBal': '',
        #             'cTime': '1663599231194',
        #             'ccy': 'ETH',
        #             'deltaBS': '',
        #             'deltaPA': '',
        #             'gammaBS': '',
        #             'gammaPA': '',
        #             'imr': '0.0005891493419938',
        #             'instId': 'ETH-USD-SWAP',
        #             'instType': 'SWAP',
        #             'interest': '0',
        #             'last': '1357.96',
        #             'lever': '125',
        #             'liab': '',
        #             'liabCcy': '',
        #             'liqPx': '2798.5664072115424',
        #             'margin': '',
        #             'markPx': '1357.89',
        #             'mgnMode': 'cross',
        #             'mgnRatio': '114.8831780032873',
        #             'mmr': '0.0002945746709969',
        #             'notionalUsd': '99.99631781661253',
        #             'optVal': '',
        #             'pTime': '1663674887669',
        #             'pendingCloseOrdLiabVal': '',
        #             'pos': '-10',
        #             'posCcy': '',
        #             'posId': '337443544378007557',
        #             'posSide': 'net',
        #             'quoteBal': '',
        #             'spotInUseAmt': '',
        #             'spotInUseCcy': '',
        #             'thetaBS': '',
        #             'thetaPA': '',
        #             'tradeId': '191853551',
        #             'uTime': '1663599231194',
        #             'upl': '-0.0000216999514543',
        #             'uplRatio': '-0.0368218338746285',
        #             'usdPx': '',
        #             'vegaBS': '',
        #             'vegaPA': ''
        #         }
        #     ]
        # }
        for data in info['data']:
            update = False
            position = Position(self._platform, self._account, self._strategy, self._symbol)
            if not position.timestamp:
                update = True
                position.update()
            if Decimal(data['pos']) > 0:
                if position.long_quantity != data['pos']:
                    update = True
                    position.update(margin_mode=MARGIN_MODE_CROSSED if data['mgnMode']=="cross" else MARGIN_MODE_FIXED, long_quantity=data['pos'], long_avg_qty=str(data['availPos']),
                                    long_open_price=data['avgPx'],
                                    long_hold_price=data['markPx'],
                                    long_liquid_price=data['liqPx'],
                                    long_unrealised_pnl=data['upl'],
                                    long_leverage=data['lever'],
                                    long_margin=data['margin'])
            elif Decimal(data['pos']) < 0:
                if position.short_quantity != data['pos']:
                    update = True
                    position.update(margin_mode=MARGIN_MODE_CROSSED if data['mgnMode']=="cross" else MARGIN_MODE_FIXED, short_quantity=abs(float(data['pos'])), short_avg_qty=str(data['availPos']),
                                    short_open_price=data['avgPx'],
                                    short_hold_price=data['markPx'],
                                    short_liquid_price=data['liqPx'],
                                    short_unrealised_pnl=data['upl'],
                                    short_leverage=data['lever'],
                                    short_margin=data['margin'])
            elif Decimal(data['pos']) == 0:
                if position.long_quantity != 0 or position.short_quantity != 0:
                    update = True
                    position.update()

            # 此处与父类不同
            if not update or not self._position_update_callback:
                return

            SingleTask.run(self._on_position_update_callback, position)

    # 根据Order返回的status修改
    def status(self, trade_quantity, remain, quantity, status_info):
        """
        订单状态
        canceled：撤单成功
        live：等待成交
        partially_filled： 部分成交
        filled：完全成交
        """
        if status_info == "live":
            return const.ORDER_STATUS_SUBMITTED
        elif status_info == "filled":
            return const.ORDER_STATUS_FILLED
        elif status_info == "partially_filled":
            return const.ORDER_STATUS_PARTIAL_FILLED
        elif status_info == "live":
            if float(remain) < float(quantity):
                return const.ORDER_STATUS_PARTIAL_FILLED
            else:
                return const.ORDER_STATUS_SUBMITTED
        elif status_info == "canceled":
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
          "arg": {
            "channel": "orders",
            "instType": "FUTURES",
            "instId": "BTC-USD-200329"
          },
          "data": [
            {
              "instType": "FUTURES",
              "instId": "BTC-USD-200329",
              "ccy": "BTC",
              "ordId": "312269865356374016",
              "clOrdId": "b1",
              "tag": "",
              "px": "999",
              "sz": "333",
              "notionalUsd": "",
              "ordType": "limit",
              "side": "buy",
              "posSide": "long",
              "tdMode": "cross",
              "tgtCcy": "",
              "fillSz": "0",
              "fillPx": "long",
              "tradeId": "0",
              "accFillSz": "323",
              "fillNotionalUsd": "",
              "fillTime": "0",
              "fillFee": "0.0001",
              "fillFeeCcy": "BTC",
              "execType": "T",
              "state": "canceled",
              "avgPx": "0",
              "lever": "20",
              "tpTriggerPx": "0",
              "tpOrdPx": "20",
              "slTriggerPx": "0",
              "slOrdPx": "20",
              "feeCcy": "",
              "fee": "",
              "rebateCcy": "",
              "rebate": "",
              "tgtCcy":"",
              "pnl": "",
              "category": "",
              "uTime": "1597026383085",
              "cTime": "1597026383085",
              "reqId": "",
              "amendResult": "",
              "code": "0",
              "msg": ""
            }
          ]
        }
        '''
        for data in msg['data']:
            pair = self.raw_symbol_to_std_symbol(data['instId'])
            order = self._orders.get(data['ordId'])
            if not order:
                info = {
                    "platform": self._platform,
                    "account": self._account,
                    "strategy": self._strategy,
                    "symbol": pair,
                    "order_id": str(data['ordId']),
                    "client_order_id": str(data['clOrdId']),
                    "action": const.ORDER_ACTION_BUY if data['side'] == 'buy' else const.ORDER_ACTION_SELL,
                    "order_type": const.ORDER_TYPE_LIMIT if data['ordType'] == "limit" else const.ORDER_TYPE_MARKET,
                    "order_price_type": data['category'],          # 没有改关键字，normal：普通委托订单种类 twap：TWAP订单种类 adl：ADL订单种类 full_liquidation：爆仓订单种类 partial_liquidation：减仓订单种类 delivery：交割 ddh：对冲减仓类型订单
                    "ctime": data['cTime'],
                }
                order = Order(**info)
                self._orders[data['ordId']] = order
            order.remain = float(data['sz']) - float(data['accFillSz'])
            order.avg_price = str(data['avgPx'])
            order.trade_type = data['tag']
            order.price = str(data['px'])
            order.quantity = str(data['sz'])
            order.utime = data['uTime']
            order.status = self.status(Decimal(data['accFillSz']), Decimal(order.remain), Decimal(data['sz']), data['state'])
            if order.status in [const.ORDER_STATUS_FAILED, const.ORDER_STATUS_CANCELED, const.ORDER_STATUS_FILLED]:
                self._orders.pop(data['ordId'])

            SingleTask.run(self._on_order_update_callback, order)

            if data['tradeId']:
                await self._fill(data)

    async def _fill(self, data: dict):
        """
        {
            "accFillSz": "0.001",
            "amendResult": "",
            "avgPx": "31527.1",
            "cTime": "1654084334977",
            "category": "normal",
            "ccy": "",
            "clOrdId": "",
            "code": "0",
            "execType": "M",
            "fee": "-0.02522168",
            "feeCcy": "USDT",
            "fillFee": "-0.02522168",
            "fillFeeCcy": "USDT",
            "fillNotionalUsd": "31.50818374",
            "fillPx": "31527.1",
            "fillSz": "0.001",
            "fillTime": "1654084353263",
            "instId": "BTC-USDT",
            "instType": "SPOT",
            "lever": "0",
            "msg": "",
            "notionalUsd": "31.50818374",
            "ordId": "452197707845865472",
            "ordType": "limit",
            "pnl": "0",
            "posSide": "",
            "px": "31527.1",
            "rebate": "0",
            "rebateCcy": "BTC",
            "reduceOnly": "false",
            "reqId": "",
            "side": "sell",
            "slOrdPx": "",
            "slTriggerPx": "",
            "slTriggerPxType": "last",
            "source": "",
            "state": "filled",
            "sz": "0.001",
            "tag": "",
            "tdMode": "cash",
            "tgtCcy": "",
            "tpOrdPx": "",
            "tpTriggerPx": "",
            "tpTriggerPxType": "last",
            "tradeId": "242589207",
            "uTime": "1654084353264"
        }
        """
        pair = self.raw_symbol_to_std_symbol(data['instId'])
        info = {
                "platform": self._platform,
                "account": self._account,
                "strategy": self._strategy,
                "symbol": pair,
                "fill_id": str(data['tradeId']),
                "order_id": str(data['ordId']),
                "trade_type": data['category'],    # normal：普通委托订单种类 twap：TWAP订单种类 adl：ADL订单种类 full_liquidation：爆仓订单种类 partial_liquidation：减仓订单种类 delivery：交割 ddh：对冲减仓类型订单
                # "liquidity_price": data['o']['AP'],
                "action": const.ORDER_ACTION_BUY if data['side'] == 'buy' else const.ORDER_ACTION_SELL,
                "price": str(data['fillPx']),
                "quantity": str(data['fillSz']),
                "role": const.LIQUIDITY_TYPE_TAKER if data['execType'] == "T" else const.LIQUIDITY_TYPE_MAKER,
                "fee": str(data['fillFee'] + "_" + data['fillFeeCcy']) if data.get('fillFee') else None,
                "ctime": data['fillTime']
            }
        fill = Fill(**info)
        SingleTask.run(self._on_fill_update_callback, fill)


class OKExMarket(ExchangeWebsocket):
    """OKx Market module.
    """
    valid_candle_intervals = {'1D', '12H', '6H', '4H', '2H', '1H', '30m', '15m', '5m', '1m'}
    candle_interval_map = {'1D': 86400, '12H': 43200, '6H': 21600, '4H': 14400, '2H': 7200, '1H': 3600, '30m': 1800,
                           '15m': 900, '5m': 300, '1m': 60}
    # OKX的频道多只取需要的
    websocket_channels = {
        # 公共频道
        const.L2_BOOK: 'books',   # action: partial, action: update
        const.TICKER: 'tickers',
        const.CANDLES: 'candle',  # 完整字段candle1m
        const.TRADES: 'trades',
        # 私有频道
        const.ORDERS: 'orders',
        const.ACCOUNTS: 'account',
        const.POSITIONS: 'positions',
        # 需要CCXT获取
        const.FILLS: 'fills'     # 最好不要用RestApi,请求全市场数据（特指symbol）时会限IP频次
    }
    def __init__(self, **kwargs):
        """Initialize Market module."""
        e = None
        if not kwargs.get("account"):
            e = Error("param account miss")
        if not kwargs.get("host"):
            kwargs["host"] = "www.okx.com"
        if not kwargs.get("wss"):
            kwargs["wss"] = None
        if not kwargs.get("access_key"):
            e = Error("param access_key miss")
        if not kwargs.get("secret_key"):
            e = Error("param secret_key miss")
        if not kwargs.get("passphrase"):
            e = Error("param passphrase miss")
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
        self._passphrase = kwargs["passphrase"]
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
        self.requires_authentication = False # 判断websocket sned时选择哪条线路
        # self._trades = {}
        # self._tickers = {}
        # Initialize our REST API client.
        self._rest_api = OKExRestAPI({"apiKey":self._access_key,"secret":self._secret_key, "password": self._passphrase,"hostname":self._host})  # 'funding', 'spot', 'margin', 'futures', 'swap', 'option'

        # Create a loop run task to send ping message to server per 5 seconds.
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
                "value_tick": data['info']['ctVal'],
                "value_limit": data['limits']['cost']['min'],
                "base_currency": data['base'],
                "quote_currency": data['quote'],
                "settlement_currency": data['quote'],
                "symbol_type": data['type'],
                "is_inverse": data['inverse'],
                "multiplier": data['info']['ctMult']
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

        self._wsp = Websocket("wss://ws.okx.com:8443/ws/v5/private", self.private_connected_callback, process_callback=self.process)
        LoopRunTask.register(self._private_send_heartbeat_msg, 20)

        self._ws = Websocket("wss://ws.okx.com:8443/ws/v5/public", self.connected_callback, process_callback=self.process)
        LoopRunTask.register(self._send_heartbeat_msg, 20)

    async def private_connected_callback(self):
        if self._symbols and self.websocket_channels.keys():
            if any(self.is_authenticated_channel(chan) for chan in self.websocket_channels.keys()):  # 如果有私有频道就注册
                if not self._access_key or not self._secret_key:
                    raise ValueError("Authenticated channel subscribed to, but no auth keys provided")
                await self.generate_token()
                await asyncio.sleep(1)
                
        SingleTask.run(self._init_callback, True)
        
    async def connected_callback(self):
        raw_channels = list(set([self.std_channel_to_raw_channel(chan) for chan in self.websocket_channels.keys()]))
        sub = {chan: self._symbols for chan in raw_channels}    # 此处会引入一些交易所没有的频道
        await self.subscribe(sub)
        
        SingleTask.run(self._init_callback, True)
        
    async def subscribe(self, sub: dict):
        for chan in sub:
            channels = []
            # 根据机器配置,有些频道不订阅,对自动订阅的没作用
            if chan == self.std_channel_to_raw_channel(const.FILLS) and not self._fill_update_callback:
                continue
            if chan == self.std_channel_to_raw_channel(const.ORDERS) and not self._order_update_callback:
                continue
            if chan == self.std_channel_to_raw_channel(const.ACCOUNTS) and not self._asset_update_callback:
                continue
            if chan == self.std_channel_to_raw_channel(const.POSITIONS) and not self._position_update_callback:
                continue
            if chan == self.std_channel_to_raw_channel(const.L2_BOOK) and not self._orderbook_update_callback:
                continue
            if chan == self.std_channel_to_raw_channel(const.TICKER) and not self._ticker_update_callback:
                continue
            if chan == self.std_channel_to_raw_channel(const.TRADES) and not self._trade_update_callback:
                continue
            if chan == self.std_channel_to_raw_channel(const.CANDLES) and not self._kline_update_callback:
                continue
            # 根据chan的不同判断线路的标志
            if self.is_authenticated_channel(self.raw_channel_to_std_channel(chan)):
                self.requires_authentication = True
            else:
                self.requires_authentication = False

            for symbol in sub[chan]:
                # 需要CCXT的频道
                if chan == self.std_channel_to_raw_channel(const.FILLS):  # 此处将前面引入的自定义频道过滤，或者通过自定义方法获取data
                    # asyncio.create_task(self._fetch_fills(symbol))    # 最好不要用RestApi,请求全市场数据（特指symbol）时会限IP频次
                    continue

                # 没有websokcet,自定需要restAPI的及过滤(过滤掉websocket channel 中有并且不需要的chan
                # elif chan == self.std_channel_to_raw_channel(const.POSITIONS):
                #     asyncio.create_task(self._fetch_position(symbol))
                #     continue

                # 有Websocket的频道
                channels.append([self.build_subscription(chan, self.std_symbol_to_raw_symbol(symbol), candle_interval) for candle_interval in
                                 self.valid_candle_intervals])

            # 有些channels在追加后嵌套的需要展开
            ch = [item for sublist in channels for item in sublist]
            # 删除重复的频道
            ch = [dict(t) for t in set([tuple(d.items()) for d in ch])]
            # 现货不存在position
            spot_position = [channel for channel in ch if
                  channel.get('channel') == 'positions' and channel.get('instType') in ['MARGIN', 'SPOT']]
            ch = [channel for channel in ch if channel not in spot_position]
            if not ch:
                continue

            # msg = {"op": "subscribe", "args": ch}
            # 因为不能一次性发送太多订阅，分拆第组20个发送
            def split_list(_list: list, n: int):
                for i in range(0, len(_list), n):
                    yield _list[i:i + n]

            if self.requires_authentication:
                [await self._wsp.send({"op": "subscribe", "args": channel}) for channel in split_list(ch, 20)]
            else:
                [await self._ws.send({"op": "subscribe", "args": channel}) for channel in split_list(ch, 20)]


    async def _send_heartbeat_msg(self, *args, **kwargs):
        """Send ping to server."""
        hb = 'ping'
        try:
            await self._ws.send(hb)
        except Exception as e:
            logger.error(e, caller=self)

    async def _private_send_heartbeat_msg(self, *args, **kwargs):
        """Send ping to server."""
        hb = 'ping'
        try:
            await self._wsp.send(hb)
        except Exception as e:
            logger.error(e, caller=self)

    async def generate_token(self):
        timestamp = int(time.time())
        message = str(timestamp) + 'GET' + '/users/self/verify'
        mac = hmac.new(bytes(self._secret_key, encoding="utf8"), bytes(message, encoding="utf8"), digestmod="sha256")
        d = mac.digest()
        sign = base64.b64encode(d).decode()
        params = {
            "apiKey": self._access_key,
            "passphrase": self._passphrase,
            "timestamp": timestamp,
            'sign': sign,
        }
        data = {"op": "login", "args": [params]}
        await self._wsp.send(data)

    def inst_type_to_okx_type(self, ticker):
        sym = self.raw_symbol_to_std_symbol(ticker)
        # 根据symbol确定交易类型
        instrument_type = self._symbols[sym].symbol_type
        # 'CCXT spot', funding', 'spot', 'margin', 'future', 'swap', 'option'
        # SPOT：币币
        # MARGIN：币币杠杆
        # SWAP：永续合约
        # FUTURES：交割合约
        # OPTION：期权
        instrument_type_map = {
            'spot': 'SPOT',
            'margin': 'MARGIN',
            'swap': 'SWAP',
            'future': 'FUTURES',
            'option': 'OPTION'
        }
        return instrument_type_map.get(instrument_type, 'MARGIN')

    def build_subscription(self, channel: str, ticker: str, candle_interval: str) -> dict:
        if channel in ['positions', 'orders']:
            subscription_dict = {"channel": channel,
                                 "instType": self.inst_type_to_okx_type(ticker),
                                 "instId": ticker}
        elif channel in ['candle']:
            subscription_dict = {"channel": f"{channel}{candle_interval}",
                                 "instId": ticker}
        else:
            subscription_dict = {"channel": channel,
                                 "instId": ticker}
        return subscription_dict

    @async_method_locker("OKExMarket.process.locker")
    async def process(self, msg):
        """Process message that received from Websocket connection.

        Args:
            msg: message received from Websocket connection.
        """
        if 'event' in msg:
            if msg['event'] == 'error':
                logger.error("{}: Error: {}".format(self._platform, msg), caller=self)
            elif msg['event'] == 'subscribe':
                pass
            elif msg['event'] == 'login':
                # 注册成功后调用订阅,不然private线路没有subscibe
                raw_channels = list(set([self.std_channel_to_raw_channel(chan) for chan in self.websocket_channels.keys()]))
                sub = {chan: self._symbols for chan in raw_channels}
                await self.subscribe(sub)
                logger.debug('{}: Websocket logged in? {}'.format(self._platform, msg['code']), caller=self)
            else:
                logger.warn("{}: Unhandled event {}".format(self._platform, msg), caller=self)

        elif 'arg' in msg:
            if self.websocket_channels[const.L2_BOOK] in msg['arg']['channel']:
                await self._book(msg)
            elif self.websocket_channels[const.TICKER] in msg['arg']['channel']:
                await self._ticker(msg)
            elif self.websocket_channels[const.TRADES] in msg['arg']['channel']:
                await self._trade(msg)
            if self.websocket_channels[const.ORDERS] in msg['arg']['channel']:
                await self._order(msg)
            elif self.websocket_channels[const.POSITIONS] in msg['arg']['channel']:
                await self._position(msg)
            elif self.websocket_channels[const.CANDLES] in msg['arg']['channel']:
                await self._candle(msg)
            elif self.websocket_channels[const.ACCOUNTS] in msg['arg']['channel']:
                await self._asset(msg)
        else:
            logger.warn("{}: Unhandled message {}".format(self._platform, msg), caller=self)
    # 
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
    # # okex是仓位有变化时才推送，没有使用
    # async def _process_positions(self, info):
    #     """
    #         {
    #           'info': {
    #             'adl': '4',
    #             'availPos': '',
    #             'avgPx': '1338.67',
    #             'baseBal': '',
    #             'cTime': '1664526175010',
    #             'ccy': 'ETH',
    #             'deltaBS': '',
    #             'deltaPA': '',
    #             'gammaBS': '',
    #             'gammaPA': '',
    #             'imr': '0.0024871538503629',
    #             'instId': 'ETH-USD-SWAP',
    #             'instType': 'SWAP',
    #             'interest': '0',
    #             'last': '1340.33',
    #             'lever': '3',
    #             'liab': '',
    #             'liabCcy': '',
    #             'liqPx': '250.2305332057643',
    #             'margin': '',
    #             'markPx': '1340.22',
    #             'mgnMode': 'cross',
    #             'mgnRatio': '973.3428546449297',
    #             'mmr': '0.0000298458462044',
    #             'notionalUsd': '9.998731551536315',
    #             'optVal': '',
    #             'pendingCloseOrdLiabVal': '',
    #             'pos': '1',
    #             'posCcy': '',
    #             'posId': '337443544378007557',
    #             'posSide': 'net',
    #             'quoteBal': '',
    #             'spotInUseAmt': '',
    #             'spotInUseCcy': '',
    #             'thetaBS': '',
    #             'thetaPA': '',
    #             'tradeId': '193860531',
    #             'uTime': '1664526175010',
    #             'upl': '0.0000086393699748',
    #             'uplRatio': '0.0034695796212563',
    #             'usdPx': '',
    #             'vegaBS': '',
    #             'vegaPA': ''
    #           },
    #           'symbol': 'ETH/USD:ETH',
    #           'notional': 0.007461461551088627,
    #           'marginMode': 'cross',
    #           'liquidationPrice': 250.2305332057643,
    #           'entryPrice': 1338.67,
    #           'unrealizedPnl': 8.6393699748e-06,
    #           'percentage': 0.34695796212563,
    #           'contracts': 1.0,
    #           'contractSize': 10.0,
    #           'markPrice': 1340.22,
    #           'side': 'long',
    #           'hedged': False,
    #           'timestamp': 1664526175010,
    #           'datetime': '2022-09-30T08:22:55.010Z',
    #           'maintenanceMargin': 2.98458462044e-05,
    #           'maintenanceMarginPercentage': 0.004,
    #           'collateral': 0.0024957932203377,
    #           'initialMargin': 0.0024871538503629,
    #           'initialMarginPercentage': 0.3333,
    #           'leverage': 3.0,
    #           'marginRatio': 0.0119
    #         }
    #     """
    #     for data in info:
    #         update = False
    #         position = Position(self._platform, self._account, data['symbol'])
    #         if not position.timestamp:
    #             update = True
    #             position.update()
    #         if Decimal(data['info']['pos']) > 0:
    #             if position.long_quantity != data['contracts']:
    #                 update = True
    #                 position.update(margin_mode=MARGIN_MODE_CROSSED if data['marginMode']=="cross" else MARGIN_MODE_FIXED, long_quantity=data['contracts'], long_avg_qty=str(
    #                     Decimal(position.long_quantity) - Decimal(data['contractSize']) if Decimal(
    #                         data['contractSize']) < Decimal(position.long_quantity) else 0),
    #                                 long_open_price=data['entryPrice'],
    #                                 long_hold_price=data['info']['avgPx'],
    #                                 long_liquid_price=data['liquidationPrice'],
    #                                 long_unrealised_pnl=data['unrealizedPnl'],
    #                                 long_leverage=data['leverage'],
    #                                 long_margin=data['initialMargin'])
    #         elif Decimal(data['info']['pos']) < 0:
    #             if position.short_quantity != data['contracts']:
    #                 update = True
    #                 position.update(margin_mode=MARGIN_MODE_CROSSED if data['marginMode']=="cross" else MARGIN_MODE_FIXED, short_quantity=data['contracts'], short_avg_qty=str(
    #                     Decimal(position.long_quantity) - Decimal(data['contractSize']) if Decimal(
    #                         data['contractSize']) < Decimal(position.long_quantity) else 0),
    #                                 short_open_price=data['entryPrice'],
    #                                 short_hold_price=data['info']['avgPx'],
    #                                 short_liquid_price=data['liquidationPrice'],
    #                                 short_unrealised_pnl=data['unrealizedPnl'],
    #                                 short_leverage=data['leverage'],
    #                                 short_margin=data['initialMargin'])
    #         elif Decimal(data['info']['pos']) == 0:
    #             if position.long_quantity != 0 or position.short_quantity != 0:
    #                 update = True
    #                 position.update()
    # 
    #         # 此处与父类不同
    #         if not update or not self._position_update_callback:
    #             return
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
    #     #   {
    #     #   'info': {
    #     #     'side': 'sell',
    #     #     'fillSz': '1',
    #     #     'fillPx': '1534.23',
    #     #     'fee': '-0.000001303585512',
    #     #     'ordId': '484985422280548367',
    #     #     'instType': 'SWAP',
    #     #     'instId': 'ETH-USD-SWAP',
    #     #     'clOrdId': 'O484985422276993024',
    #     #     'posSide': 'net',
    #     #     'billId': '484985445252751361',
    #     #     'tag': '',
    #     #     'execType': 'M',
    #     #     'tradeId': '187496777',
    #     #     'feeCcy': 'ETH',
    #     #     'ts': '1661901540742'
    #     #   },
    #     #   'timestamp': 1661901540742,
    #     #   'datetime': '2022-08-30T23:19:00.742Z',
    #     #   'symbol': 'ETH/USD:ETH',
    #     #   'id': '187496777',
    #     #   'order': '484985422280548367',
    #     #   'type': None,
    #     #   'takerOrMaker': 'maker',
    #     #   'side': 'sell',
    #     #   'price': 1534.23,
    #     #   'amount': 1.0,
    #     #   'cost': 0.0065179275597531,
    #     #   'fee': {
    #     #     'cost': 1.303585512e-06,
    #     #     'currency': 'ETH'
    #     #   },
    #     #   'fees': [
    #     #     {
    #     #       'currency': 'ETH',
    #     #       'cost': 1.303585512e-06
    #     #     }
    #     #   ]
    #     # }
    #     for data in info:  # 引用CCXT的格式化结果
    #         info = {
    #             "platform": self._platform,
    #             "account": self._account,
    #             "symbol": data['symbol'],
    #             "fill_id": str(data['id']),
    #             "order_id": str(data['order']),
    #             "trade_type": data['category'],    # normal：普通委托订单种类 twap：TWAP订单种类 adl：ADL订单种类 full_liquidation：爆仓订单种类 partial_liquidation：减仓订单种类 delivery：交割 ddh：对冲减仓类型订单
    #             # "liquidity_price": None,
    #             "action": const.ORDER_ACTION_BUY if data['side'] == 'buy' else const.ORDER_ACTION_SELL,
    #             "price": str(data['price']),
    #             "quantity": str(data['amount']),
    #             "role": const.LIQUIDITY_TYPE_TAKER if data['takerOrMaker'] == "taker" else const.LIQUIDITY_TYPE_MAKER,
    #             "fee": str(data['info']['fee']) + "_" + data['info']['feeCcy'],
    #             "ctime": int(data['timestamp'])
    #         }
    #         fill = Fill(**info)
    # 
    #         SingleTask.run(self._on_fill_update_callback, fill)

    async def _position(self, info):
        # {
        #     'arg': {
        #         'channel': 'positions',
        #         'instType': 'SWAP',
        #         'instId': 'ETH-USD-SWAP',
        #         'uid': '16009888698347520'
        #     },
        #     'data': [
        #         {
        #             'adl': '2',
        #             'availPos': '',
        #             'avgPx': '1357.49',
        #             'baseBal': '',
        #             'cTime': '1663599231194',
        #             'ccy': 'ETH',
        #             'deltaBS': '',
        #             'deltaPA': '',
        #             'gammaBS': '',
        #             'gammaPA': '',
        #             'imr': '0.0005891493419938',
        #             'instId': 'ETH-USD-SWAP',
        #             'instType': 'SWAP',
        #             'interest': '0',
        #             'last': '1357.96',
        #             'lever': '125',
        #             'liab': '',
        #             'liabCcy': '',
        #             'liqPx': '2798.5664072115424',
        #             'margin': '',
        #             'markPx': '1357.89',
        #             'mgnMode': 'cross',
        #             'mgnRatio': '114.8831780032873',
        #             'mmr': '0.0002945746709969',
        #             'notionalUsd': '99.99631781661253',
        #             'optVal': '',
        #             'pTime': '1663674887669',
        #             'pendingCloseOrdLiabVal': '',
        #             'pos': '-10',
        #             'posCcy': '',
        #             'posId': '337443544378007557',
        #             'posSide': 'net',
        #             'quoteBal': '',
        #             'spotInUseAmt': '',
        #             'spotInUseCcy': '',
        #             'thetaBS': '',
        #             'thetaPA': '',
        #             'tradeId': '191853551',
        #             'uTime': '1663599231194',
        #             'upl': '-0.0000216999514543',
        #             'uplRatio': '-0.0368218338746285',
        #             'usdPx': '',
        #             'vegaBS': '',
        #             'vegaPA': ''
        #         }
        #     ]
        # }
        for data in info['data']:
            update = False
            position = Position(self._platform, self._account, symbol=self.raw_symbol_to_std_symbol(data['instId']))
            if not position.timestamp:
                update = True
                position.update()
            if Decimal(data['pos']) > 0:
                if position.long_quantity != data['pos']:
                    update = True
                    position.update(margin_mode=MARGIN_MODE_CROSSED if data['mgnMode']=="cross" else MARGIN_MODE_FIXED, long_quantity=data['pos'], long_avg_qty=str(data['availPos']),
                                    long_open_price=data['avgPx'],
                                    long_hold_price=data['markPx'],
                                    long_liquid_price=data['liqPx'],
                                    long_unrealised_pnl=data['upl'],
                                    long_leverage=data['lever'],
                                    long_margin=data['margin'])
            elif Decimal(data['pos']) < 0:
                if position.short_quantity != data['pos']:
                    update = True
                    position.update(margin_mode=MARGIN_MODE_CROSSED if data['mgnMode']=="cross" else MARGIN_MODE_FIXED, short_quantity=abs(float(data['pos'])), short_avg_qty=str(data['availPos']),
                                    short_open_price=data['avgPx'],
                                    short_hold_price=data['markPx'],
                                    short_liquid_price=data['liqPx'],
                                    short_unrealised_pnl=data['upl'],
                                    short_leverage=data['lever'],
                                    short_margin=data['margin'])
            elif Decimal(data['pos']) == 0:
                if position.long_quantity != 0 or position.short_quantity != 0:
                    update = True
                    position.update()

            # 此处与父类不同
            if not update or not self._position_update_callback:
                return

            SingleTask.run(self._on_position_update_callback, position)

    def status(self, trade_quantity, remain, quantity, status_info):
        """
        订单状态
        canceled：撤单成功
        live：等待成交
        partially_filled： 部分成交
        filled：完全成交
        """
        if status_info == "live":
            return const.ORDER_STATUS_SUBMITTED
        elif status_info == "filled":
            return const.ORDER_STATUS_FILLED
        elif status_info == "partially_filled":
            return const.ORDER_STATUS_PARTIAL_FILLED
        elif status_info == "live":
            if float(remain) < float(quantity):
                return const.ORDER_STATUS_PARTIAL_FILLED
            else:
                return const.ORDER_STATUS_SUBMITTED
        elif status_info == "canceled":
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
          "arg": {
            "channel": "orders",
            "instType": "FUTURES",
            "instId": "BTC-USD-200329"
          },
          "data": [
            {
              "instType": "FUTURES",
              "instId": "BTC-USD-200329",
              "ccy": "BTC",
              "ordId": "312269865356374016",
              "clOrdId": "b1",
              "tag": "",
              "px": "999",
              "sz": "333",
              "notionalUsd": "",
              "ordType": "limit",
              "side": "buy",
              "posSide": "long",
              "tdMode": "cross",
              "tgtCcy": "",
              "fillSz": "0",
              "fillPx": "long",
              "tradeId": "0",
              "accFillSz": "323",
              "fillNotionalUsd": "",
              "fillTime": "0",
              "fillFee": "0.0001",
              "fillFeeCcy": "BTC",
              "execType": "T",
              "state": "canceled",
              "avgPx": "0",
              "lever": "20",
              "tpTriggerPx": "0",
              "tpOrdPx": "20",
              "slTriggerPx": "0",
              "slOrdPx": "20",
              "feeCcy": "",
              "fee": "",
              "rebateCcy": "",
              "rebate": "",
              "tgtCcy":"",
              "pnl": "",
              "category": "",
              "uTime": "1597026383085",
              "cTime": "1597026383085",
              "reqId": "",
              "amendResult": "",
              "code": "0",
              "msg": ""
            }
          ]
        }
        '''
        for data in msg['data']:
            pair = self.raw_symbol_to_std_symbol(data['instId'])
            order = self._orders.get(data['ordId'])
            if not order:
                info = {
                    "platform": self._platform,
                    "account": self._account,
                    "symbol": pair,
                    "order_id": str(data['ordId']),
                    "client_order_id": str(data['clOrdId']),
                    "action": const.ORDER_ACTION_BUY if data['side'] == 'buy' else const.ORDER_ACTION_SELL,
                    "order_type": const.ORDER_TYPE_LIMIT if data['ordType'] == "limit" else const.ORDER_TYPE_MARKET,
                    "order_price_type": data['category'],          # 没有改关键字，normal：普通委托订单种类 twap：TWAP订单种类 adl：ADL订单种类 full_liquidation：爆仓订单种类 partial_liquidation：减仓订单种类 delivery：交割 ddh：对冲减仓类型订单
                    "ctime": data['cTime'],
                }
                order = Order(**info)
                self._orders[data['ordId']] = order
            order.remain = float(data['sz']) - float(data['accFillSz'])
            order.avg_price = str(data['avgPx'])
            order.trade_type = data['tag']   # 开多 平多 开空 平空
            order.price = str(data['px'])
            order.quantity = str(data['sz'])
            order.utime = data['uTime']
            order.status = self.status(Decimal(data['accFillSz']), Decimal(order.remain), Decimal(data['sz']), data['state'])
            if order.status in [const.ORDER_STATUS_FAILED, const.ORDER_STATUS_CANCELED, const.ORDER_STATUS_FILLED]:
                self._orders.pop(data['ordId'])

            SingleTask.run(self._on_order_update_callback, order)

            if data['tradeId']:
                await self._fill(data)

    async def _fill(self, data: dict):
        """
        {
            "accFillSz": "0.001",
            "amendResult": "",
            "avgPx": "31527.1",
            "cTime": "1654084334977",
            "category": "normal",
            "ccy": "",
            "clOrdId": "",
            "code": "0",
            "execType": "M",
            "fee": "-0.02522168",
            "feeCcy": "USDT",
            "fillFee": "-0.02522168",
            "fillFeeCcy": "USDT",
            "fillNotionalUsd": "31.50818374",
            "fillPx": "31527.1",
            "fillSz": "0.001",
            "fillTime": "1654084353263",
            "instId": "BTC-USDT",
            "instType": "SPOT",
            "lever": "0",
            "msg": "",
            "notionalUsd": "31.50818374",
            "ordId": "452197707845865472",
            "ordType": "limit",
            "pnl": "0",
            "posSide": "",
            "px": "31527.1",
            "rebate": "0",
            "rebateCcy": "BTC",
            "reduceOnly": "false",
            "reqId": "",
            "side": "sell",
            "slOrdPx": "",
            "slTriggerPx": "",
            "slTriggerPxType": "last",
            "source": "",
            "state": "filled",
            "sz": "0.001",
            "tag": "",
            "tdMode": "cash",
            "tgtCcy": "",
            "tpOrdPx": "",
            "tpTriggerPx": "",
            "tpTriggerPxType": "last",
            "tradeId": "242589207",
            "uTime": "1654084353264"
        }
        """
        pair = self.raw_symbol_to_std_symbol(data['instId'])
        info = {
                "platform": self._platform,
                "account": self._account,
                "symbol": pair,
                "fill_id": str(data['tradeId']),
                "order_id": str(data['ordId']),
                "trade_type": data['category'],    # normal：普通委托订单种类 twap：TWAP订单种类 adl：ADL订单种类 full_liquidation：爆仓订单种类 partial_liquidation：减仓订单种类 delivery：交割 ddh：对冲减仓类型订单
                # "liquidity_price": data['o']['AP'],
                "action": const.ORDER_ACTION_BUY if data['side'] == 'buy' else const.ORDER_ACTION_SELL,
                "price": str(data['fillPx']),
                "quantity": str(data['fillSz']),
                "role": const.LIQUIDITY_TYPE_TAKER if data['execType'] == "T" else const.LIQUIDITY_TYPE_MAKER,
                "fee": str(data['fillFee'] + "_" + data['fillFeeCcy']) if data.get('fillFee') else None,
                "ctime": data['fillTime']
            }
        fill = Fill(**info)

        SingleTask.run(self._on_fill_update_callback, fill)

    async def _trade(self, msg: dict):
            # {
            #   'arg': {
            #     'channel': 'trades',
            #     'instId': 'BTC-USD-SWAP'
            #   },
            #   'data': [
            #     {
            #       'instId': 'BTC-USD-SWAP',
            #       'tradeId': '202711912',
            #       'px': '19081.2',
            #       'sz': '5',
            #       'side': 'sell',
            #       'ts': '1663685513448'
            #     }
            #   ]
            # }
        for data in msg['data']:
            pair = self.raw_symbol_to_std_symbol(data['instId'])
            info = {
                "platform": self._platform,
                "symbol": pair,
                "action": const.ORDER_ACTION_BUY if data["side"] == "buy" else const.ORDER_ACTION_SELL,
                "price": data['px'],
                "quantity": data['sz'],
                "id": data['tradeId'],
                "timestamp": int(data['ts'])  # Unix时间戳的毫秒数格式
            }
            trade = Trade(**info)
            # self._trades[pair] = trade

            SingleTask.run(self._on_trade_update_callback, trade)

    async def _ticker(self, msg: dict):
        # {
        #     'arg': {
        #         'channel': 'tickers',
        #         'instId': 'BTC-USD-SWAP'
        #     },
        #     'data': [
        #         {
        #             'instType': 'SWAP',
        #             'instId': 'BTC-USD-SWAP',
        #             'last': '19080.5',
        #             'lastSz': '14',
        #             'askPx': '19080.6',
        #             'askSz': '297',
        #             'bidPx': '19080.5',
        #             'bidSz': '369',
        #             'open24h': '19331.5',
        #             'high24h': '19686.6',
        #             'low24h': '18782.5',
        #             'sodUtc0': '19538.9',
        #             'sodUtc8': '19081.1',
        #             'volCcy24h': '19812.39',
        #             'vol24h': '3816731',
        #             'ts': '1663685513107'
        #         }
        #     ]
        # }
        for data in msg['data']:
            pair = self.raw_symbol_to_std_symbol(data['instId'])
            info = {
                "platform": self._platform,
                "symbol": pair,
                "ask": {data['askPx']: data['askSz']},
                "bid": {data['bidPx']: data['bidSz']},
                "last": {data['last']: data['lastSz']},
                "timestamp": int(data["ts"])  # Unix时间戳的毫秒数格式
            }
            ticker = Ticker(**info)
            # self._tickers[pair] = ticker
            SingleTask.run(self._on_ticker_update_callback, ticker)

    async def _book(self, msg: dict):
        if msg['action'] == 'snapshot':
            # snapshot
            pair = self.raw_symbol_to_std_symbol(msg['arg']['instId'])
            for update in msg['data']:
                bids = {price: amount for price, amount, *_ in update['bids']}
                asks = {price: amount for price, amount, *_ in update['asks']}
                info = {
                    "platform": self._platform,
                    "symbol": pair,
                    "asks": asks,
                    "bids": bids,
                    "timestamp": int(update["ts"])  # Unix时间戳的毫秒数格式
                }
                orderbook = Orderbook(**info)
                self._orderbooks[pair] = orderbook

                SingleTask.run(self._on_orderbook_update_callback, orderbook)

        else:
            # update
            delta = {"bids": [], "asks": []}
            pair = self.raw_symbol_to_std_symbol(msg['arg']['instId'])
            for data in msg['data']:
                self._orderbooks[pair].timestamp = int(data["ts"])
                for side in ('bids', 'asks'):
                    s = "bids" if side == 'bids' else "asks"
                    for price, amount, *_ in data[side]:
                        if float(amount) == 0:
                            if price in getattr(self._orderbooks[pair], s):
                                delta[s].append((price, 0))
                                del getattr(self._orderbooks[pair], s)[price]
                        else:
                            delta[s].append((price, amount))
                            getattr(self._orderbooks[pair], s)[price] = amount  # 对类属性值操作
                SingleTask.run(self._on_orderbook_update_callback, self._orderbooks[pair])

    async def _candle(self, msg: dict):
        # {
        #     'arg': {
        #         'channel': 'candle1M',
        #         'instId': 'BTC-USD-SWAP'
        #     },
        #     'data': [
        #         [
        #             '1661961600000',
        #             '20140.4',
        #             '22822.6',
        #             '18167.9',
        #             '19080.5',
        #             '104329347',
        #             '515363.406'
        #         ]
        #     ]
        # }
        pair = self.raw_symbol_to_std_symbol(msg['arg']['instId'])
        kline_type = const.MARKET_TYPE_KLINE if msg['arg']['channel'][6:] == '1m' else "kline_" + msg['arg']['channel'][6:].lower()
        for data in msg['data']:
            info = {
                "platform": self._platform,
                "symbol": pair,
                "start": None,
                "stop": None,
                "open": data[1],
                "high": data[2],
                "low": data[3],
                "close": data[4],
                "volume": data[6],
                "timestamp": int(data[0]),
                "kline_type": kline_type
            }
            kline = Kline(**info)
            # self._tickers[pair] = ticker
            SingleTask.run(self._on_kline_update_callback, kline)


    async def _asset(self, msg: dict):
        # {
        #     'arg': {
        #         'channel': 'account',
        #         'uid': '16009888698347520'
        #     },
        #     'data': [
        #         {
        #             'adjEq': '',
        #             'details': [
        #                 {
        #                     'availBal': '',
        #                     'availEq': '0.0373542405526773',
        #                     'cashBal': '0.0380898566614526',
        #                     'ccy': 'ETH',
        #                     'coinUsdPrice': '1356.4',
        #                     'crossLiab': '',
        #                     'disEq': '51.546585287444536',
        #                     'eq': '0.0380024957884433',
        #                     'eqUsd': '51.546585287444536',
        #                     'fixedBal': '0',
        #                     'frozenBal': '0.000648255235766',
        #                     'interest': '',
        #                     'isoEq': '0',
        #                     'isoLiab': '',
        #                     'isoUpl': '0',
        #                     'liab': '',
        #                     'maxLoan': '',
        #                     'mgnRatio': '104.21819799565878',
        #                     'notionalLever': '2.1322784935455004',
        #                     'ordFrozen': '0',
        #                     'spotInUseAmt': '',
        #                     'stgyEq': '0',
        #                     'twap': '0',
        #                     'uTime': '1663681041633',
        #                     'upl': '-0.0000873608730093'
        #                 },
        assets = {}
        for datas in msg['data']:
            for data in datas['details']:
                total = Decimal(data['eq'])
                free = Decimal(data['availEq'])
                locked = Decimal(data['frozenBal'])
                assets[data['ccy']] = {
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
