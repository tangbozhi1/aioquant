# -*- coding:utf-8 -*-
# 封装的RestAPI(CCXT获取K线，订单、仓位、余额)
# 以及资金划转，大单拆分，费率等额外数据获取
import asyncio
from aioretry import retry
from aioquant.utils.decorator import retry_policy,async_method_locker
import time
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

# 获取资产
@retry(retry_policy)
async def fetch_balance(exchange):
    balance = await exchange.fetch_balance()
    return _process_asset(balance)

# 获取当前资金费率
@retry(retry_policy)
async def fetch_fundingrate(exchange, symbol):
    fundingrate = await exchange.fetch_funding_rate(symbol)
    return _process_fundingrate(fundingrate)

# 获取ticker数据
@async_method_locker("fetch_ticker.locker")
@retry(retry_policy)
async def fetch_ticker(exchange, symbol):
    tickers = await exchange.fetch_ticker(symbol)
    return _process_ticker(tickers)

# 获取实际持仓
@retry(retry_policy)
async def fetch_position(exchange, symbol):
    position_risk = await exchange.fetch_positions([symbol])
    return _process_position(position_risk)

# 获取订单
@retry(retry_policy)
async def fetch_order(exchange, id, symbol):
    order = await exchange.fetch_order(id, symbol)
    return _process_order(order)


# 获取持仓利息
@retry(retry_policy)
async def fetch_interest_history(exchange, symbol, start_time_dt, interval='1h', limit=100):
    # 13位
    start_time_t = int(time.mktime(start_time_dt.timetuple())) * 1000
    interest = await exchange.fetch_open_interest_history(symbol, timeframe=interval, since=start_time_t, limit=limit)
    return _process_interest(interest)   # okx的ccxt代码有bug

def _process_asset(info):
    assets = {}
    total = dict(info['total'])
    free = dict(info['free'])
    locked = dict(info['used'])
    for ccy in total:
        assets[ccy] = {
            "total": "%.8f" % total[ccy],
            "free": "%.8f" % free[ccy],
            "locked": "%.8f" % locked[ccy],
            "timestamp": int(time.time() * 1000),
        }

    # 整理数据
    df = pd.DataFrame(assets, dtype='float').T
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def _process_position(info):
    position_risk = pd.DataFrame.from_records(info)
    # 整理数据
    position_risk.rename(columns={'contracts': '当前持仓量'}, inplace=True)
    position_risk = position_risk[position_risk['当前持仓量'] != 0]  # 只保留有仓位的币种
    position_risk['timestamp'] = pd.to_datetime(position_risk['timestamp'], unit='ms')
    position_risk.set_index('symbol', inplace=True)  # 将symbol设置为index
    return position_risk

def _process_order(info):
    df = pd.DataFrame([info['id'],info['clientOrderId'],info['symbol'],info['timestamp'],info['side'],info['status'],"%.8f" % info['price'],"%.8f" % info['amount']]).T
    df.columns=['id', 'clientOrderId', 'symbol', 'timestamp', 'side', 'status', 'price', 'amount']
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def _process_ticker(info):
    df = pd.DataFrame([info['symbol'],info['timestamp'],"%.8f" % info['last'],"%.8f" % info['close']]).T
    df.columns=['symbol', 'timestamp', 'symbol', 'last', 'close']
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('symbol', inplace=True)
    return df

def _process_interest(info):
    interest = pd.DataFrame.from_records(info)
    # 整理数据
    interest['timestamp'] = pd.to_datetime(interest['timestamp'], unit='ms')
    interest.set_index('symbol', inplace=True)  # 将symbol设置为index
    return interest

