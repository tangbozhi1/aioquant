# -*- coding:utf-8 -*-

"""
Tools Bag.

Author: HuangTao
Date:   2018/04/28
Email:  huangtao@ifclover.com
"""
import calendar
import uuid
import decimal
import datetime
import numpy as np
import time
import re
import traceback
from copy import deepcopy
import pandas as pd
from pyecharts.commons.utils import JsCode
from pyecharts import options as opts
from pyecharts.charts import Kline, Line, Bar, Scatter, Grid, Boxplot

def get_cur_timestamp():
    """Get current timestamp(second)."""
    ts = int(time.time())
    return ts


def get_cur_timestamp_ms():
    """Get current timestamp(millisecond)."""
    ts = int(time.time() * 1000)
    return ts


def get_datetime_str(fmt="%Y-%m-%d %H:%M:%S"):
    """Get date time string, year + month + day + hour + minute + second.

    Args:
        fmt: Date format, default is `%Y-%m-%d %H:%M:%S`.

    Returns:
        str_dt: Date time string.
    """
    today = datetime.datetime.today()
    str_dt = today.strftime(fmt)
    return str_dt


def get_date_str(fmt="%Y%m%d", delta_days=0):
    """Get date string, year + month + day.

    Args:
        fmt: Date format, default is `%Y%m%d`.
        delta_days: Delta days for currently, default is 0.

    Returns:
        str_d: Date string.
    """
    day = datetime.datetime.today()
    if delta_days:
        day += datetime.timedelta(days=delta_days)
    str_d = day.strftime(fmt)
    return str_d


def ts_to_datetime_str(ts=None, fmt="%Y-%m-%d %H:%M:%S"):
    """Convert timestamp to date time string.

    Args:
        ts: Timestamp, millisecond.
        fmt: Date time format, default is `%Y-%m-%d %H:%M:%S`.

    Returns:
        Date time string.
    """
    if not ts:
        ts = get_cur_timestamp()
    dt = datetime.datetime.fromtimestamp(int(ts))
    return dt.strftime(fmt)


def datetime_str_to_ts(dt_str, fmt="%Y-%m-%d %H:%M:%S"):
    """Convert date time string to timestamp.

    Args:
        dt_str: Date time string.
        fmt: Date time format, default is `%Y-%m-%d %H:%M:%S`.

    Returns:
        ts: Timestamp, millisecond.
    """
    ts = int(time.mktime(datetime.datetime.strptime(dt_str, fmt).timetuple()))
    return ts

