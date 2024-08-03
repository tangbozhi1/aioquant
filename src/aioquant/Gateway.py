# -*- coding:utf-8 -*-

"""
Trade Module.

Author: HuangTao
Date:   2019/04/21
Email:  huangtao@ifclover.com
"""

import copy
import json
from aioquant.configure import config
from aioquant import const
from aioquant.utils import tools
from aioquant.error import Error
from aioquant.utils import logger
from aioquant.tasks import SingleTask
from aioquant.order import Order
from aioquant.position import Position
from aioquant.asset import Asset
from aioquant.fill import Fill
from aioquant.market import Orderbook, Kline, Trade, Ticker


class ExchangeGateway:
    """Trade Module.

    Attributes:
        order,fill,position object have strategy
        strategy: What's name would you want to created for your strategy.
        platform: Exchange platform name. e.g. `binance` / `okex` / `bitmex`.
        symbol: Symbol name for your trade. e.g. `BTC/USDT`.
        host: HTTP request host.
        wss: Websocket address.
        account: Account name for this trade exchange.
        access_key: Account's ACCESS KEY.
        secret_key: Account's SECRET KEY.
        passphrase: API KEY Passphrase. (Only for `OKEx`)
        order_update_callback: You can use this param to specify a async callback function when you initializing Trade
            module. `order_update_callback` is like `async def on_order_update_callback(order: Order): pass` and this
            callback function will be executed asynchronous when some order state updated.
        position_update_callback: You can use this param to specify a async callback function when you initializing
            Trade module. `position_update_callback` is like `async def on_position_update_callback(position: Position): pass`
            and this callback function will be executed asynchronous when position updated.
        init_callback: You can use this param to specify a async callback function when you initializing Trade
            module. `init_callback` is like `async def on_init_callback(success: bool, **kwargs): pass`
            and this callback function will be executed asynchronous after Trade module object initialized done.
        error_callback: You can use this param to specify a async callback function when you initializing Trade
            module. `error_callback` is like `async def on_error_callback(error: Error, **kwargs): pass`
            and this callback function will be executed asynchronous when some error occur while trade module is running.
    """

    def __init__(self, strategy=None, platform=None, symbol=None, raw_symbol=None, host=None, wss=None, account=None, access_key=None,
                 secret_key=None, passphrase=None, order_update_callback=None, fill_update_callback=None, position_update_callback=None,
                 asset_update_callback=None, init_callback=None, error_callback=None, **kwargs):
        """Initialize trade object."""
        kwargs["strategy"] = strategy
        kwargs["platform"] = platform
        kwargs["symbol"] = symbol
        kwargs["raw_symbol"] = raw_symbol
        kwargs["host"] = host
        kwargs["wss"] = wss
        kwargs["account"] = account
        kwargs["access_key"] = access_key
        kwargs["secret_key"] = secret_key
        kwargs["passphrase"] = passphrase
        kwargs["fill_update_callback"] = fill_update_callback
        kwargs["order_update_callback"] = order_update_callback
        kwargs["position_update_callback"] = position_update_callback
        kwargs["asset_update_callback"] = asset_update_callback
        kwargs["init_callback"] = self._on_init_callback
        kwargs["error_callback"] = self._on_error_callback

        self._raw_params = copy.copy(kwargs)
        self._fill_update_callback = fill_update_callback
        self._order_update_callback = order_update_callback
        self._position_update_callback = position_update_callback
        self._asset_update_callback = asset_update_callback
        self._init_callback = init_callback
        self._error_callback = error_callback

        if platform == const.BINANCE:
            from aioquant.platform.binance import BinanceTrade as T
        elif platform == const.BINANCE_FUTURES:
            from aioquant.platform.binance_futures import BinanceTrade as T
        elif platform == const.BINANCE_DELIVERY:
            from aioquant.platform.binance_delivery import BinanceTrade as T
        elif platform == const.OKX:
            from aioquant.platform.okex import OKExTrade as T
        elif platform == const.FTX:
            from aioquant.platform.ftx import FtxTrade as T
        else:
            logger.error("platform error:", platform, caller=self)
            e = Error("platform error")
            SingleTask.run(self._on_error_callback, e)
            SingleTask.run(self._on_init_callback, False)
            return
        self._t = T(**kwargs)

    @property
    def assets(self):
        return self._t.assets

    @property
    def orders(self):
        return self._t.orders

    # @property
    # def position(self):
    #     return self._t.position  # only for contract trading.

    # @property
    # def fills(self):
    #     return self._t.fills

    @property
    def symbols(self):
        return self._t.symbols

    @property
    def rest_api(self):
        return self._t.rest_api

    def std_channel_to_raw_channel(self, channel: str) -> str:
        try:
            return self.websocket_channels[channel]
        except KeyError:
            raise ValueError(f'{channel} is not supported')

    def raw_channel_to_std_channel(self, channel: str) -> str:
        for chan, exch in self.websocket_channels.items():
            if exch == channel:
                return chan
        raise ValueError(f'Unable to normalize channel')

    def std_symbol_to_raw_symbol(self, symbol) -> str:
        try:
            return self.symbols[symbol].raw_symbol
        except KeyError:
            raise ValueError(f'{symbol} is not supported')

    def raw_symbol_to_std_symbol(self, symbol: str) -> str:
        for sym, info in self.symbols.items():
            if info.raw_symbol == symbol:
                return sym
        raise ValueError(f'{symbol} is not supported')

    async def create_order(self, action, price, quantity, *args, **kwargs) -> (str, Error):
        """Create an order.

        Args:
            action: Trade direction, `BUY` or `SELL`.
            price: Price of each order/contract.
            quantity: The buying or selling quantity.
            kwargs：
                order_type: Specific type of order, `LIMIT` or `MARKET`. (default is `LIMIT`)
                client_order_id: Client order id, default `None` will be replaced by a random uuid string.
                trade_type: 自定义字段，通过插入client id 下单时间接实现标记
                            # TRADE_TYPE_BUY_OPEN = 1  # 1 做多, action = BUY & quantity > 0.
                            # TRADE_TYPE_SELL_OPEN = 2  # 2 做空, action = SELL & quantity < 0.
                            # TRADE_TYPE_SELL_CLOSE = 3  # 3 有多单时平多 , action = SELL & quantity > 0.
                            # TRADE_TYPE_BUY_CLOSE = 4  # 4 有空单时平空, action = BUY & quantity < 0.

        Returns:
            order_id: Order id if created successfully, otherwise it's None.
            error: Error information, otherwise it's None.
        """
        # price = tools.float_to_str(price)
        # quantity = tools.float_to_str(quantity)
        if not kwargs.get("client_order_id"):
            kwargs["client_order_id"] = tools.get_uuid1().replace("-", "")
        order_id, error = await self._t.create_order(action, price, quantity, *args, **kwargs)
        return order_id, error

    async def edit_order(self, *args, **kwargs):
        """edit an order.

        Args:
            price: Price of each order/contract.
            quantity: The buying or selling remain quantity.

        Returns:
            order_id: Order id if edited successfully, otherwise it's None.
            error: Error information, otherwise it's None.
        """
        success, error = await self._t.edit_order(*args, **kwargs)
        return success, error

    async def revoke_order(self, *order_ids):
        """Revoke (an) order(s).

        Args:
            order_ids: Order id list, you can set this param to 0 or multiple items. If you set 0 param, you can cancel
                all orders for this symbol(initialized in Trade object). If you set 1 param, you can cancel an order.
                If you set multiple param, you can cancel multiple orders. Do not set param length more than 100.

        Returns:
            success: If execute successfully, return success information, otherwise it's None.
            error: If execute failed, return error information, otherwise it's None.
        """
        success, error = await self._t.revoke_order(*order_ids)
        return success, error

    async def get_open_order_ids(self) -> (list, Error):
        """Get open order id list.

        Args:
            None.

        Returns:
            order_ids: Open order id list, otherwise it's None.
            error: Error information, otherwise it's None.
        """
        order_ids, error = await self._t.get_open_order_ids()
        return order_ids, error

    async def _on_fill_update_callback(self, fill: Fill) -> None:
        """Order information update callback.

        Args:
            order: Order object.
        """
        if not self._fill_update_callback:
            return
        await self._fill_update_callback(fill)  # 这里有点难理解
        from aioquant.event import EventFill
        EventFill(fill).publish()

    async def _on_order_update_callback(self, order: Order) -> None:
        """Order information update callback.

        Args:
            order: Order object.
        """
        if not self._order_update_callback:
            return
        await self._order_update_callback(order)  # 这里有点难理解
        from aioquant.event import EventOrder
        EventOrder(order).publish()

    async def _on_position_update_callback(self, position: Position) -> None:
        """Position information update callback.

        Args:
            position: Position object.
        """
        if not self._position_update_callback:
            return
        await self._position_update_callback(position)
        from aioquant.event import EventPosition
        EventPosition(position).publish()

    async def _on_asset_update_callback(self, asset: Asset) -> None:
        """Order information update callback.

        Args:
            order: Order object.
        """
        if not self._asset_update_callback:
            return
        await self._asset_update_callback(asset)
        from aioquant.event import EventAsset
        EventAsset(asset).publish()

    async def _on_init_callback(self, success: bool) -> None:
        """Callback function when initialize Trade module finished.

        Args:
            success: `True` if initialize Trade module success, otherwise `False`.
        """
        if not self._init_callback:
            return
        params = {
            "strategy": self._raw_params["strategy"],
            "platform": self._raw_params["platform"],
            "symbol": self._raw_params["symbol"],
            "account": self._raw_params["account"]
        }
        await self._init_callback(success, **params)

    async def _on_error_callback(self, error: Error) -> None:
        """Callback function when some error occur while Trade module is running.

        Args:
            error: Error information.
        """
        if not self._error_callback:
            return
        params = {
            "strategy": self._raw_params["strategy"],
            "platform": self._raw_params["platform"],
            "symbol": self._raw_params["symbol"],
            "account": self._raw_params["account"]
        }
        await self._error_callback(error, **params)


