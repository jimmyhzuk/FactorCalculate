#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""
@version: 0.1
@author: zzh
@file: factor_scale_value.py
@time: 2019-01-28 11:33
"""
import sys

from vision.file_unit.balance import Balance

from jpy.factor.ttm_fundamental import get_ttm_fundamental

sys.path.append("../")
sys.path.append("../../")
sys.path.append("../../../")

import argparse
import time
import collections
import pandas as pd
from datetime import datetime, timedelta
from factor.factor_base import FactorBase
from vision.fm.signletion_engine import *
from vision.file_unit.income import Income
from vision.file_unit.valuation import Valuation
from ultron.cluster.invoke.cache_data import cache_data
from factor import factor_scale_value_task
from factor.utillities.trade_date import TradeDate


class FactorScaleValue(FactorBase):

    def __init__(self, name):
        super(FactorScaleValue, self).__init__(name)
        self._trade_date = TradeDate()

    # 构建因子表
    def create_dest_tables(self):
        """
        创建数据库表
        :return:
        """
        drop_sql = """drop table if exists `{0}`""".format(self._name)

        create_sql = """create table `{0}`(
                    `id` varchar(32) NOT NULL,
                    `symbol` varchar(24) NOT NULL,
                    `trade_date` date NOT NULL,
                    `mkt_value` decimal(19,4) NOT NULL,
                    `cir_mkt_value` decimal(19,4),
                    `sales_ttm` decimal(19,4),
                    `total_assets` decimal(19,4),
                    `log_of_mkt_value` decimal(19, 4),
                    `log_of_neg_mkt_value` decimal(19,4),
                    `nl_size` decimal(19,4),
                    `log_sales_ttm` decimal(19,4),
                    `log_total_last_qua_assets` decimal(19,4),
                    PRIMARY KEY(`id`,`trade_date`,`symbol`)
                    )ENGINE=InnoDB DEFAULT CHARSET=utf8;""".format(self._name)
        super(FactorScaleValue, self)._create_tables(create_sql, drop_sql)

    def get_trade_date(self, trade_date, n):
        """
        获取当前时间前n年的时间点，且为交易日，如果非交易日，则往前提取最近的一天。
        :param trade_date: 当前交易日
        :param n:
        :return:
        """
        # print("trade_date %s" % trade_date)
        trade_date_sets = collections.OrderedDict(
            sorted(self._trade_date._trade_date_sets.items(), key=lambda t: t[0], reverse=False))

        time_array = datetime.strptime(str(trade_date), "%Y%m%d")
        time_array = time_array - timedelta(days=365) * n
        date_time = int(datetime.strftime(time_array, "%Y%m%d"))
        if date_time < min(trade_date_sets.keys()):
            # print('date_time %s is outof trade_date_sets' % date_time)
            return date_time
        else:
            while not date_time in trade_date_sets:
                date_time = date_time - 1
            # print('trade_date pre %s year %s' % (n, date_time))
            return date_time

    def get_basic_data(self, trade_date):
        """
        获取基础数据
        按天获取当天交易日所有股票的基础数据
        :param trade_date: 交易日
        :return:
        """
        # market_cap，circulating_market_cap，total_operating_revenue
        valuation_sets = get_fundamentals(add_filter_trade(query(Valuation._name_,
                                                                 [Valuation.symbol,
                                                                  Valuation.market_cap,
                                                                  Valuation.circulating_market_cap]), [trade_date]))

        income_sets = get_fundamentals(add_filter_trade(query(Income._name_,
                                                              [Income.symbol,
                                                               Income.total_operating_revenue]), [trade_date]))
        balance_set = get_fundamentals(add_filter_trade(query(Balance._name_,
                                                              [Balance.symbol,
                                                               Balance.total_assets]), [trade_date]))
        # TTM计算
        ttm_factors = {Income._name_: [Income.symbol,
                                       Income.total_operating_revenue]
                       }

        ttm_factor_sets = get_ttm_fundamental([], ttm_factors, trade_date).reset_index()
        # ttm 周期内计算需要优化
        # ttm_factor_sets_sum = get_ttm_fundamental([], ttm_factors_sum_list, trade_date, 5).reset_index()

        ttm_factor_sets = ttm_factor_sets.drop(columns={"trade_date"})

        return valuation_sets, ttm_factor_sets, income_sets, balance_set

    def prepaer_calculate(self, trade_date):
        valuation_sets, ttm_factor_sets, income_sets, balance_set = self.get_basic_data(trade_date)
        # valuation_sets = pd.merge(valuation_sets, income_sets, on='symbol')
        valuation_sets = pd.merge(valuation_sets, ttm_factor_sets, on='symbol')
        valuation_sets = pd.merge(valuation_sets, balance_set, on='symbol')
        if len(valuation_sets) <= 0:
            print("%s has no data" % trade_date)
            return
        else:
            session = str(int(time.time() * 1000000 + datetime.now().microsecond))
            cache_data.set_cache(session, 'scale' + str(trade_date), valuation_sets.to_json(orient='records'))
            factor_scale_value_task.calculate.delay(factor_name='scale' + str(trade_date), trade_date=trade_date,
                                                    session=session)

    def do_update(self, start_date, end_date, count):
        # 读取本地交易日
        trade_date_sets = self._trade_date.trade_date_sets_ago(start_date, end_date, count)
        for trade_date in trade_date_sets:
            print('因子计算日期： %s' % trade_date)
            self.prepaer_calculate(trade_date)
        print('----->')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--start_date', type=int, default=20070101)
    parser.add_argument('--end_date', type=int, default=0)
    parser.add_argument('--count', type=int, default=1)
    parser.add_argument('--rebuild', type=bool, default=False)
    parser.add_argument('--update', type=bool, default=False)
    parser.add_argument('--schedule', type=bool, default=False)

    args = parser.parse_args()
    if args.end_date == 0:
        end_date = int(datetime.now().date().strftime('%Y%m%d'))
    else:
        end_date = args.end_date
    if args.rebuild:
        processor = FactorScaleValue('factor_scale_value')
        processor.create_dest_tables()
        processor.do_update(args.start_date, end_date, args.count)
    if args.update:
        processor = FactorScaleValue('factor_scale_value')
        processor.do_update(args.start_date, end_date, args.count)
