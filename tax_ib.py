#!/usr/bin/env python
# coding: utf-8

from collections import defaultdict
from string import digits as DIGITS
import copy
import csv
import datetime
import glob

import prettytable

_CBRF = None


class Trade(object):
    def __init__(self, symbol, date, quantity, price, fee, **kwds):
        self.is_buying = quantity > 0

        self.symbol = symbol
        self.date = date
        self.quantity = quantity
        self.price = price
        self.fee = fee

        self.proceeds = kwds.get('proceeds')
        self.basis = kwds.get('basis')
        self.realized_pl = kwds.get('realized_pl')

    def __str__(self):
        return 'sym: {self.symbol}, date: {self.date}, quantity: {self.quantity}, price: {self.price}'.format(self=self)


def str2date(s):
    if s[2] in DIGITS:
        yy, mm, dd = s[:4], s[5:7], s[8:10]
    else:
        dd, mm, yy = s[:2], s[3:5], s[6:10]
    return datetime.date(int(yy), int(mm), int(dd))


def parse_fee(fee):
    """
    >>> parse_fee('-1.0241')
    -1.02
    """
    a, _, b = fee.partition('.')
    fee2 = a + '.' + b[:2]
    return float(fee2)


def parse_trades(filepaths):
    trades = []
    for filepath in filepaths:
        with open(filepath) as fobj:
            keys = None
            for i, row in enumerate(csv.reader(fobj)):
                if row[0] != 'Trades':
                    continue
                if row[1] == 'Header':
                    keys = row
                    continue
                if row[1] == 'Data':
                    trade = dict(zip(keys, row))
                    trades.append(Trade(
                        symbol=trade['Symbol'],
                        date=str2date(trade['Date/Time']),
                        quantity=int(trade['Quantity']),
                        price=float(trade['T. Price']),
                        fee=parse_fee(trade['Comm/Fee']),
                        proceeds=float(trade['Proceeds']),
                        basis=float(trade['Basis']),
                        realized_pl=float(trade['Realized P/L']),
                    ))
    trades.sort(key=lambda x: x.date)
    return trades


def print_trades(trades):
    keys = ['symbol', 'date', 'quantity', 'price', 'proceeds', 'fee', 'basis', 'realized_pl']
    rows = []
    for i, trade in enumerate(trades):
        row = {'N': i+1}
        for key in keys:
            val = trade.__dict__[key]
            if isinstance(val, float):
                val = '{:.2f}'.format(round(val, 2))
            row[key] = val
        rows.append(row)

    keys.insert(0, 'N')
    pt = prettytable.PrettyTable(keys)
    pt.align = 'r'
    pt.align['symbol'] = 'l'
    for row in rows:
        row = [row.get(key, '-') for key in keys]
        pt.add_row(row)

    print pt.get_string()


class TaxItem(object):
    def __init__(self, buy, sel):
        self.buy = buy
        self.sel = sel

        self.revenue_usd = buy.quantity * (float(sel.price) - float(buy.price)) + sel.fee + buy.fee
        self.revenue_rur = buy.quantity * (float(sel.price) * usd_to_rub(sel.date) - float(buy.price) * usd_to_rub(buy.date)) + sel.fee * usd_to_rub(sel.date) + buy.fee * usd_to_rub(buy.date)
        self.tax_rur = self.revenue_rur * 0.13


def calc_tax(trades):
    items = []
    sym2blist = defaultdict(list)
    for trade in trades:
        if trade.is_buying:
            # buy
            sym2blist[trade.symbol].append(trade)
            continue
        # sell, sel.quantity отрицательное число
        blist = sym2blist[trade.symbol]
        sel = trade
        while sel.quantity:
            buy = blist[0]
            # sel.fee, buy.fee = float(sel.fee), float(buy.fee)
            if buy.quantity + sel.quantity > 0:
                # продаем меньше чем первая покупка в списке
                quantity = -sel.quantity
                tr1 = copy.copy(buy)
                tr1.quantity = quantity
                tr1.fee = round(tr1.fee * quantity / buy.quantity, 2)
                buy.quantity -= quantity
                buy.fee = round(buy.fee - tr1.fee, 2)
                items.append(TaxItem(tr1, sel))
                break
            else:  # buy.quantity + sel.quantity < 0
                # продаем больше или равно чем первая покупка в списке
                blist.pop(0)
                # print sel.symbol, sel.quantity, buy.quantity
                tr2 = copy.copy(sel)
                tr2.quantity = buy.quantity
                tr2.fee = round(tr2.fee * buy.quantity / -sel.quantity, 2)
                sel.quantity += buy.quantity
                sel.fee -= tr2.fee
                items.append(TaxItem(buy, tr2))
    return items


def print_tax(taxitems):
    rows = []
    for titem in taxitems:
        buy, sel = titem.buy, titem.sel
        rows.append({
            'symbol': buy.symbol,
            'date_buy': buy.date,
            'date_sell': sel.date,
            'price_buy': float(buy.price),
            'price_sell': float(sel.price),
            'quantity': sel.quantity,
            'fee': sel.fee + buy.fee,
            'revenue_usd': titem.revenue_usd,
            'cbrf_buy':  usd_to_rub(buy.date),
            'cbrf_sel':  usd_to_rub(sel.date),
            'revenue_rur': titem.revenue_rur,
            'tax_rur': round(titem.tax_rur, 2),
        })

    total = {}
    for row in rows:
        for key in ['fee', 'revenue_usd', 'revenue_rur', 'tax_rur']:
            total[key] = total.get(key, 0) + row[key]
    rows.append(total)

    for row in rows:
        for key, val in row.iteritems():
            if isinstance(val, float):
                row[key] = '{:.2f}'.format(round(val, 2))

    keys = ['symbol', 'date_sell', 'date_buy', 'price_sell', 'price_buy', 'quantity', 'cbrf_sel', 'cbrf_buy', 'fee', 'revenue_usd', 'revenue_rur', 'tax_rur']
    pt = prettytable.PrettyTable(keys)
    pt.align = 'r'
    pt.align['symbol'] = 'l'
    for row in rows:
        row = [row.get(key, '-') for key in keys]
        pt.add_row(row)
    print pt.get_string()


def read_cbrf(filepaths):
    date2curs = {}
    for filepath in filepaths:
        prev = None
        with open(filepath) as fobj:
            for i, line in enumerate(fobj):
                if i == 0:
                    continue
                row = line.split(',')
                data, curs = row[1], row[2]
                # print data, curs
                date = str2date(data)
                date2curs[date] = curs
                if prev is not None:
                    curs = date2curs[prev]
                    for day in xrange(1, (date - prev).days):
                        prev += datetime.timedelta(days=1)
                        date2curs[prev] = curs
                prev = date
    return date2curs


def usd_to_rub(date):
    global _CBRF
    if _CBRF is None:
        _CBRF = read_cbrf(glob.glob('cbrf/*.csv'))
    if isinstance(date, basestring):
        date = str2date(date)
    return float(_CBRF[date])


def main():
    trades = parse_trades(glob.glob('ib_reports/*.csv'))

    print '===Trades'
    print_trades(trades)

    year2titems = defaultdict(list)
    for titem in calc_tax(trades):
        year2titems[titem.sel.date.year].append(titem)
    for year in sorted(year2titems):
        print '==={}'.format(year)
        titems = year2titems[year]
        titems.sort(key=lambda x: x.sel.date)
        print_tax(year2titems[year])


if __name__ == '__main__':
    main()
