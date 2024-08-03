from typing import Callable, Dict, Tuple, Union, Optional, List
import time
from aioquant.configure import config
from aioquant import const
from aioquant.utils import tools
from aioquant.market import Kline,Orderbook,Ticker,Trade
import numpy as np
import pandas as pd
# 显示所有列
pd.set_option('display.max_columns', None)
# 显示所有行
pd.set_option('display.max_rows', None)
# 不换行显示
pd.set_option('display.width', 1000)
# 进行列对齐
pd.set_option('display.unicode.ambiguous_as_wide', True)
pd.set_option('display.unicode.east_asian_width', True)
# 自定义列宽
pd.set_option("display.max_colwidth", 40)
# 不显示科学计数法
pd.set_option("display.float_format", "{:,.2f}".format)
import dolphindb as ddb
import dolphindb.orca as orca
import dolphindb.settings as keys

from .dolphindb_script import (
    CREATE_TABLE_SCRIPT,
    TABLE_CONVERS_SCRIPT,
    INIT_STREAM_SCRIPT,
    SQL_SCRIPT
)

class DolphindbDatabase(object):
    """DolphinDB数据库接口"""

    def __init__(self) -> None:
        """"""
        self.user: str = config.dolphindb["userid"]
        self.password: str = config.dolphindb["password"]
        self.host: str = config.dolphindb["host"]
        self.port: int = config.dolphindb["port"]
        self.db_path: str = config.dolphindb["dfs"]

        # 连接数据库
        self.session = ddb.session()
        self.session.connect(self.host, self.port, self.user, self.password,reconnect=True)
        self.orca = orca.connect(self.host, self.port, self.user, self.password)

        # 创建连接池（run 方法被包装成了协程函数await pool.run("XXXX")）
        self.pool = ddb.DBConnectionPool(self.host, self.port, 1, self.user, self.password,reConnect=True)
        # 初始化流数据表和分布式数据表结构
        self.session.run(CREATE_TABLE_SCRIPT)
        self.session.run(INIT_STREAM_SCRIPT)

    def init(self):
        self.session.run(f"dbHandle = CreateDb('{self.db_path}')")
        self.session.run(f"CreateBarTable(dbHandle,'{self.db_path}','bar')")
        self.session.run(f"CreateKlineTable(dbHandle,'{self.db_path}','kline')")
        self.session.run(f"CreateTickTable(dbHandle,'{self.db_path}','tick')")
        self.session.run(f"CreateTradeTable(dbHandle,'{self.db_path}','trade')")
        self.session.run(f"CreateOrderbookTable(dbHandle,'{self.db_path}','orderbook')")

        # if self.session.existsDatabase(self.db_path):
        #     self.session.dropDatabase(self.db_path)
        # dbExchange = self.session.database(dbName='dbExchange',partitionType=keys.HASH,partitions=[keys.DT_SYMBOL,3],dbPath='')
        # dates = np.array(pd.date_range(start='20100101', end='20231231'), dtype="datetime64[D]")
        # dbTime = self.session.database(dbName='dbTime',partitionType=keys.VALUE,partitions=dates,dbPath='')
        # dbSymbol = self.session.database(dbName='dbSymbol',partitionType=keys.HASH,partitions=[keys.DT_SYMBOL,3000],dbPath='')
        # self.db = self.session.database(dbName='dbHandle',partitionType=keys.COMPO,partitions=[dbExchange, dbTime, dbSymbol],dbPath=self.db_path,engine="TSDB")
        # t = self.session.table(data=df)
        # self.db.createPartitionedTable(table=t, tableName='kline', partitionColumns=['platform','candle_begin_time','symbol'],sortColumns='candle_begin_time').append(t)

    def session(self):
        return self.session

    def orca(self):
        return self.orca

    def pool(self):
        return self.pool

    def save_bar_data(self, bars: List) -> None:
        """保存k线数据"""
        # 转换为DatFrame写入数据库
        data: List[dict] = []

        for bar in bars:
            d = {
                "candle_begin_time": int(bar['timestamp']),
                "open": float(bar['open']),
                "high": float(bar['high']),
                "low": float(bar['low']),
                "close": float(bar['close']),
                "volume": float(bar['volume']),
                "symbol": str(bar['symbol']),
                "kline_type": str(bar['kline_type']),
                "platform": str(bar['platform']),
            }

            data.append(d)

        df: pd.DataFrame = pd.DataFrame.from_records(data)
        df['candle_begin_time'] = pd.to_datetime(df['candle_begin_time'], unit='ms')  # 时间类型转换
        appender = ddb.PartitionedTableAppender(self.db_path, "kline", "candle_begin_time", self.pool)
        appender.append(df)

    def load_bar_data(self, platform, symbol, kline_type, start) -> List:
        """读取K线数据"""
        # 转换时间格式
        start = np.datetime64(start)
        start: str = str(start).replace("-", ".")
        table = self.session.loadTable(tableName="kline", dbPath=self.db_path)
        df: pd.DataFrame = (
            table.select('candle_begin_time,first(open) as open,max(high) as high,min(low) as low,last(close) as close,sum(volume) as volume,symbol,kline_type,platform')
            .where(f'symbol="{symbol}"')
            .where(f'platform="{platform}"')
            .where(f'kline_type="{kline_type}"')
            .where(f'candle_begin_time>={start}')
            .groupby('candle_begin_time')
            .toDF()
        )
        if df.empty:
            return []
        df.set_index("candle_begin_time", inplace=True)

        # 转换为BarData格式
        bars: List = []

        for tp in df.itertuples():
            bar = Kline(
                platform = tp.platform,
                start = str(tp.Index.to_pydatetime()),
                symbol = tp.symbol,
                open = tp.open,
                high = tp.high,
                low = tp.low,
                close = tp.close,
                volume = tp.volume,
                timestamp = str(tp.Index.to_pydatetime()),
                kline_type = tp.kline_type
            )
            bars.append(bar)

        return bars

    def save_tick_data(self, ticks: List) -> None:
        """保存TICK数据"""
        data: List[dict] = []

        for tick in ticks:
            d = {
                "ask": str(tick['ask']),
                "bid": str(tick['bid']),
                "last": str(tick['last']),
                "timestamp": int(tick['timestamp']),
                "symbol": str(tick['symbol']),
                "platform": str(tick['platform']),
            }

            data.append(d)

        df: pd.DataFrame = pd.DataFrame.from_records(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')  # 时间类型转换
        appender = ddb.PartitionedTableAppender(self.db_path, "tick", "timestamp", self.pool)
        appender.append(df)

    def load_tick_data(self, platform, symbol, start) -> List:
        # 转换时间格式
        start = np.datetime64(start)
        start: str = str(start).replace("-", ".")
        table = self.session.loadTable(tableName="tick", dbPath=self.db_path)
        df: pd.DataFrame = (
            table.select('ask, bid, last, timestamp, symbol, platform')
            .where(f'symbol="{symbol}"')
            .where(f'platform="{platform}"')
            .where(f'timestamp>={start}')
            .groupby('timestamp')
            .toDF()
        )
        if df.empty:
            return []
        df.set_index("timestamp", inplace=True)

        # 转换为BarData格式
        ticks: List = []
        for tp in df.itertuples():
            tick = Ticker(
                platform = tp.platform,
                symbol = tp.symbol,
                ask = tp.ask,
                bid = tp.bid,
                last = tp.last,
                timestamp = str(tp.Index.to_pydatetime()),
            )
            ticks.append(tick)

        return ticks

    # def pub_trade_data(self) -> None:
    #     """
    #     通过trade(tick)数据合成K线
    #     VWAP的计算公式：VWAP = (最高价 * 量1 + 最低价 * 量2 + 收盘价 * 量3)/（量1＋量2＋量3） #可以用普通K合成，不考虑
    #     交易量划分K线窗口：交易量每增加10000计算一次K线
    #     通过数据库存获取trade然后发布成流表，从流表合成Bar
    #     """
    #     # 构造表
    #     script = """
    #     // 初始化删除已有流表
    #     try{dropStreamTable(`outTables)}catch(ex){}
    #     // 构造输出流表
    #     bars = database("dfs://aioquant").loadTable("bar")
    #     sch = select name,typeString as type from bars.schema().colDefs
    #     share streamTable(100:0, sch.name,sch.type) as outputTable
    #     // 构造输入表
    #     trades = database("dfs://aioquant").loadTable("trade")
    #     sch = select name,typeString as type from trades.schema().colDefs
    #     // 计算成需要输入内容
    #     //barMinutes = 5
    #     //inputTable = select first(price) as open, max(price) as high, min(price) as low, last(price) as close, sum(volume) as volume from trade group by symbol, date, bar(time, barMinutes*60*1000) as barStart
    #     volThreshold = 10000
    #     inputTable = select first(timestamp) as timestamp, first(timestamp) as start,last(timestamp) as stop,first(price) as open, max(price) as high, min(price) as low, last(price) as close, last(cumvol) as volume, symbol, platform from (select platform, symbol, timestamp, price, cumsum(quantity) as cumvol from trades context by symbol) group by symbol, bar(int(cumvol), volThreshold) as volBar
    #     replay(inputTables=inputTable, outputTables=outputTable, dateColumn=`timestamp, timeColumn=`timestamp)
    #     """
    #     self.session.run(script)   
        

    def save_kline_data(self, platform, symbol, start, volume) -> None:
        """
    #     通过trade(tick)数据合成K线
    #     VWAP的计算公式：VWAP = (最高价 * 量1 + 最低价 * 量2 + 收盘价 * 量3)/（量1＋量2＋量3） #可以用普通K合成，不考虑
    #     交易量划分K线窗口：交易量每增加10000计算一次K线
    #     通过数据库存获取trade然后发布成流表，从流表合成Bar
        """
        table = self.session.loadTable(tableName="trade", dbPath=self.db_path)
        start = np.datetime64(start)
        start: str = str(start).replace("-", ".")
        table1 = (
            table.select('platform, symbol, timestamp, price, int(cumsum(quantity)) as cumvol')
                .where(f'symbol="{symbol}"')
                .where(f'platform="{platform}"')
                .where(f'timestamp>={start}')
                .executeAs("table1")
        )
        table2 = (
            table1.select(f'platform, symbol, timestamp, price, cumvol, bar(cumvol, {volume}) as volBar')
                .where(f'cumvol>{volume}')
                .executeAs("table2")
        )
        table3 = (
            table2.select('first(timestamp) as timestamp, first(timestamp) as start,last(timestamp) as stop,first(price) as open, max(price) as high, min(price) as low, last(price) as close, last(cumvol) as volume, last(symbol) as symbol, last(platform) as platform')
                .groupby(['symbol','volBar'])
                .executeAs("table3")
        )
        df: pd.DataFrame = (
            table3.select('timestamp, start,stop,open, high, low, close, float(volume) as volume, symbol, platform')
                .toDF()
        )

        if df.empty:
            return []

        appender = ddb.PartitionedTableAppender(self.db_path, "bar", "timestamp", self.pool)
        appender.append(df)

    def load_kline_data(self, platform, symbol, start) -> List:
        """读取K线数据"""
        # 转换时间格式
        start = np.datetime64(start)
        start: str = str(start).replace("-", ".")
        table = self.session.loadTable(tableName="bar", dbPath=self.db_path)
        df: pd.DataFrame = (
            table.select('*')
                .where(f'symbol="{symbol}"')
                .where(f'platform="{platform}"')
                .where(f'timestamp>={start}')
                .toDF()
        )
        if df.empty:
            return []
        df.set_index("timestamp", inplace=True)

        # 转换为BarData格式
        bars: List = []

        for tp in df.itertuples():
            bar = {
                "platform": tp.platform,
                "symbol": tp.symbol,
                "start": tp.start,
                "stop": tp.stop,
                "open": tp.open,
                "high": tp.high,
                "low": tp.low,
                "close": tp.close,
                "volume": tp.volume,
                "timestamp": str(tp.Index.to_pydatetime())
            }
            bars.append(bar)

        return bars
    
    def save_trade_data(self, trades: List) -> None:
        """保存TICK数据"""
        data: List[dict] = []

        for trade in trades:
            d = {
                "action": str(trade['action']),
                "id": str(trade['id']),
                "price": float(trade['price']),
                "quantity": float(trade['quantity']),
                "timestamp": int(trade['timestamp']),
                "symbol": str(trade['symbol']),
                "platform": str(trade['platform']),
            }

            data.append(d)

        df: pd.DataFrame = pd.DataFrame.from_records(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')  # 时间类型转换
        appender = ddb.PartitionedTableAppender(self.db_path, "trade", "timestamp", self.pool)
        appender.append(df)
        
    def load_trade_data(self, platform, symbol, start) -> List:
        # 转换时间格式
        start = np.datetime64(start)
        start: str = str(start).replace("-", ".")
        table = self.session.loadTable(tableName="trade", dbPath=self.db_path)
        df: pd.DataFrame = (
            table.select('action, id, price, quantity, timestamp, symbol, platform')
            .where(f'symbol="{symbol}"')
            .where(f'platform="{platform}"')
            .where(f'timestamp>={start}')
            .toDF()
        )
        if df.empty:
            return []
        df.set_index("timestamp", inplace=True)

        # 转换为BarData格式
        trades: List = []
        for tp in df.itertuples():
            trade = Trade(
                platform = tp.platform,
                symbol = tp.symbol,
                action = tp.action,
                price = tp.price,
                quantity = tp.quantity,
                id = tp.id,
                timestamp = str(tp.Index.to_pydatetime()),
            )
            trades.append(trade)

        return trades

    def save_orderbook_data(self, orderbooks: List) -> None:
        """保存TICK数据"""
        data: List[dict] = []

        for orderbook in orderbooks:
            d = {
                "asks": str(orderbook['asks']),
                "bids": str(orderbook['bids']),
                "timestamp": int(orderbook['timestamp']),
                "symbol": str(orderbook['symbol']),
                "platform": str(orderbook['platform']),
            }

            data.append(d)

        df: pd.DataFrame = pd.DataFrame.from_records(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')  # 时间类型转换
        appender = ddb.PartitionedTableAppender(self.db_path, "orderbook", "timestamp", self.pool)
        appender.append(df)

    def load_orderbook_data(self, platform, symbol, start) -> List:
        # 转换时间格式
        start = np.datetime64(start)
        start: str = str(start).replace("-", ".")
        table = self.session.loadTable(tableName="orderbook", dbPath=self.db_path)
        df: pd.DataFrame = (
            table.select('asks, bids, timestamp, symbol, platform')
                .where(f'symbol="{symbol}"')
                .where(f'platform="{platform}"')
                .where(f'timestamp>={start}')
                .groupby('timestamp')
                .toDF()
        )
        if df.empty:
            return []
        df.set_index("timestamp", inplace=True)

        # 转换为BarData格式
        orderbooks: List = []
        for tp in df.itertuples():
            orderbook = Orderbook(
                platform=tp.platform,
                symbol=tp.symbol,
                asks=tp.asks,
                bids=tp.bids,
                timestamp=str(tp.Index.to_pydatetime()),
            )
            orderbooks.append(orderbook)

        return orderbooks
    

class BarGenerator:
    """
    For:
    1. generating 1 minute bar data from tick data
    2. generating x minute bar/x hour bar data from 1 minute data
    Notice:
    1. for x minute bar, x must be able to divide 60: 2, 3, 5, 6, 10, 15, 20, 30
    2. for x hour bar, x can be any number
    回调函数需要理解事件驱动，回调函数调用类再次驱动需要创建相应的类，tick驱动生成bar,再用回调的bar驱动生成分钟bar,再生成小时bar，回调要生成windows_bar
    """

    def __init__(
        self,
        on_event_bar: Callable,
        window: int = 0,
        on_event_window_bar: Callable = None,
        interval = const.MARKET_TYPE_KLINE
    ) -> None:
        """Constructor"""
        self.bar: Kline = None
        self.on_bar: Callable = on_event_bar

        self.interval = interval
        self.interval_count: int = 0

        self.hour_bar: Kline = None

        self.window: int = window
        self.window_bar: Kline = None
        self.on_window_bar: Callable = on_event_window_bar

        self.last_tick: Ticker = None
        self.last_trade: Trade = None

    def update_trade(self, trade: Trade) -> None:
        """
        Update new trade data into generator.
        """
        new_minute: bool = False

        # Filter tick data with 0 last price
        if not trade:
            return

        # Filter tick data with older timestamp
        if self.last_trade and trade.timestamp < self.last_trade.timestamp:
            return

        if not self.bar:
            new_minute = True

        elif tools.ms_to_ms_str(int(self.last_trade.timestamp),"%Y-%m-%dT%H:%M:00.00") != tools.ms_to_ms_str(int(trade.timestamp),"%Y-%m-%dT%H:%M:00.00"):

            self.bar.start = tools.ms_to_ms_str(int(trade.timestamp),"%Y-%m-%dT%H:%M:00.00")
            # 传入参数bar作为默认回调函数的输出
            self.on_bar(self.bar)

            new_minute = True
        if new_minute:
            self.bar = Kline(
                platform=trade.platform,
                start=int(trade.timestamp),
                stop=int(trade.timestamp),
                symbol=trade.symbol,
                open=float(trade.price),
                high=float(trade.price),
                low=float(trade.price),
                close=float(trade.price),
                volume=float(trade.quantity),
                timestamp=trade.timestamp,
                kline_type=0
            )
        else:
            self.bar.start = min(self.bar.start, int(trade.timestamp))
            self.bar.stop = max(self.bar.stop, int(trade.timestamp))
            self.bar.high = max(self.bar.high, float(trade.price))
            self.bar.low = min(self.bar.low, float(trade.price))
            self.bar.close = float(trade.price)
            self.bar.timestamp = trade.timestamp
            self.bar.volume += float(trade.quantity)

        if self.last_trade:
            volume_change = -float(trade.quantity) if trade.action == "SELL" else float(trade.quantity)
            self.bar.kline_type += volume_change

        self.last_trade = trade

    def update_volume(self, tick: Ticker) -> None:
        """
        Update new tick data into generator.
        """
        new_kline: bool = False
        # Filter tick data with 0 last price
        if not tick.last:
            return

        # Filter tick data with older timestamp
        if self.last_tick and tick.timestamp < self.last_tick.timestamp:
            return

        if not self.bar:
            new_kline = True
        elif self.bar.start != self.bar.stop:  # 保证有两条tick才能生成bar,计算的volume才能准确
            self.on_bar(self.bar)

            new_kline = True

        if new_kline:
            self.bar = Kline(
                platform=tick.platform,
                start=int(tick.timestamp),
                stop=int(tick.timestamp),
                symbol=tick.symbol,
                open=float(list(tick.last.keys())[0]),
                high=float(list(tick.last.keys())[0]),
                low=float(list(tick.last.keys())[0]),
                close=float(list(tick.last.keys())[0]),
                volume=float(list(tick.last.values())[0]),
                timestamp=tick.timestamp,
                kline_type=const.MARKET_TYPE_KLINE  # 为了aioquant用,采用默认
            )
        else:
            self.bar.start = min(self.bar.start, int(tick.timestamp))
            self.bar.stop = max(self.bar.stop, int(tick.timestamp))
            self.bar.high = max(self.bar.high, float(list(tick.last.keys())[0]))
            self.bar.low = min(self.bar.low, float(list(tick.last.keys())[0]))
            self.bar.close = float(list(tick.last.keys())[0])
            self.bar.timestamp = tick.timestamp

        if self.last_tick:
            volume_change = float(list(tick.last.values())[0]) - float(list(self.last_tick.last.values())[0])
            self.bar.volume += max(volume_change, 0)

        self.last_tick = tick

    def update_tick(self, tick: Ticker) -> None:
        """
        Update new tick data into generator.
        """
        new_minute: bool = False

        # Filter tick data with 0 last price
        if not tick.last:
            return

        # Filter tick data with older timestamp
        if self.last_tick and tick.timestamp < self.last_tick.timestamp:
            return

        if not self.bar:
            new_minute = True
        # elif (
        #     (self.bar.start != tools.ms_to_ms_str(int(tick.timestamp),"%Y-%m-%dT%H:%M:00.00"))              # bar.star == tick.timestamp 1664699054306 1664699040000 1664697600000
        #     or (self.bar.start != tools.ms_to_ms_str(int(tick.timestamp),"%Y-%m-%dT%H:00:00.00"))           # 需要合成一分种的bar,即每分钟结束时调用回调
        # ):
        elif tools.ms_to_ms_str(int(self.last_tick.timestamp),"%Y-%m-%dT%H:%M:00.00") != tools.ms_to_ms_str(int(tick.timestamp),"%Y-%m-%dT%H:%M:00.00"):

            self.bar.start = tools.ms_to_ms_str(int(tick.timestamp),"%Y-%m-%dT%H:%M:00.00")
            # 传入参数bar作为默认回调函数的输出
            self.on_bar(self.bar)

            new_minute = True
        if new_minute:
            self.bar = Kline(
                platform=tick.platform,
                start=int(tick.timestamp),
                stop=int(tick.timestamp),
                symbol=tick.symbol,
                open=float(list(tick.last.keys())[0]),
                high=float(list(tick.last.keys())[0]),
                low=float(list(tick.last.keys())[0]),
                close=float(list(tick.last.keys())[0]),
                volume=float(list(tick.last.values())[0]),
                timestamp=tick.timestamp,
                kline_type=const.MARKET_TYPE_KLINE
            )
        else:
            self.bar.start = min(self.bar.start, int(tick.timestamp))
            self.bar.stop = max(self.bar.stop, int(tick.timestamp))
            self.bar.high = max(self.bar.high, float(list(tick.last.keys())[0]))
            self.bar.low = min(self.bar.low, float(list(tick.last.keys())[0]))
            self.bar.close = float(list(tick.last.keys())[0])
            self.bar.timestamp = tick.timestamp

        if self.last_tick:
            volume_change = float(list(tick.last.values())[0]) - float(list(self.last_tick.last.values())[0])
            self.bar.volume += max(volume_change, 0)

        self.last_tick = tick

    # 默认回调函数内运行，通过bar驱动(bar可以是其他函数生成)选择对应方法
    def update_bar(self, bar: Kline=None) -> None:
        """
        Update 1 minute bar into generator
        """
        if self.interval == const.MARKET_TYPE_KLINE:
            self.update_bar_minute_window(bar)
        elif self.interval == 'Volume':
            self.update_bar_volume_window(bar)
        elif self.interval == 'Trade':
            self.update_bar_trade_window(bar)
        else:
            self.update_bar_hour_window(bar)

    def update_bar_trade_window(self, bar: Kline) -> None:
        """"""
        # If not inited, create window bar object
        if not self.window_bar:
            self.window_bar = Kline(
                platform=bar.platform,
                start=bar.start,
                stop=bar.stop,
                symbol=bar.symbol,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                timestamp=bar.timestamp,
                kline_type=bar.kline_type
            )
        # Otherwise, update high/low price into window bar
        else:
            self.window_bar.stop = max(
                self.window_bar.stop, bar.stop)
            self.window_bar.start = min(
                self.window_bar.start, bar.start)
            self.window_bar.high = max(
                self.window_bar.high, bar.high)
            self.window_bar.low = min(
                self.window_bar.low, bar.low)

        # Update close price/volume/turnover into window bar
        self.window_bar.close = bar.close
        self.window_bar.volume += bar.volume
        self.window_bar.timestamp = bar.timestamp
        self.window_bar.kline_type += bar.kline_type

        # Check if window bar completed
        if not (time.gmtime().tm_min + 1) % self.window:
            self.on_window_bar(self.window_bar)
            self.window_bar = None

    # 对单根由tick生成的bar合成volume达到100的window_bar
    def update_bar_volume_window(self, bar: Kline) -> None:
        """"""
        # If not inited, create window bar object，
        if not self.window_bar:
            self.window_bar = Kline(
                platform=bar.platform,
                start=bar.start,
                stop=bar.stop,
                symbol=bar.symbol,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                timestamp=bar.timestamp,
                kline_type=const.MARKET_TYPE_KLINE
            )

        # Otherwise only update minute bar
        else:
            self.window_bar.stop = max(
                self.window_bar.stop, bar.stop)
            self.window_bar.start = min(
                self.window_bar.start, bar.start)
            self.window_bar.high = max(
                self.window_bar.high, bar.high)
            self.window_bar.low = min(
                self.window_bar.low, bar.low)

            # Update close price/volume/turnover into window bar
        self.window_bar.close = bar.close
        self.window_bar.volume += bar.volume
        self.window_bar.timestamp = bar.timestamp


        if self.window_bar.volume >= 100 * self.window:
            self.on_window_bar(self.window_bar)
            self.window_bar = None

    # 对1分钟的bar合成X分钟window_bar
    def update_bar_minute_window(self, bar: Kline) -> None:
        """"""
        # If not inited, create window bar object
        if not self.window_bar:
            dt = tools.ms_to_ms_str(int(bar.timestamp),"%Y-%m-%dT%H:%M:00.00")
            self.window_bar = Kline(
                platform=bar.platform,
                start=dt,
                stop=bar.stop,
                symbol=bar.symbol,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                timestamp=bar.timestamp,
                kline_type=const.MARKET_TYPE_KLINE
            )
        # Otherwise, update high/low price into window bar
        else:
            self.window_bar.stop = max(
                self.window_bar.stop, bar.stop)
            self.window_bar.start = min(
                self.window_bar.start, bar.start)
            self.window_bar.high = max(
                self.window_bar.high, bar.high)
            self.window_bar.low = min(
                self.window_bar.low, bar.low)

        # Update close price/volume/turnover into window bar
        self.window_bar.close = bar.close
        self.window_bar.volume += bar.volume
        self.window_bar.timestamp = bar.timestamp

        # Check if window bar completed
        if not (time.gmtime().tm_min + 1) % self.window:
            self.on_window_bar(self.window_bar)
            self.window_bar = None

    # 对1分钟的bar合成1小时hour_bar,如果只需要1小时的直接生成window_bar (后面再判断)
    def update_bar_hour_window(self, bar: Kline) -> None:
        """"""
        # If not inited, create window bar object
        finished_bar: Kline = None
        if not self.hour_bar:
            dt = tools.ms_to_ms_str(int(bar.timestamp), "%Y-%m-%dT%H:00:00.00")
            self.window_bar = Kline(
                platform=bar.platform,
                start=dt,
                stop=bar.stop,
                symbol=bar.symbol,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                timestamp=int(bar.timestamp),
                kline_type=const.MARKET_TYPE_KLINE_1H
            )
            if tools.ms_to_ms_str(int(self.window_bar.timestamp), "%Y-%m-%dT%H::00.00") != tools.ms_to_ms_str(int(bar.timestamp), "%Y-%m-%dT%H:00:00.00"):
                self.on_hour_bar(self.window_bar)

            if not finished_bar:
                dt = tools.ms_to_ms_str(int(bar.timestamp),"%Y-%m-%dT%H:00:00.00")
                self.hour_bar = Kline(
                    platform=bar.platform,
                    start=dt,
                    stop=bar.stop,
                    symbol=bar.symbol,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    timestamp=int(bar.timestamp),
                    kline_type=const.MARKET_TYPE_KLINE_1H
                )

        # If minute is 59, update minute bar into window bar and push
        if time.gmtime().tm_min == 59:
            self.hour_bar.stop = max(
                self.hour_bar.stop, bar.stop)
            self.hour_bar.start = min(
                self.hour_bar.start, bar.start)
            self.hour_bar.high = max(
                self.hour_bar.high, bar.high)
            self.hour_bar.low = min(
                self.hour_bar.low, bar.low)

            self.hour_bar.close = bar.close
            self.hour_bar.volume += bar.volume
            self.hour_bar.timestamp = int(bar.timestamp)

            finished_bar = self.hour_bar
            self.hour_bar = None

        # If minute bar of new hour, then push existing window bar
        elif tools.ms_to_ms_str(int(self.hour_bar.timestamp),"%Y-%m-%dT%H:00:00.00") != tools.ms_to_ms_str(int(bar.timestamp),"%Y-%m-%dT%H:00:00.00"):
            finished_bar = self.hour_bar
            self.hour_bar = None
        # Otherwise only update minute bar
        else:
            self.hour_bar.stop = max(
                self.hour_bar.stop, bar.stop)
            self.hour_bar.start = min(
                self.hour_bar.start, bar.start)
            self.hour_bar.high = max(
                self.hour_bar.high, bar.high)
            self.hour_bar.low = min(
                self.hour_bar.low, bar.low)

            self.hour_bar.close = bar.close
            self.hour_bar.volume += bar.volume
            self.hour_bar.timestamp = bar.timestamp

        # Push finished window bar
        if finished_bar:
            # 这里不是调用回调而是调用类方法，判断回调间隔windows
            self.on_hour_bar(finished_bar)

    # 对合成的1小时hour_bar,判断回调间隔windows
    def on_hour_bar(self, bar: Kline) -> None:
        """"""
        if self.window == 1:
            self.on_window_bar(bar)
        else:
            if not self.window_bar:
                self.window_bar = Kline(
                    platform=bar.platform,
                    start=bar.start,
                    stop=bar.stop,
                    symbol=bar.symbol,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    timestamp=bar.timestamp,
                    kline_type=const.MARKET_TYPE_KLINE_1H
                )
            else:
                self.window_bar.stop = max(
                    self.window_bar.stop, bar.stop)
                self.window_bar.start = min(
                    self.window_bar.start, bar.start)
                self.window_bar.high = max(
                    self.window_bar.high, bar.high)
                self.window_bar.low = min(
                    self.window_bar.low, bar.low)

            self.window_bar.close = bar.close
            self.window_bar.volume += bar.volume
            self.window_bar.timestamp = bar.timestamp

            self.interval_count += 1
            if not self.interval_count % self.window:
                self.interval_count = 0
                self.on_window_bar(self.window_bar)
                self.window_bar = None

    def generate(self):
        """
        Generate the bar data and call callback immediately.
        """
        bar: Kline = self.bar

        if self.bar:
            bar.start = tools.ms_to_ms_str(int(self.bar.timestamp),"%Y-%m-%dT%H:%M:00.00")
            self.on_bar(bar)

        self.bar = None
        return bar

class ArrayManager(object):
    """
    For:
    1. time series container of bar data
    2. calculating technical indicator value
    """

    def __init__(self, size=100):
        """Constructor"""
        self.count = 0
        self.size = size
        self.inited = False

        self.open_array = np.zeros(size)
        self.high_array = np.zeros(size)
        self.low_array = np.zeros(size)
        self.close_array = np.zeros(size)
        self.volume_array = np.zeros(size)

    def update_bar(self, bar: Kline):
        """
        Update new bar data into array manager.
        """
        self.count += 1
        if not self.inited and self.count >= self.size:
            self.inited = True

        self.open_array[:-1] = self.open_array[1:]
        self.high_array[:-1] = self.high_array[1:]
        self.low_array[:-1] = self.low_array[1:]
        self.close_array[:-1] = self.close_array[1:]
        self.volume_array[:-1] = self.volume_array[1:]

        self.open_array[-1] = bar.open
        self.high_array[-1] = bar.high
        self.low_array[-1] = bar.low
        self.close_array[-1] = bar.close
        self.volume_array[-1] = bar.volume

    @property
    def open(self):
        """
        Get open price time series.
        """
        return self.open_array

    @property
    def high(self):
        """
        Get high price time series.
        """
        return self.high_array

    @property
    def low(self):
        """
        Get low price time series.
        """
        return self.low_array

    @property
    def close(self):
        """
        Get close price time series.
        """
        return self.close_array

    @property
    def volume(self):
        """
        Get trading volume time series.
        """
        return self.volume_array

    def vwap(self, array=False):
        """
        VWAP.
        """
        VWAP = (self.volume * (self.high + self.low) / 2).cumsum() / self.volume.cumsum()
        if array:
            return VWAP
        return VWAP[-1]

    def sma(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        Simple moving average.
        """
        result: np.ndarray = talib.SMA(self.close, n)
        if array:
            return result
        return result[-1]

    def ema(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        Exponential moving average.
        """
        result: np.ndarray = talib.EMA(self.close, n)
        if array:
            return result
        return result[-1]

    def kama(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        KAMA.
        """
        result: np.ndarray = talib.KAMA(self.close, n)
        if array:
            return result
        return result[-1]

    def wma(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        WMA.
        """
        result: np.ndarray = talib.WMA(self.close, n)
        if array:
            return result
        return result[-1]

    def apo(
        self,
        fast_period: int,
        slow_period: int,
        matype: int = 0,
        array: bool = False
    ) -> Union[float, np.ndarray]:
        """
        APO.
        """
        result: np.ndarray = talib.APO(self.close, fast_period, slow_period, matype)
        if array:
            return result
        return result[-1]

    def cmo(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        CMO.
        """
        result: np.ndarray = talib.CMO(self.close, n)
        if array:
            return result
        return result[-1]

    def mom(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        MOM.
        """
        result: np.ndarray = talib.MOM(self.close, n)
        if array:
            return result
        return result[-1]

    def ppo(
        self,
        fast_period: int,
        slow_period: int,
        matype: int = 0,
        array: bool = False
    ) -> Union[float, np.ndarray]:
        """
        PPO.
        """
        result: np.ndarray = talib.PPO(self.close, fast_period, slow_period, matype)
        if array:
            return result
        return result[-1]

    def roc(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        ROC.
        """
        result: np.ndarray = talib.ROC(self.close, n)
        if array:
            return result
        return result[-1]

    def rocr(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        ROCR.
        """
        result: np.ndarray = talib.ROCR(self.close, n)
        if array:
            return result
        return result[-1]

    def rocp(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        ROCP.
        """
        result: np.ndarray = talib.ROCP(self.close, n)
        if array:
            return result
        return result[-1]

    def rocr_100(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        ROCR100.
        """
        result: np.ndarray = talib.ROCR100(self.close, n)
        if array:
            return result
        return result[-1]

    def trix(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        TRIX.
        """
        result: np.ndarray = talib.TRIX(self.close, n)
        if array:
            return result
        return result[-1]

    def std(self, n: int, nbdev: int = 1, array: bool = False) -> Union[float, np.ndarray]:
        """
        Standard deviation.
        """
        result: np.ndarray = talib.STDDEV(self.close, n, nbdev)
        if array:
            return result
        return result[-1]

    def obv(self, array: bool = False) -> Union[float, np.ndarray]:
        """
        OBV.
        """
        result: np.ndarray = talib.OBV(self.close, self.volume)
        if array:
            return result
        return result[-1]

    def cci(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        Commodity Channel Index (CCI).
        """
        result: np.ndarray = talib.CCI(self.high, self.low, self.close, n)
        if array:
            return result
        return result[-1]

    def atr(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        Average True Range (ATR).
        """
        result: np.ndarray = talib.ATR(self.high, self.low, self.close, n)
        if array:
            return result
        return result[-1]

    def natr(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        NATR.
        """
        result: np.ndarray = talib.NATR(self.high, self.low, self.close, n)
        if array:
            return result
        return result[-1]

    def rsi(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        Relative Strenght Index (RSI).
        """
        result: np.ndarray = talib.RSI(self.close, n)
        if array:
            return result
        return result[-1]

    def macd(
        self,
        fast_period: int,
        slow_period: int,
        signal_period: int,
        array: bool = False
    ) -> Union[
        Tuple[np.ndarray, np.ndarray, np.ndarray],
        Tuple[float, float, float]
    ]:
        """
        MACD.
        """
        macd, signal, hist = talib.MACD(
            self.close, fast_period, slow_period, signal_period
        )
        if array:
            return macd, signal, hist
        return macd[-1], signal[-1], hist[-1]

    def adx(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        ADX.
        """
        result: np.ndarray = talib.ADX(self.high, self.low, self.close, n)
        if array:
            return result
        return result[-1]

    def adxr(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        ADXR.
        """
        result: np.ndarray = talib.ADXR(self.high, self.low, self.close, n)
        if array:
            return result
        return result[-1]

    def dx(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        DX.
        """
        result: np.ndarray = talib.DX(self.high, self.low, self.close, n)
        if array:
            return result
        return result[-1]

    def minus_di(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        MINUS_DI.
        """
        result: np.ndarray = talib.MINUS_DI(self.high, self.low, self.close, n)
        if array:
            return result
        return result[-1]

    def plus_di(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        PLUS_DI.
        """
        result: np.ndarray = talib.PLUS_DI(self.high, self.low, self.close, n)
        if array:
            return result
        return result[-1]

    def willr(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        WILLR.
        """
        result: np.ndarray = talib.WILLR(self.high, self.low, self.close, n)
        if array:
            return result
        return result[-1]

    def ultosc(
        self,
        time_period1: int = 7,
        time_period2: int = 14,
        time_period3: int = 28,
        array: bool = False
    ) -> Union[float, np.ndarray]:
        """
        Ultimate Oscillator.
        """
        result: np.ndarray = talib.ULTOSC(self.high, self.low, self.close, time_period1, time_period2, time_period3)
        if array:
            return result
        return result[-1]

    def trange(self, array: bool = False) -> Union[float, np.ndarray]:
        """
        TRANGE.
        """
        result: np.ndarray = talib.TRANGE(self.high, self.low, self.close)
        if array:
            return result
        return result[-1]

    def boll(
        self,
        n: int,
        dev: float,
        array: bool = False
    ) -> Union[
        Tuple[np.ndarray, np.ndarray],
        Tuple[float, float]
    ]:
        """
        Bollinger Channel.
        """
        mid: Union[float, np.ndarray] = self.sma(n, array)
        std: Union[float, np.ndarray] = self.std(n, 1, array)

        up: Union[float, np.ndarray] = mid + std * dev
        down: Union[float, np.ndarray] = mid - std * dev

        return up, down

    def keltner(
        self,
        n: int,
        dev: float,
        array: bool = False
    ) -> Union[
        Tuple[np.ndarray, np.ndarray],
        Tuple[float, float]
    ]:
        """
        Keltner Channel.
        """
        mid: Union[float, np.ndarray] = self.sma(n, array)
        atr: Union[float, np.ndarray] = self.atr(n, array)

        up: Union[float, np.ndarray] = mid + atr * dev
        down: Union[float, np.ndarray] = mid - atr * dev

        return up, down

    def donchian(
        self, n: int, array: bool = False
    ) -> Union[
        Tuple[np.ndarray, np.ndarray],
        Tuple[float, float]
    ]:
        """
        Donchian Channel.
        """
        up: np.ndarray = talib.MAX(self.high, n)
        down: np.ndarray = talib.MIN(self.low, n)

        if array:
            return up, down
        return up[-1], down[-1]

    def aroon(
        self,
        n: int,
        array: bool = False
    ) -> Union[
        Tuple[np.ndarray, np.ndarray],
        Tuple[float, float]
    ]:
        """
        Aroon indicator.
        """
        aroon_down, aroon_up = talib.AROON(self.high, self.low, n)

        if array:
            return aroon_up, aroon_down
        return aroon_up[-1], aroon_down[-1]

    def aroonosc(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        Aroon Oscillator.
        """
        result: np.ndarray = talib.AROONOSC(self.high, self.low, n)

        if array:
            return result
        return result[-1]

    def minus_dm(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        MINUS_DM.
        """
        result: np.ndarray = talib.MINUS_DM(self.high, self.low, n)

        if array:
            return result
        return result[-1]

    def plus_dm(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        PLUS_DM.
        """
        result: np.ndarray = talib.PLUS_DM(self.high, self.low, n)

        if array:
            return result
        return result[-1]

    def mfi(self, n: int, array: bool = False) -> Union[float, np.ndarray]:
        """
        Money Flow Index.
        """
        result: np.ndarray = talib.MFI(self.high, self.low, self.close, self.volume, n)
        if array:
            return result
        return result[-1]

    def ad(self, array: bool = False) -> Union[float, np.ndarray]:
        """
        AD.
        """
        result: np.ndarray = talib.AD(self.high, self.low, self.close, self.volume)
        if array:
            return result
        return result[-1]

    def adosc(
        self,
        fast_period: int,
        slow_period: int,
        array: bool = False
    ) -> Union[float, np.ndarray]:
        """
        ADOSC.
        """
        result: np.ndarray = talib.ADOSC(self.high, self.low, self.close, self.volume, fast_period, slow_period)
        if array:
            return result
        return result[-1]

    def bop(self, array: bool = False) -> Union[float, np.ndarray]:
        """
        BOP.
        """
        result: np.ndarray = talib.BOP(self.open, self.high, self.low, self.close)

        if array:
            return result
        return result[-1]

    def stoch(
        self,
        fastk_period: int,
        slowk_period: int,
        slowk_matype: int,
        slowd_period: int,
        slowd_matype: int,
        array: bool = False
    ) -> Union[
        Tuple[float, float],
        Tuple[np.ndarray, np.ndarray]
    ]:
        """
        Stochastic Indicator
        """
        k, d = talib.STOCH(
            self.high,
            self.low,
            self.close,
            fastk_period,
            slowk_period,
            slowk_matype,
            slowd_period,
            slowd_matype
        )
        if array:
            return k, d
        return k[-1], d[-1]