class ExchangeWebsocket:
    """Market Module.

    Attributes:
        order,fill,position object have not strategy
        platform: Exchange platform name. e.g. `binance` / `okex` / `bitmex`.
        host: HTTP request host.
        wss: Websocket address.
        account: Account name for this trade exchange.
        access_key: Account's ACCESS KEY.
        secret_key: Account's SECRET KEY.
        passphrase: API KEY Passphrase. (Only for `OKEx`)
        order_update_callback: You can use this param to specify a async callback function when you initializing Trade
            module. `order_update_callback` is like `async def on_order_update_callback(order: Order): pass` and this
            callback function will be executed asynchronous when some order state updated.
        position_update_callback: You can use this param to specify a async callback function when you initializing
            Trade module. `position_update_callback` is like `async def on_position_update_callback(position: Position): pass`
            and this callback function will be executed asynchronous when position updated.
        init_callback: You can use this param to specify a async callback function when you initializing Trade
            module. `init_callback` is like `async def on_init_callback(success: bool, **kwargs): pass`
            and this callback function will be executed asynchronous after Trade module object initialized done.
        error_callback: You can use this param to specify a async callback function when you initializing Trade
            module. `error_callback` is like `async def on_error_callback(error: Error, **kwargs): pass`
            and this callback function will be executed asynchronous when some error occur while trade module is running.
    """

    def __init__(self, platform=None, host=None, wss=None, account=None, access_key=None, secret_key=None, passphrase=None, order_update_callback=None, fill_update_callback=None, position_update_callback=None, asset_update_callback=None, orderbook_update_callback=None, kline_update_callback=None, trade_update_callback=None, ticker_update_callback=None, init_callback=None, error_callback=None, **kwargs):
        """Initialize trade object."""
        kwargs["platform"] = platform
        kwargs["host"] = host
        kwargs["wss"] = wss
        kwargs["account"] = account
        kwargs["access_key"] = access_key
        kwargs["secret_key"] = secret_key
        kwargs["passphrase"] = passphrase
        kwargs["fill_update_callback"] = fill_update_callback
        kwargs["order_update_callback"] = order_update_callback
        kwargs["position_update_callback"] = position_update_callback
        kwargs["asset_update_callback"] = asset_update_callback
        kwargs["kline_update_callback"] = kline_update_callback
        kwargs["orderbook_update_callback"] = orderbook_update_callback
        kwargs["trade_update_callback"] = trade_update_callback
        kwargs["ticker_update_callback"] = ticker_update_callback
        kwargs["init_callback"] = self._on_init_callback
        kwargs["error_callback"] = self._on_error_callback

        self._raw_params = copy.copy(kwargs)
        self._fill_update_callback = fill_update_callback
        self._order_update_callback = order_update_callback
        self._position_update_callback = position_update_callback
        self._asset_update_callback = asset_update_callback
        self._kline_update_callback = kline_update_callback
        self._orderbook_update_callback = orderbook_update_callback
        self._trade_update_callback = trade_update_callback
        self._ticker_update_callback = ticker_update_callback
        self._init_callback = init_callback
        self._error_callback = error_callback


        if platform == const.BINANCE:
            from aioquant.platform.binance import BinanceMarket as M
        elif platform == const.BINANCE_FUTURES:
            from aioquant.platform.binance_futures import BinanceMarket as M
        elif platform == const.BINANCE_DELIVERY:
            from aioquant.platform.binance_delivery import BinanceMarket as M
        elif platform == const.OKX:
            from aioquant.platform.okex import OKExMarket as M
        elif platform == const.FTX:
            from aioquant.platform.ftx import FtxMarket as M
        else:
            logger.error("platform error:", platform, caller=self)
            e = Error("platform error")
            SingleTask.run(self._on_error_callback, e)
            SingleTask.run(self._on_init_callback, False)
            return
        self._m = M(**kwargs)


    @property
    def assets(self):
        return self._m.assets

    @property
    def orders(self):
        return self._m.orders

    # @property
    # def position(self):
    #     return self._m.position  # only for contract trading.

    # @property
    # def fills(self):
    #     return self._m.fills

    @property
    def symbols(self):
        return self._m.symbols

    @property
    def orderbooks(self):
        return self._m.orderbooks

    # @property
    # def klines(self):
    #     return self._m.klines
    #
    # @property
    # def trades(self):
    #     return self._m.trades
    #
    # @property
    # def tickers(self):
    #     return self._m.tickers

    @property
    def rest_api(self):
        return self._m.rest_api

    def std_channel_to_raw_channel(self, channel: str) -> str:
        try:
            return self.websocket_channels[channel]
        except KeyError:
            raise ValueError(f'{channel} is not supported')

    def raw_channel_to_std_channel(self, channel: str) -> str:
        for chan, exch in self.websocket_channels.items():
            if exch == channel:
                return chan
        raise ValueError(f'Unable to normalize channel')

    def std_symbol_to_raw_symbol(self, symbol) -> str:
        try:
            return self.symbols[symbol].raw_symbol
        except KeyError:
            raise ValueError(f'{symbol} is not supported')

    def raw_symbol_to_std_symbol(self, symbol: str) -> str:
        for sym, info in self.symbols.items():
            if info.raw_symbol == symbol:
                return sym
        raise ValueError(f'{symbol} is not supported')

    async def _on_fill_update_callback(self, fill: Fill) -> None:
        """Order information update callback.

        Args:
            order: Order object.
            第一次通过子类调用_on_fill_update_callback,此时_fill_update_callback为类方法
            运行到._fill_update_callback(fill)实例第二次调用_on_fill_update_callback(此时_fill_update_callback为主程序on_event_fill_update函数,为None)
            跳出await self._fill_update_callback(fill)运行后序EventFill，即仍然向RabbitMQ发布
        """
        if not self._fill_update_callback:
            return
        await self._fill_update_callback(fill)  # 这里有点难理解
        from aioquant.event import EventFill
        EventFill(fill).publish()

    async def _on_order_update_callback(self, order: Order) -> None:
        """Order information update callback.

        Args:
            order: Order object.
        """
        if not self._order_update_callback:
            return
        await self._order_update_callback(order)  # 这里有点难理解
        from aioquant.event import EventOrder
        EventOrder(order).publish()

    async def _on_position_update_callback(self, position: Position) -> None:
        """Position information update callback.

        Args:
            position: Position object.
        """
        if not self._position_update_callback:
            return
        await self._position_update_callback(position)
        from aioquant.event import EventPosition
        EventPosition(position).publish()

    async def _on_asset_update_callback(self, asset: Asset) -> None:
        """Order information update callback.

        Args:
            order: Order object.
        """
        if not self._asset_update_callback:
            return
        await self._asset_update_callback(asset)
        from aioquant.event import EventAsset
        EventAsset(asset).publish()

    async def _on_orderbook_update_callback(self, orderbook: Orderbook) -> None:
        """orderbook information update callback.

        Args:
            orderbook: Orderbook object.
        """
        if not self._orderbook_update_callback:
            return
        await self._orderbook_update_callback(orderbook)
        # from aioquant.event import EventOrderbook
        # EventOrderbook(orderbook).publish()

    async def _on_kline_update_callback(self, kline: Kline) -> None:
        """kline information update callback.

        Args:
            kline: Kline object.
        """
        if not self._kline_update_callback:
            return
        await self._kline_update_callback(kline)
        # from aioquant.event import EventKline
        # EventKline(kline).publish()

    async def _on_trade_update_callback(self, trade: Trade) -> None:
        """Trade information update callback.

        Args:
            trade: Trade object.
        """
        if not self._trade_update_callback:
            return
        await self._trade_update_callback(trade)
        # from aioquant.event import EventTrade
        # EventTrade(trade).publish()

    async def _on_ticker_update_callback(self, ticker: Ticker) -> None:
        """Ticker information update callback.

        Args:
            ticker: Ticker object.
        """
        if not self._ticker_update_callback:
            return
        await self._ticker_update_callback(ticker)
        # from aioquant.event import EventTicker
        # EventTicker(ticker).publish()

    async def _on_init_callback(self, success: bool) -> None:
        """Callback function when initialize Trade module finished.

        Args:
            success: `True` if initialize Trade module success, otherwise `False`.
        """
        if not self._init_callback:
            return
        params = {
            "platform": self._raw_params["platform"],
            "account": self._raw_params["account"]
        }
        await self._init_callback(success, **params)

    async def _on_error_callback(self, error: Error) -> None:
        """Callback function when some error occur while Trade module is running.

        Args:
            error: Error information.
        """
        if not self._error_callback:
            return
        params = {
            "platform": self._raw_params["platform"],
            "account": self._raw_params["account"]
        }
        await self._error_callback(error, **params)