def ms_to_ms_str(ts=None, fmt='%Y-%m-%dT%H:%M:%S.%f'):
    if not ts:
        ts = get_cur_timestamp()
    if not isinstance(ts, int):
        return None
    if int(ts) < 0:
        return None
    yyyy = '([0-9]{4})-?'
    mm = '([0-9]{2})-?'
    dd = '([0-9]{2})(?:T|[\\s])?'
    h = '([0-9]{2}):?'
    m = '([0-9]{2}):?'
    s = '([0-9]{2})'
    ms = '(\\.[0-9]{1,3})?'
    tz = '(?:(\\+|\\-)([0-9]{2})\\:?([0-9]{2})|Z)?'
    regex = r'' + yyyy + mm + dd + h + m + s + ms + tz
    try:
        match = re.search(regex, datetime.datetime.utcfromtimestamp(ts // 1000).strftime(fmt)[:-6] + "000Z", re.IGNORECASE)
        if match is None:
            return None
        yyyy, mm, dd, h, m, s, ms, sign, hours, minutes = match.groups()
        ms = ms or '.000'
        ms = (ms + '00')[0:4]
        msint = int(ms[1:])
        sign = sign or ''
        sign = int(sign + '1') * -1
        hours = int(hours or 0) * sign
        minutes = int(minutes or 0) * sign
        offset = datetime.timedelta(hours=hours, minutes=minutes)
        string = yyyy + mm + dd + h + m + s + ms + 'Z'
        dt = datetime.datetime.strptime(string, "%Y%m%d%H%M%S.%fZ")
        dt = dt + offset
        return calendar.timegm(dt.utctimetuple()) * 1000 + msint
    except (TypeError, OverflowError, OSError):
        return None
    
def get_utc_time():
    """Get current UTC time."""
    utc_t = datetime.datetime.utcnow()
    return utc_t


def utctime_str_to_ts(utctime_str, fmt="%Y-%m-%dT%H:%M:%S.%fZ"):
    """Convert UTC time string to timestamp(second).

    Args:
        utctime_str: UTC time string, e.g. `2019-03-04T09:14:27.806Z`.
        fmt: UTC time format, e.g. `%Y-%m-%dT%H:%M:%S.%fZ`.

    Returns:
        timestamp: Timestamp(second).
    """
    dt = datetime.datetime.strptime(utctime_str, fmt)
    timestamp = int(dt.replace(tzinfo=datetime.timezone.utc).astimezone(tz=None).timestamp())
    return timestamp


def utctime_str_to_ms(utctime_str, fmt="%Y-%m-%dT%H:%M:%S.%fZ"):
    """Convert UTC time string to timestamp(millisecond).

    Args:
        utctime_str: UTC time string, e.g. `2019-03-04T09:14:27.806Z`.
        fmt: UTC time format, e.g. `%Y-%m-%dT%H:%M:%S.%fZ`.

    Returns:
        timestamp: Timestamp(millisecond).
    """
    dt = datetime.datetime.strptime(utctime_str, fmt)
    timestamp = int(dt.replace(tzinfo=datetime.timezone.utc).astimezone(tz=None).timestamp() * 1000)
    return timestamp


def get_utctime_str(fmt="%Y-%m-%dT%H:%M:%S.%fZ"):
    """Get current UTC time string.

    Args:
        fmt: UTC time format, e.g. `%Y-%m-%dT%H:%M:%S.%fZ`.

    Returns:
        utctime_str: UTC time string, e.g. `2019-03-04T09:14:27.806Z`.
    """
    utctime = get_utc_time()
    utctime_str = utctime.strftime(fmt)
    return utctime_str

def timestamp_normalize(ts: datetime.datetime) -> float:
    return ts.astimezone(datetime.timezone.utc).timestamp()

def get_uuid1():
    """Generate a UUID based on the host ID and current time

    Returns:
        s: UUID1 string.
    """
    uid1 = uuid.uuid1()
    s = str(uid1)
    return s


def get_uuid3(str_in):
    """Generate a UUID using an MD5 hash of a namespace UUID and a name

    Args:
        str_in: Input string.

    Returns:
        s: UUID3 string.
    """
    uid3 = uuid.uuid3(uuid.NAMESPACE_DNS, str_in)
    s = str(uid3)
    return s


def get_uuid4():
    """Generate a random UUID.

    Returns:
        s: UUID5 string.
    """
    uid4 = uuid.uuid4()
    s = str(uid4)
    return s


def get_uuid5(str_in):
    """Generate a UUID using a SHA-1 hash of a namespace UUID and a name

    Args:
        str_in: Input string.

    Returns:
        s: UUID5 string.
    """
    uid5 = uuid.uuid5(uuid.NAMESPACE_DNS, str_in)
    s = str(uid5)
    return s


def float_to_str(f, p=20):
    """Convert the given float to a string, without resorting to scientific notation.

    Args:
        f: Float params.
        p: Precision length.

    Returns:
        s: String format data.
    """
    if type(f) == str:
        f = float(f)
    ctx = decimal.Context(p)
    d1 = ctx.create_decimal(repr(f))
    s = format(d1, 'f')
    return s

class ChanAnalyze:

    def __init__(self, klines):
        self.klines_orig = klines  # 原始K线
        # 原始K线每行追加'fx_mark':None,'fx':None,'bi':None,'xd':None生成新字段的K线
        self.klines = self.preprocess()
        self.klines_merge = self.merge()  # 合并后的K线 去除包含关系
        self.check_merge()  # 检查合并
        self.fxs = self.klinefx()  # 分型列表
        self.fbs = self.klinefb()  # 笔列表
        self.xds = self.klinexd()  # 线段列表
        self.zss = self.klinezs()  # 中枢列表
        self.__update_kline()
        # print("分型:",self.fxs)
        # print("分笔:",self.fbs)
        # print("线段:",self.xds)
        # print("中枢:",self.zss)

    def __update_kline(self):
        kn_map = {x['candle_begin_time']: x for x in self.klines_merge}
        for k in self.klines:
            k1 = kn_map.get(k['candle_begin_time'], None)
            if k1:
                k['fx_mark'], k['fx'], k['bi'], k['xd'] = k1['fx_mark'], k1['fx'], k1['bi'], k1['xd']

    '''
    原始K线追加新字段
    '''

    def preprocess(self):
        """新增分析所需字段"""
        if isinstance(self.klines_orig, pd.DataFrame):
            self.klines_orig = [row.to_dict()
                                for _, row in self.klines_orig.iterrows()]

        results = []
        for k in self.klines_orig:
            k['fx_mark'], k['fx'], k['bi'], k['xd'] = None, None, None, None
            results.append(k)
        return results

    '''
    合并
    '''
    # 对原始K线中正包与反包进行合并

    def merge(self):
        # 取前两根 K 线放入 k_new，完成初始化
        kline = deepcopy(self.klines)
        k_new = kline[:2]
        # 从 k_new 中取最后两根 K 线计算方向
        for k in kline[2:]:
            k1, k2 = k_new[-2:]
            if k2['high'] > k1['high']:
                direction = "up"
            elif k2['low'] < k1['low']:
                direction = "down"
            else:
                direction = "up"

            # 判断 k2 与 k 之间是否存在包含关系
            cur_h, cur_l, cur_v = k['high'], k['low'], k['volume']
            last_h, last_l, last_v = k2['high'], k2['low'], k2['volume']

            # 左包含 or 右包含
            if (cur_h <= last_h and cur_l >= last_l) or (cur_h >= last_h and cur_l <= last_l):
                # 有包含关系，按方向分别处理
                if direction == "up":
                    last_h = max(last_h, cur_h)
                    last_l = max(last_l, cur_l)
                    last_v = sum([last_v, cur_v])
                elif direction == "down":
                    last_h = min(last_h, cur_h)
                    last_l = min(last_l, cur_l)
                    last_v = sum([last_v, cur_v])
                else:
                    raise ValueError

                k['high'] = last_h
                k['low'] = last_l
                k['volume'] = last_v
                k_new.pop(-1)
                k_new.append(k)
            else:
                # 无包含关系，更新 K 线
                k_new.append(k)
        return k_new

    '''
    检查合并
    '''
    # 判断合并后的K线，如果存在正包与反包则出错

    def check_merge(self):
        for i in range(len(self.klines_merge)-1, -1, -1):
            if i < 1:
                return
            curent_kline = self.klines_merge[i]
            second_kline = self.klines_merge[i-1]
            if (curent_kline['low'] <= second_kline['low'] and curent_kline['high'] >= second_kline['high']) or \
                    (curent_kline['low'] >= second_kline['low'] and curent_kline['high'] <= second_kline['high']):
                print("wrong merge")
                print(curent_kline)
                print(second_kline)

    '''
     识别分型并标记
     顶分型'fx_mark':h
     底分型'fx_mark':l
     '''
    # 通过三根K线判断顶底分型

    def klinefx(self):
        kline = deepcopy(self.klines_merge)
        i = 0
        while i < len(kline):
            if i == 0 or i == len(kline) - 1:
                i += 1
                continue
            k1, k2, k3 = kline[i - 1: i + 2]
            i += 1

            # 顶分型标记
            if k2['high'] > k1['high'] and k2['high'] > k3['high']:
                k2['fx_mark'] = 'h'
                k2['fx'] = k2['high']

            # 底分型标记
            if k2['low'] < k1['low'] and k2['low'] < k3['low']:
                k2['fx_mark'] = 'l'
                k2['fx'] = k2['low']
        self.klines_merge = kline

        fx = [{"candle_begin_time": x['candle_begin_time'], "fx_mark": x['fx_mark'], "fx": x['fx']} for x in self.klines_merge
              if x['fx_mark'] in ['l', 'h']]
        return fx

    '''
    识别笔并标记
    '''
    # 对分型判断无共用K线，分型作废，分型相邻

    def klinefb(self):
        kline = deepcopy(self.klines_merge)
        fx_p = []
        for fx_mark in ['l', 'h']:
            fx = [x for x in deepcopy(self.fxs) if x['fx_mark'] == fx_mark]
            fx = sorted(
                fx, key=lambda x: x['candle_begin_time'], reverse=False)
            for i in range(1, len(fx) - 1):
                fx1, fx2, fx3 = fx[i - 1:i + 2]
                if (fx_mark == "l" and fx1['fx'] >= fx2['fx'] <= fx3['fx']) or \
                        (fx_mark == "h" and fx1['fx'] <= fx2['fx'] >= fx3['fx']):
                    fx_p.append(deepcopy(fx2))

        # 两个相邻的顶点分型之间有1根非共用K线
        for i in range(len(self.fxs) - 1):
            fx1, fx2 = self.fxs[i], self.fxs[i + 1]
            k_num = [x for x in kline if fx1['candle_begin_time'] <=
                     x['candle_begin_time'] <= fx2['candle_begin_time']]
            if len(k_num) >= 5:
                fx_p.append(deepcopy(fx1))
                fx_p.append(deepcopy(fx2))

        fx_p = sorted(
            fx_p, key=lambda x: x['candle_begin_time'], reverse=False)

        # 确认哪些分型可以构成笔
        bi = []
        for i in range(len(fx_p)):
            k = deepcopy(fx_p[i])
            k['bi'] = k['fx']
            del k['fx']
            if len(bi) == 0:
                bi.append(k)
            else:
                k0 = bi[-1]
                if k0['fx_mark'] == k['fx_mark']:
                    if (k0['fx_mark'] == "h" and k0['bi'] < k['bi']) or \
                            (k0['fx_mark'] == "l" and k0['bi'] > k['bi']):
                        bi.pop(-1)
                        bi.append(k)
                else:
                    # 确保相邻两个顶底之间顶大于底
                    if (k0['fx_mark'] == 'h' and k['bi'] >= k0['bi']) or \
                            (k0['fx_mark'] == 'l' and k['bi'] <= k0['bi']):
                        bi.pop(-1)
                        continue

                    # 一笔的顶底分型之间至少包含5根K线
                    k_num = [x for x in kline if k0['candle_begin_time']
                             <= x['candle_begin_time'] <= k['candle_begin_time']]
                    if len(k_num) >= 5:
                        bi.append(k)

        # 判断最后一笔标记是否有效：
        # 一、标记顶分型，最近K线在顶分型上方，则无效；标记底分型，最近K线在底分型下方，则无效
        # 二、标记顶分型，最近底分型在顶分型上方，则无效；标记底分型，最近顶分型在底分型下方，则无效
        last_bi = bi[-1]
        last_k = self.klines_merge[-1]
        if (last_bi['fx_mark'] == 'h' and last_k['high'] >= last_bi['bi']) or \
                (last_bi['fx_mark'] == 'l' and last_k['low'] <= last_bi['bi']):
            bi.pop()

        bi_list = [x["candle_begin_time"] for x in bi]
        for k in self.klines_merge:
            if k['candle_begin_time'] in bi_list:
                k['bi'] = k['fx']
        return bi

    '''
    识别线段并标记
    '''

    def klinexd(self):
        try:
            """依据不创新高、新低的近似标准找出所有潜在线段标记"""
            bi = deepcopy(self.fbs)
            xd = []
            potential = bi[0]

            i = 0
            while i < len(bi) - 3:
                k1, k2, k3 = bi[i + 1], bi[i + 2], bi[i + 3]

                if potential['fx_mark'] == "l":
                    assert k2['fx_mark'] == 'l'
                    if k3['bi'] < k1['bi']:
                        potential['xd'] = potential['bi']
                        xd.append(potential)
                        i += 1
                        potential = deepcopy(bi[i])
                    else:
                        i += 2
                elif potential['fx_mark'] == "h":
                    assert k2['fx_mark'] == 'h'
                    if k3['bi'] > k1['bi']:
                        potential['xd'] = potential['bi']
                        xd.append(potential)
                        i += 1
                        potential = deepcopy(bi[i])
                    else:
                        i += 2
                else:
                    raise ValueError

            potential['xd'] = potential['bi']
            xd.append(potential)
            xd = [{"candle_begin_time": x['candle_begin_time'],
                   "fx_mark": x['fx_mark'], "xd": x['xd']} for x in xd]

            bi = deepcopy(self.fbs)
            xd_v = []
            for i in range(len(xd)):
                p2 = deepcopy(xd[i])
                if i == 0:
                    xd_v.append(p2)
                else:
                    p1 = deepcopy(xd_v[-1])
                    if p1['fx_mark'] == p2['fx_mark']:
                        if (p1['fx_mark'] == 'h' and p1['xd'] < p2['xd']) or \
                                (p1['fx_mark'] == 'l' and p1['xd'] > p2['xd']):
                            xd_v.pop(-1)
                            xd_v.append(p2)
                    else:
                        # 连续两个不同类型线段标记不允许出现“线段高点低于线段低点”和“线段低点高于线段高点”的情况；
                        if (p1['fx_mark'] == "h" and p1['xd'] < p2['xd']) or \
                                (p1['fx_mark'] == "l" and p1['xd'] > p2['xd']):
                            continue

                        # bi_l = [x for x in bi if x['dt'] <= p1['dt']]
                        bi_m = [x for x in bi if p1['candle_begin_time'] <=
                                x['candle_begin_time'] <= p2['candle_begin_time']]
                        bi_r = [x for x in bi if x['candle_begin_time']
                                >= p2['candle_begin_time']]
                        if len(bi_m) == 2:
                            # 两个连续线段标记之间只有一笔的处理
                            if i == len(xd) - 1:
                                break
                            p3 = deepcopy(xd[i + 1])
                            if (p1['fx_mark'] == "h" and p1['xd'] < p3['xd']) or \
                                    (p1['fx_mark'] == "l" and p1['xd'] > p3['xd']):
                                xd_v.pop(-1)
                                xd_v.append(p3)
                        elif len(bi_m) == 4:
                            # 两个连续线段标记之间只有三笔的处理
                            lp2 = bi_m[-2]
                            rp2 = bi_r[1]
                            if lp2['fx_mark'] == rp2['fx_mark']:
                                if (p2['fx_mark'] == "h" and lp2['bi'] < rp2['bi']) or \
                                        (p2['fx_mark'] == "l" and lp2['bi'] > rp2['bi']):
                                    xd_v.append(p2)
                        else:
                            xd_v.append(p2)
            # 判断最后一线段标记是否有效：
            # 一、标记顶分型，最近K线在顶分型上方，则无效；标记底分型，最近K线在底分型下方，则无效
            # 二、标记顶分型，最近向下笔在顶分型上方，则无效；标记底分型，最近向上笔在底分型下方，则无效
            last_xd = xd_v[-1]

            last_k = self.klines_merge[-1]
            if (last_xd['fx_mark'] == 'h' and last_k['high'] >= last_xd['xd']) or \
                    (last_xd['fx_mark'] == 'l' and last_k['low'] <= last_xd['xd']):
                xd_v.pop()

            dts = [x['candle_begin_time'] for x in xd]

            def __add_xd(k):
                if k['candle_begin_time'] in dts:
                    k['xd'] = k['fx']
                return k

            self.klines_merge = [__add_xd(k) for k in self.klines_merge]
            return xd
        except:
            traceback.print_exc()
            return []

    '''
    识别中枢并标记
    '''

    def klinezs(self):
        if len(self.xds) <= 4:
            return []

        k_xd = self.xds
        k_zs = []
        zs_xd = []

        for i in range(len(k_xd)):
            if len(zs_xd) < 3:
                zs_xd.append(k_xd[i])
                continue
            xd_p = k_xd[i]
            zs_d = max([x['xd'] for x in zs_xd if x['fx_mark'] == 'l'])
            zs_g = min([x['xd'] for x in zs_xd if x['fx_mark'] == 'h'])

            if xd_p['fx_mark'] == "l" and xd_p['xd'] > zs_g:
                # 线段在中枢上方结束，形成三买
                k_zs.append({'zs': (zs_d, zs_g), "zs_xd": deepcopy(zs_xd)})
                zs_xd = deepcopy(k_xd[i - 2:i + 1])
            elif xd_p['fx_mark'] == "g" and xd_p['xd'] < zs_d:
                # 线段在中枢下方结束，形成三卖
                k_zs.append({'zs': (zs_d, zs_g), "zs_xd": deepcopy(zs_xd)})
                zs_xd = deepcopy(k_xd[i - 2:i + 1])
            else:
                zs_xd.append(deepcopy(xd_p))

        if len(zs_xd) >= 4:
            zs_d = max([x['xd'] for x in zs_xd if x['fx_mark'] == 'l'])
            zs_g = min([x['xd'] for x in zs_xd if x['fx_mark'] == 'h'])
            k_zs.append({'zs': (zs_d, zs_g), "zs_xd": deepcopy(zs_xd)})

        return k_zs

    '''
    绘制K线
    '''

    def draw_charts(self, klines, fx=None, bi=None, xd=None, width="1920px", height='1024px') -> Grid:
        """绘制缠中说禅K线分析结果
        :param kline: K线
        [{'candle_begin_time': Timestamp('2022-03-16 00:00:00'), 'symbol': 'ADA-USDT', 'open': 0.7989, 'high': 0.8337, 'low': 0.7933, 'close': 0.8001, 'volume': 145200427.3299, '是否交易': 1},
        {'candle_begin_time': Timestamp('2022-03-16 06:00:00'), 'symbol': 'ADA-USDT', 'open': 0.8001, 'high': 0.8157, 'low': 0.7979999999999999, 'close': 0.8106, 'volume': 79757761.86400002, '是否交易': 1}]
        :param fx: 分型识别结果
                [{'candle_begin_time': Timestamp('2022-05-09 17:00:00'), 'fx_mark': 'h', 'fx': 33788.0},
              {'candle_begin_time': Timestamp('2022-05-09 20:00:00'), 'fx_mark': 'l', 'fx': 32619.5}]
        :param bi: 笔识别结果
                [{'candle_begin_time': Timestamp('2022-05-09 21:00:00'), 'fx_mark': 'h', 'bi': 33442.3},
               {'candle_begin_time': Timestamp('2022-05-10 08:00:00'), 'fx_mark': 'l', 'bi': 29713.0}]
        :param xd: 线段识别结果
                [{'candle_begin_time': Timestamp('2022-05-09 21:00:00'), 'fx_mark': 'h', 'xd': 33442.3},
               {'candle_begin_time': Timestamp('2022-05-10 08:00:00'), 'fx_mark': 'l', 'xd': 29713.0}]
        :param width: 图表宽度
        :param height: 图表高度
        :return: 用Grid组合好的图表
        """
        # 配置项设置
        # ------------------------------------------------------------------------------------------------------------------
        bg_color = "#1f212d"  # 背景
        up_color = "#F9293E"
        down_color = "#00aa3b"

        init_opts = opts.InitOpts(bg_color=bg_color, width=width,
                                  height=height, animation_opts=opts.AnimationOpts(False))
        title_opts = opts.TitleOpts(title=klines[0]['symbol'], pos_top="1%", title_textstyle_opts=opts.TextStyleOpts(
            color=up_color, font_size=20), subtitle_textstyle_opts=opts.TextStyleOpts(color=down_color, font_size=12))
        label_not_show_opts = opts.LabelOpts(is_show=False)
        legend_not_show_opts = opts.LegendOpts(is_show=False)
        red_item_style = opts.ItemStyleOpts(color=up_color)
        green_item_style = opts.ItemStyleOpts(color=down_color)
        k_style_opts = opts.ItemStyleOpts(
            color=up_color, color0=down_color, border_color=up_color, border_color0=down_color, opacity=0.8)
        legend_opts = opts.LegendOpts(is_show=True, pos_top="1%", pos_left="30%", item_width=14,
                                      item_height=8, textstyle_opts=opts.TextStyleOpts(font_size=12, color="#0e99e2"))
        brush_opts = opts.BrushOpts(tool_box=["rect", "polygon", "keep", "lineX", "lineY", "clear"],
                                    x_axis_index="all", brush_link="all", out_of_brush={"colorAlpha": 0.1}, brush_type="lineX")
        axis_pointer_opts = opts.AxisPointerOpts(
            is_show=True, link=[{"xAxisIndex": "all"}])
        dz_inside = opts.DataZoomOpts(is_show=False, type_="inside", xaxis_index=[
                                      0, 1], range_start=98, range_end=100)
        dz_slider = opts.DataZoomOpts(is_show=True, xaxis_index=[
                                      0, 1], type_="slider", pos_top="85%", range_start=98, range_end=100)
        yaxis_opts = opts.AxisOpts(is_scale=True, axislabel_opts=opts.LabelOpts(
            color="#c7c7c7", font_size=8, position="inside"))
        grid0_xaxis_opts = opts.AxisOpts(type_="category", grid_index=0, axislabel_opts=label_not_show_opts, split_number=20,
                                         min_="dataMin", max_="dataMax", is_scale=True, boundary_gap=False, axisline_opts=opts.AxisLineOpts(is_on_zero=False))
        tool_tip_opts = opts.TooltipOpts(trigger="axis", axis_pointer_type="cross", background_color="rgba(245, 245, 245, 0.8)", border_width=1, border_color="#ccc",
                                         position=JsCode("""
                        function (pos, params, el, elRect, size) {
                            var obj = {top: 10};
                            obj[['left', 'right'][+(pos[0] < size.viewSize[0] / 2)]] = 30;
                            return obj;
                        }
                        """),
                                         textstyle_opts=opts.TextStyleOpts(
                                             color="#000"),
                                         )

        # 数据预处理
        # ------------------------------------------------------------------------------------------------------------------
        k_data = [opts.CandleStickItem(name=i, value=[x['open'], x['close'], x['low'], x['high']])
                  for i, x in enumerate(klines)]
        vol = []
        for i, row in enumerate(klines):
            item_style = red_item_style if row['close'] > row['open'] else green_item_style
            bar = opts.BarItem(
                name=i, value=row['volume'], itemstyle_opts=item_style, label_opts=label_not_show_opts)
            vol.append(bar)
        dts = [x['candle_begin_time'] for x in klines]

        # K 线主图
        # ------------------------------------------------------------------------------------------------------------------
        chart_k = Kline()
        chart_k.add_xaxis(xaxis_data=dts)
        chart_k.add_yaxis(series_name="Kline", y_axis=k_data,
                          itemstyle_opts=k_style_opts)
        chart_k.set_global_opts(
            legend_opts=legend_opts,
            datazoom_opts=[dz_inside, dz_slider],
            yaxis_opts=yaxis_opts,
            tooltip_opts=tool_tip_opts,
            axispointer_opts=axis_pointer_opts,
            brush_opts=brush_opts,
            title_opts=title_opts,
            xaxis_opts=grid0_xaxis_opts
        )

        # 缠论结果
        # ------------------------------------------------------------------------------------------------------------------
        if fx:
            fx_dts = [x['candle_begin_time'] for x in fx]
            fx_val = [x['fx'] for x in fx]
            chart_fx = Scatter()
            chart_fx.add_xaxis(fx_dts)
            chart_fx.add_yaxis(series_name="FX", y_axis=fx_val, is_selected=False, symbol="circle", symbol_size=6,
                               label_opts=label_not_show_opts, itemstyle_opts=opts.ItemStyleOpts(color="rgba(152, 147, 193, 1.0)", ))
            chart_fx.set_global_opts(
                xaxis_opts=grid0_xaxis_opts, legend_opts=legend_not_show_opts)
            chart_k = chart_k.overlap(chart_fx)

        if bi:
            bi_dts = [x['candle_begin_time'] for x in bi]
            bi_val = [x['bi'] for x in bi]
            chart_bi = Line()
            chart_bi.add_xaxis(bi_dts)
            chart_bi.add_yaxis(series_name="BI", y_axis=bi_val, is_selected=True, symbol="diamond", symbol_size=10, label_opts=label_not_show_opts,
                               itemstyle_opts=opts.ItemStyleOpts(color="rgba(255, 255, 0, 1.0)", ), linestyle_opts=opts.LineStyleOpts(width=1.5))
            chart_bi.set_global_opts(
                xaxis_opts=grid0_xaxis_opts, legend_opts=legend_not_show_opts)
            chart_k = chart_k.overlap(chart_bi)

        if xd:
            xd_dts = [x['candle_begin_time'] for x in xd]
            xd_val = [x['xd'] for x in xd]
            chart_xd = Line()
            chart_xd.add_xaxis(xd_dts)
            chart_xd.add_yaxis(series_name="XD", y_axis=xd_val, is_selected=True, symbol="triangle", symbol_size=10,
                               itemstyle_opts=opts.ItemStyleOpts(color="rgba(37, 141, 54, 1.0)", ), linestyle_opts=opts.LineStyleOpts(width=3.5))
            chart_xd.set_global_opts(
                xaxis_opts=grid0_xaxis_opts, legend_opts=legend_not_show_opts)
            chart_k = chart_k.overlap(chart_xd)

        # 成交量图
        # ------------------------------------------------------------------------------------------------------------------
        chart_vol = Bar()
        chart_vol.add_xaxis(dts)
        chart_vol.add_yaxis(series_name="Volume", y_axis=vol, bar_width='60%')
        chart_vol.set_global_opts(
            xaxis_opts=opts.AxisOpts(
                type_="category",
                grid_index=1,
                axislabel_opts=opts.LabelOpts(
                    is_show=True, font_size=8, color="#9b9da9"),
            ),
            yaxis_opts=yaxis_opts, legend_opts=legend_not_show_opts,
        )
        grid0_opts = opts.GridOpts(
            pos_left="0%", pos_right="1%", pos_top="12%", height="58%")
        grid1_opts = opts.GridOpts(
            pos_left="0%", pos_right="1%", pos_top="86%", height="10%")
        grid_chart = Grid(init_opts)
        grid_chart.add(chart_k, grid_opts=grid0_opts)
        grid_chart.add(chart_vol, grid_opts=grid1_opts)
        grid_chart.render(re.sub(r"[/,:]", "-", kline[0]['symbol'])+".html")



# calculating RSI (gives the same values as TradingView)
# https://stackoverflow.com/questions/20526414/relative-strength-index-in-python-pandas
def RSI(series, period=14):
    delta = series.diff().dropna()
    ups = delta * 0
    downs = ups.copy()
    ups[delta > 0] = delta[delta > 0]
    downs[delta < 0] = -delta[delta < 0]
    ups[ups.index[period-1]] = np.mean( ups[:period] ) #first value is sum of avg gains
    ups = ups.drop(ups.index[:(period-1)])
    downs[downs.index[period-1]] = np.mean( downs[:period] ) #first value is sum of avg losses
    downs = downs.drop(downs.index[:(period-1)])
    rs = ups.ewm(com=period-1,min_periods=0,adjust=False,ignore_na=False).mean() / \
         downs.ewm(com=period-1,min_periods=0,adjust=False,ignore_na=False).mean()
    return 100 - 100 / (1 + rs)


# calculating Stoch RSI (gives the same values as TradingView)
# https://www.tradingview.com/wiki/Stochastic_RSI_(STOCH_RSI)
def StochRSI(series, period=14, smoothK=3, smoothD=3):
    # Calculate RSI
    delta = series.diff().dropna()
    ups = delta * 0
    downs = ups.copy()
    ups[delta > 0] = delta[delta > 0]
    downs[delta < 0] = -delta[delta < 0]
    ups[ups.index[period-1]] = np.mean( ups[:period] ) #first value is sum of avg gains
    ups = ups.drop(ups.index[:(period-1)])
    downs[downs.index[period-1]] = np.mean( downs[:period] ) #first value is sum of avg losses
    downs = downs.drop(downs.index[:(period-1)])
    rs = ups.ewm(com=period-1,min_periods=0,adjust=False,ignore_na=False).mean() / \
         downs.ewm(com=period-1,min_periods=0,adjust=False,ignore_na=False).mean()
    rsi = 100 - 100 / (1 + rs)

    # Calculate StochRSI
    stochrsi  = (rsi - rsi.rolling(period).min()) / (rsi.rolling(period).max() - rsi.rolling(period).min())
    stochrsi_K = stochrsi.rolling(smoothK).mean()
    stochrsi_D = stochrsi_K.rolling(smoothD).mean()

    return stochrsi, stochrsi_K, stochrsi_D


# calculating Stoch RSI
#  -- Same as the above function but uses EMA, not SMA
def StochRSI_EMA(series, period=14, smoothK=3, smoothD=3):
    # Calculate RSI
    delta = series.diff().dropna()
    ups = delta * 0
    downs = ups.copy()
    ups[delta > 0] = delta[delta > 0]
    downs[delta < 0] = -delta[delta < 0]
    ups[ups.index[period-1]] = np.mean( ups[:period] ) #first value is sum of avg gains
    ups = ups.drop(ups.index[:(period-1)])
    downs[downs.index[period-1]] = np.mean( downs[:period] ) #first value is sum of avg losses
    downs = downs.drop(downs.index[:(period-1)])
    rs = ups.ewm(com=period-1,min_periods=0,adjust=False,ignore_na=False).mean() / \
         downs.ewm(com=period-1,min_periods=0,adjust=False,ignore_na=False).mean()
    rsi = 100 - 100 / (1 + rs)

    # Calculate StochRSI
    stochrsi  = (rsi - rsi.rolling(period).min()) / (rsi.rolling(period).max() - rsi.rolling(period).min())
    stochrsi_K = stochrsi.ewm(span=smoothK).mean()
    stochrsi_D = stochrsi_K.ewm(span=smoothD).mean()

    return stochrsi, stochrsi_K, stochrsi_D

def get_derivative(start, stop, step, value, delta=1e-10):
    """导函数生成器"""
    from scipy import interpolate
    _x = np.linspace(start, stop, step)
    _y = np.array(value)
    f = interpolate.interp1d(_x, _y, kind='cubic')
    def derivative(x):
        """导函数"""
        return (f(x + delta) - f(x)) / delta
    return derivative

def change_rate(data, start, stop, step, value):
    fd = get_derivative(start, stop, step, value)
    return fd(data)

class BSTNode:
    """
    定义一个二叉树节点类。
    以讨论算法为主，忽略了一些诸如对数据类型进行判断的问题。
    """
    def __init__(self, data, left=None, right=None):
        """
        初始化
        :param data: 节点储存的数据
        :param left: 节点左子树
        :param right: 节点右子树
        """
        self.data = data
        self.left = left
        self.right = right

class BinarySortTree:
    """
    基于BSTNode类的二叉查找树。维护一个根节点的指针。
    """
    def __init__(self):
        self._root = None

    def is_empty(self):
        return self._root is None

    def search(self, key):
        """
        关键码检索
        :param key: 关键码
        :return: 查询节点或None
        """
        bt = self._root
        while bt:
            entry = bt.data
            if key < entry:
                bt = bt.left
            elif key > entry:
                bt = bt.right
            else:
                return entry
        return None

    def insert(self, key):
        """
        插入操作
        :param key:关键码
        :return: 布尔值
        """
        bt = self._root
        if not bt:
            self._root = BSTNode(key)
            return
        while True:
            entry = bt.data
            if key < entry:
                if bt.left is None:
                    bt.left = BSTNode(key)
                    return
                bt = bt.left
            elif key > entry:
                if bt.right is None:
                    bt.right = BSTNode(key)
                    return
                bt = bt.right
            else:
                bt.data = key
                return

    def delete(self, key):
        """
        二叉查找树最复杂的方法
        :param key: 关键码
        :return: 布尔值
        """
        p, q = None, self._root     # 维持p为q的父节点，用于后面的链接操作
        if not q:
            print("空树！")
            return
        while q and q.data != key:
            p = q
            if key < q.data:
                q = q.left
            else:
                q = q.right
            if not q:               # 当树中没有关键码key时，结束退出。
                return
        # 上面已将找到了要删除的节点，用q引用。而p则是q的父节点或者None（q为根节点时）。
        if not q.left:
            if p is None:
                self._root = q.right
            elif q is p.left:
                p.left = q.right
            else:
                p.right = q.right
            return
        # 查找节点q的左子树的最右节点，将q的右子树链接为该节点的右子树
        # 该方法可能会增大树的深度，效率并不算高。可以设计其它的方法。
        r = q.left
        while r.right:
            r = r.right
        r.right = q.right
        if p is None:
            self._root = q.left
        elif p.left is q:
            p.left = q.left
        else:
            p.right = q.left

    def __iter__(self):
        """
        实现二叉树的中序遍历算法,
        展示我们创建的二叉查找树.
        直接使用python内置的列表作为一个栈。
        :return: data
        """
        stack = []
        node = self._root
        while node or stack:
            while node:
                stack.append(node)
                node = node.left
            node = stack.pop()
            yield node.data
            node = node.right


class DoubleNode:
    def __init__(self, elem):
        self.elem = elem
        self.next = None
        self.prev = None

class Linked:
    def __init__(self, node=None):
        self.__head = node
        if node:
            node.next = node
            node.prev = node

    def is_empty(self):
        """判断链表是否为空"""
        # 判断头结点的值是否为空
        return self.__head is None

    def length(self):
        """判断链表长度"""
        # 初始化游标
        cur = self.__head
        # 判断是否为空
        if self.__head is None:
            return
        # 长度计算变量
        count = 1
        # 判断游标指向是否为空
        while cur.next is not self.__head:
            # 指向下一个结点，同时计数器加一
            cur = cur.next
            count += 1
        return count

    def travel(self):
        """遍历整个链表并存为列表"""
        # 初始化游标
        cur = self.__head
        # 判断是否为空
        if self.__head is None:
            return
        # 输出每个结点的elem
        list = []
        while cur.next is not self.__head:
            list.append(cur.elem)
            cur = cur.next
        # 最后一跳已出循环
        list.append(cur.elem)
        return list

    def sort(self, elem):
        """
        给定一个链表和一个值x，将它划分为所有小于x的节点都在大于或等于x的节点之前，
        同时保留两个分区中每个节点的原始相对顺序。
         X为8.5
        原始[1, 2, 2, 3, 4, 5, 10, 11, 12, 7, 8, 9, 10, 11, 12]
        新的[8, 7, 12, 11, 10, 5, 4, 3, 2, 2, 1]
        """
        # 初始化游标
        cur = self.__head
        # 判断是否为空
        if self.__head is None:
            return
        # 创建新结点
        phead1 = DoubleNode(elem)
        phead2 = DoubleNode(elem)
        minNode = phead1
        maxNode = phead2
        # 一个用于存放小于x值的链表，另一个用于存放大于x值的链表
        while cur.next is not self.__head:
            # 初始
            # cur循环链（2000－1000－1007.7）
            # minNode  单节点1368
            # phead1   单链插1368
            # maxNode  单节点1368
            # phead2   单节点1368
            # 循环后
            # cur循环链（2000－1000－1007.7）
            # minNode  单链         无限2000－1000－1007.7－1015.5....-1360.8之后为空
            # phead1   单链插入节点  之前为空1368－1000－1007.7 (1000之前是2000) 不变

            # maxNode  单链         之前为空1364.9－1371.3－1381.9....-2000无限
            # phead2   单链插入节点  之前为空1364.9－1371.3－1381.9 (1371.3之前是1360.8) 不变
            if cur.elem < elem:
                minNode.next = cur    # 为minNode附值cur链，直到1368之后为空
                cur = cur.next        # 移动cur指针
                minNode = minNode.next# 移动minNode指针
                minNode.next = None   # 到1368之后的minNode为空
            else:
                maxNode.next = cur    # 为maxNode附值cur链，直到2000之后为空
                cur = cur.next        # 移动cur指针
                maxNode = maxNode.next# 移动maxNode指针
                maxNode.next = None   # 到2000之后(即1000)的minNode为空
        # 最后一跳已出循环（cur.elem为2000)
        # 最后一跳后
        # cur循环链（.....2000之后为空）
        # minNode  单链         无限2000－1000－1007.7－1015.5....-1360.8之后为空  执行会切断2000之后的无限
        # phead1   单链插入节点  之前为空1368－1000－1007.7 (1000之前是2000) 不变

        #  maxNode  单链         之前为空1364.9－1371.3－1381.9....-2000无限   执行会切断2000之后的无限
        # phead2   单链插入节点  之前为空1364.9－1371.3－1381.9 (1371.3之前是1360.8) 不变
        if cur.elem <= elem:          # 小于不运行
            minNode.next = cur        # 为minNode下一根附值2000
            minNode = minNode.next    # 移动minNode指针
            minNode.next = None       # 到1000之后的minNode为空
        else:                         # 大于不运行
            maxNode.next = cur        # 为maxNode下一根附值2000
            maxNode = maxNode.next    # 移动minNode指针
            maxNode.next = None       # 切断2000之后
        #  minNode  从单链变循环链,cur变成单链
        cur.next = self.__head  # !!!!!!!!!!!!!!!!!!!!!!!搞不懂为啥上面会造成实例中节点断开从循环链变成单链，此处作用是将cur.next的None变成1000恢复成循环链表
        minNode.next = phead2.next    # 给minNode单链补充固定链成一条循环链 1360.8-1371.3－1381.9

        # 结束
        # 此时maxNode是大于elem的单链，minNode是循环链,但此时的minNode的elem已经是1360.8会立即退出循环，只能向前查找
        # 输出每个结点的elem
        list = []
        while minNode is not maxNode:
            list.append(minNode.elem)
            minNode = minNode.prev # 此时的minNode的elem已经是1360.8会立即退出循环，只能向前查找
        return list

    def position(self, pos):
        """根据位置读取元素"""
        # 判断输入位置是否在链表中
        if 0 <= pos <= (self.length() - 1):
            # 创建游标
            cur = self.__head
            # 创建计数器
            count = 0
            # 将游标移动到指定位置
            while count < pos:
                count += 1
                cur = cur.next
            return cur.elem
        else:
            return False

    def element(self, elem):
        """输出元素所在位置"""
        # 创建游标和计数器
        cur = self.__head
        count = 0
        while True:
            # 判断游标指向元素是否为输入元素
            if cur.elem == elem:
                return count
            # 判断测试的长度是否已经超出
            elif cur.next is self.__head:
                return False
            cur = cur.next
            count += 1

    def clear(self):
        """清空链表"""
        self.__head = None

    def add(self, elem):
        """头部添加元素"""
        # 创建新结点
        newNode = DoubleNode(elem)
        # 判断是否为空链表
        if self.is_empty():
            self.__head = newNode
            newNode.prev, newNode.next = self.__head, self.__head
        else:
            # 将新结点指向原头结点
            newNode.next = self.__head
            # 将尾结点指向新结点
            self.__head.prev.next = newNode
            # 将新结点指向尾结点
            newNode.prev = self.__head.prev
            # 将原头结点指向新结点
            self.__head.prev = newNode
            # 将原头结点定义为新结点
            self.__head = newNode

    def append(self, elem):
        """尾部添加元素"""
        # 新建结点
        newNode = DoubleNode(elem)
        # 判断是否为空链表
        if self.is_empty():
            self.__head = newNode
            newNode.prev, newNode.next = self.__head, self.__head
        else:
            # 将原尾结点指向新结点
            self.__head.prev.next = newNode
            # 将新结点指向原尾结点
            newNode.prev = self.__head.prev
            # 将尾结点指向头结点
            newNode.next = self.__head
            # 将头结点指向尾结点
            self.__head.prev = newNode

    def insert(self, pos, elem):
        """指定位置添加元素"""
        # 判断插入位置
        if pos <= 0:
            self.add(elem)
        elif pos > (self.length() - 1):
            self.append(elem)
        else:
            # 新建结点
            newNode = DoubleNode(elem)
            # 创建游标以及副游标
            cur = self.__head
            # 创建计数器
            count = 0
            # 将游标定位到指定位置前一位结点上
            while count < (pos - 1):
                count += 1
                cur = cur.next
            # 将新结点指向游标以及游标之后的结点
            newNode.prev, newNode.next = cur, cur.next
            # 将游标所在结点之后的结点指向新结点
            cur.next.prev = newNode
            # 将指针所在结点指向新结点
            cur.next = newNode

    def del_add(self):
        """删除首结点"""
        # 创建指向尾结点的游标
        cur = self.__head.prev
        # 将头结点后移一位
        self.__head = self.__head.next
        # 将尾结点指向新的头结点
        cur.next = self.__head
        # 将新的头结点执行尾结点
        self.__head.prev = self.__head

    def del_app(self):
        """删除尾结点"""
        # 创建游标并且指向尾结点
        cur = self.__head.prev
        # 将游标前移一位
        cur = cur.prev
        # 将游标所在结点指向头结点
        cur.next = self.__head
        # 将头结点指向游标所在位置
        self.__head.prev = cur

    def remove(self, elem):
        """根据指定元素删除"""
        cur = self.__head
        while cur:
            # 判断游标指向元素是否为输入元素
            if cur.elem == elem:
                # 判断是否删除的为首节点
                if self.__head.elem == elem:
                    self.del_add()
                    return
                # 判断是否删除的为尾结点
                if cur.next is self.__head:
                    self.del_app()
                    return
                else:
                    cur.next.prev = cur.prev
                    cur.prev.next = cur.next
                break
            elif cur.next == self.__head:
                return
            # 游标后移
            else:
                cur = cur.next

    def delete(self, pos):
        """根据位置删除"""
        # 判断输入是否在链表中
        if 0 <= pos <= (self.length() - 1):
            # 判断是否为首结点
            if pos == 0:
                self.del_add()
                return
            # 判断是否为尾结点
            elif pos == self.length():
                self.del_app()
                return
            else:
                # 创建游标以及计数器
                cur = self.__head
                count = 0
                while count < pos:
                    count += 1
                    cur = cur.next
                cur.next.prev = cur.prev
                cur.prev.next = cur.next

    def __len__(self):
        """可以使用len()方法获取链表长度"""
        return self.length

    def __iter__(self):
        """可使用循环遍历链表里的元素"""
        if self.is_empty():
            return
        cur = self.__head
        yield cur.elem
        while cur.next != self.__head:
            cur = cur.next
            yield cur.elem

    def __contains__(self, elem):
        """可以使用in进行判断是否在链表中"""
        if self.is_empty():
            return False
        cur = self.__head
        if cur.elem == elem:
            return True
        while cur.next != self.__head:
            cur = cur.next
            if cur.elem == elem:
                return True
        return False