def _process_fundingrate(info):
    df = pd.DataFrame([info['fundingTimestamp'],info['symbol'],"%.8f" % info['fundingRate']]).T
    df.columns=['candle_begin_time', 'symbol', 'fundingRate']
    df['candle_begin_time'] = pd.to_datetime(df['candle_begin_time'], unit='ms')
    df.sort_values(by=['candle_begin_time', 'symbol'], inplace=True)
    df.reset_index(drop=True, inplace=True)
    df.rename(columns={'candle_begin_time': 'timestamp'}, inplace=True)  # 修改列名
    df['timestamp'] = df['timestamp'].astype(np.int64) // 1000000    # 转换成时间戳
    return df

# 获取所有交易对K线
@async_method_locker("get_all_klines.locker")
@retry(retry_policy)
async def get_all_klines(exchange, symbol_list, start_time_dt, end_time_dt, interval='1h', limit=100, platform=None):
    all_candle_data = {}
    for symbol in symbol_list:
        candle_data = await get_klines(exchange, symbol, start_time_dt, end_time_dt, interval, limit, platform)
        all_candle_data = {symbol: candle_data}
    return all_candle_data

# 获取K线
@async_method_locker("get_klines.locker")
@retry(retry_policy)
async def get_klines(exchange, symbol, start_time_dt, end_time_dt, interval='1h', limit=100, platform=None):
    # 处理时区兼容
    # utc_offset = int(time.localtime().tm_gmtoff / 60 / 60)
    # 13位
    start_time_t = int(time.mktime(start_time_dt.timetuple())) * 1000
    end_time_t = int(time.mktime(end_time_dt.timetuple())) * 1000
    alldata = pd.DataFrame()
    columns = [
        'candle_begin_time',
        'open',
        'high',
        'low',
        'close',
        'volume'
    ]
    while True:
        kline = await exchange.fetch_ohlcv(symbol, timeframe=interval, since=start_time_t, limit=limit)
        # 整理数据
        df = pd.DataFrame(kline, columns=columns, dtype='float')
        df['candle_begin_time'] = pd.to_datetime(df['candle_begin_time'], unit='ms')

        alldata = alldata.append(df, ignore_index=False, sort=False)
        # 更新请求参数
        start_time_t = int(df.iat[-1, 0].timestamp()) * 1000
        if start_time_t >= end_time_t or df.shape[0] <= 1:
            break
        else:
            await asyncio.sleep(5)
    # 只保留当日数据
    alldata = alldata[alldata['candle_begin_time'] <= end_time_dt]
    alldata.sort_values('candle_begin_time', inplace=True)
    alldata.drop_duplicates(subset=['candle_begin_time'], keep='last', inplace=True)
    alldata.reset_index(drop=True, inplace=True)
    # 统一数据结构方便上传到Dolphindb (读取数据都是从数据库存)
    alldata['symbol'] = symbol                                              # 补充未有字段
    if interval == '1m':
        alldata['kline_type'] = 'kline'                                # 补充未有字段
    else:
        alldata['kline_type'] = f'kline_{interval}'                                # 补充未有字段
    alldata['platform'] = platform                                              # 补充未有字段
    alldata.rename(columns={'candle_begin_time': 'timestamp'}, inplace=True)  # 修改列名
    alldata['timestamp'] = alldata['timestamp'].astype(np.int64) // 1000000    # 转换成时间戳

    return alldata

# 获取服务器timestamp
@retry(retry_policy)
async def fetch_timestamp(exchange):
    timestamp = await exchange.fetch_time()
    return timestamp

# 设置杠杆
@retry(retry_policy)
async def reset_leverage(exchange, leverage=2, symbol=None):
    await exchange.set_leverage(leverage, symbol)
    print('All symbols max_leverage is', leverage)

# 账户互转
@retry(retry_policy)
async def transfer(exchange, code, amount, fromAccount, toAccount):
    data = await exchange.transfer(code, amount, fromAccount, toAccount)
    return data


# 钱包转账
@retry(retry_policy)
async def withdraw(exchange, code, amount, address, tag=None):
    data = await exchange.withdraw(code, amount, address, tag)
    return data

