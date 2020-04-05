#!/usr/bin/env python2
# coding: utf-8

from collections import defaultdict
from string import digits as DIGITS
import copy
import csv
import datetime
import glob

try:
    import click
    import prettytable
except ImportError:
    print 'Error: cant import click|prettytable'
    print
    print '1. use anaconda'
    print 'or'
    print '2. pip install click prettytable'
    exit(1)

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


class Dividend(object):
    def __init__(self, symbol, date, amount, **kwds):
        self.symbol = symbol
        self.date = date
        self.amount = amount

        self.broker_tax = 0

    @property
    def tax_ib(self):
        return self.broker_tax

    @property
    def tax_ib_rur(self):
        rate = usd_to_rub(self.date)
        return round(self.broker_tax * rate, 2)

    @property
    def tax_me(self):
        return self.amount * 0.13 - int(round(self.broker_tax, 0))

    @property
    def tax_me_rur(self):
        rate = usd_to_rub(self.date)
        tax_rur = self.amount * rate * 0.13 - int(round(self.broker_tax * rate, 0))
        return int(round(tax_rur, 0))

    def __str__(self):
        return 'DIV sym: {self.symbol}, date: {self.date}, amount: {self.amount}'.format(self=self)


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
                        fee=abs(parse_fee(trade['Comm/Fee'])),
                        proceeds=float(trade['Proceeds']),
                        basis=float(trade['Basis']),
                        realized_pl=float(trade['Realized P/L']),
                    ))
    trades.sort(key=lambda x: x.date)
    return trades


def parse_dividends(filepaths):
    dividends = {}
    for filepath in filepaths:
        with open(filepath) as fobj:
            keys = None
            for i, row in enumerate(csv.reader(fobj)):
                if row[0] == 'Dividends':
                    if row[1] == 'Header':
                        keys = row
                    elif row[1] == 'Data':
                        kv = dict(zip(keys, row))
                        if kv['Currency'] == 'Total':
                            continue
                        date = str2date(kv['Date'])
                        symbol = kv['Description'].partition('(')[0].strip()
                        dividends[(date, symbol)] = Dividend(
                            symbol=symbol,
                            date=date,
                            amount=float(kv['Amount']),
                        )
                elif row[0] == 'Withholding Tax':
                    if row[1] == 'Header':
                        keys = row
                    elif row[1] == 'Data':
                        kv = dict(zip(keys, row))
                        if kv['Currency'] == 'Total':
                            continue
                        date = str2date(kv['Date'])
                        symbol = kv['Description'].partition('(')[0].strip()
                        tax = abs(float(kv['Amount']))

                        div = dividends[(date, symbol)]
                        div.broker_tax = tax

    divs = dividends.values()
    divs.sort(key=lambda x: (x.date, x.symbol))
    return divs


class TaxItem(object):
    def __init__(self, buy_list, sel):
        self.symbol = sel.symbol
        self.quantity = abs(sel.quantity)
        self.date_sell = sel.date
        self.price_sell = sel.price
        quantity = self.quantity

        self.buy_usd = sum(buy.quantity * buy.price + buy.fee for buy in buy_list)
        self.sell_usd = quantity * sel.price - sel.fee
        self.profit_usd = self.sell_usd - self.buy_usd
        self.buy_rur = sum(usd_to_rub(buy.date) * (buy.quantity * buy.price + buy.fee) for buy in buy_list)
        self.sell_rur = self.sell_usd * usd_to_rub(sel.date)
        self.profit_rur = self.sell_rur - self.buy_rur

        self.tax_rur = round(self.profit_rur * 0.13, 0)
        self.price_buy = self.buy_usd / quantity
        self.fee = sel.fee + sum(buy.fee for buy in buy_list)


def calc_tax(trades):
    items = []
    sym2blist = defaultdict(list)
    slist = []
    for trade in trades:
        if trade.is_buying:
            # buy
            sym2blist[trade.symbol].append(trade)
            continue
        slist.append(trade)

    for sel in slist:
        blist = sym2blist[sel.symbol]
        buy_list = []
        quantity = abs(sel.quantity)

        while quantity:
            buy = blist[0]
            if buy.quantity > quantity:
                # продаем меньше чем первая покупка в списке
                tr = copy.copy(buy)
                tr.quantity = quantity
                tr.fee = round(tr.fee * quantity / buy.quantity, 2)
                buy.quantity -= quantity
                buy.fee = round(buy.fee - tr.fee, 2)
                buy_list.append(tr)
                break
            else:  # buy.quantity <= quantity
                # продаем больше или равно чем первая покупка в списке
                blist.pop(0)
                quantity -= buy.quantity
                buy_list.append(buy)

        items.append(TaxItem(buy_list, sel))

    return items


def print_table(items, keys, keys_total=None):
    rows = []
    for i, item in enumerate(items):
        row = {'N': i+1}
        for key in keys:
            row[key] = getattr(item, key)
        rows.append(row)

    if keys_total:
        total = {}
        for row in rows:
            for key in keys_total:
                val = row[key]
                if isinstance(val, (int, float)):
                    total[key] = total.get(key, 0) + val
        rows.append(total)

    for row in rows:
        for key, val in row.iteritems():
            if isinstance(val, float):
                row[key] = '{:.2f}'.format(round(val, 2))

    keys = ['N'] + keys[:]
    pt = prettytable.PrettyTable(keys)
    pt.align = 'r'
    pt.align['symbol'] = 'l'
    for row in rows:
        row = [row.get(key, '-') for key in keys]
        pt.add_row(row)
    print pt.get_string()


def read_cbrf(filepaths):
    """
    https://cbr.ru/currency_base/dynamics/?UniDbQuery.Posted=True&UniDbQuery.mode=2&UniDbQuery.date_req1=&UniDbQuery.date_req2=&UniDbQuery.VAL_NM_RQ=R01235&UniDbQuery.From=01.01.2010&UniDbQuery.To=28.03.2020
    """
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


def process_trades(ctx, year, verbose=False):
    trades = parse_trades(ctx.ib_reports_files)

    # print '===Trades'
    # print_table(trades, ['symbol', 'date', 'quantity', 'price', 'proceeds', 'fee', 'basis', 'realized_pl'])

    keys = [
        'symbol', 'date_sell', 'quantity', 'price_sell', 'price_buy',
        'fee', 'sell_usd', 'buy_usd', 'profit_usd', 'sell_rur', 'buy_rur', 'profit_rur', 'tax_rur',
    ]
    keys_total = ['fee', 'sell_usd', 'buy_usd', 'profit_usd', 'sell_rur', 'buy_rur', 'profit_rur', 'tax_rur']
    if not verbose:
        keys = ['symbol', 'date_sell', 'quantity', 'sell_usd', 'buy_rur', 'tax_rur']
        keys_total = ['sell_usd', 'buy_rur', 'tax_rur']

    year2titems = defaultdict(list)
    for titem in calc_tax(trades):
        year2titems[titem.date_sell.year].append(titem)

    def print_one(year):
        print '==={}'.format(year)
        titems = year2titems[year]
        titems.sort(key=lambda x: x.date_sell)
        print_table(year2titems[year], keys, keys_total)

    if year:
        print_one(year)
    else:
        for year in sorted(year2titems):
            print_one(year)


def process_dividends(ctx, year):
    dividends = parse_dividends(ctx.ib_reports_files)

    year2divs = defaultdict(list)
    for div in dividends:
        year2divs[div.date.year].append(div)

    keys = ['symbol', 'date', 'amount', 'tax_ib', 'tax_ib_rur', 'tax_me', 'tax_me_rur']
    keys_total = ['amount', 'tax_ib', 'tax_ib_rur', 'tax_me', 'tax_me_rur']
    if year:
        print '==={}'.format(year)
        print_table(year2divs[year], keys, keys_total)
    else:
        for year in sorted(year2divs):
            print '==={}'.format(year)
            print_table(year2divs[year], keys, keys_total)


@click.group(context_settings=dict(help_option_names=['-h', '--help']), invoke_without_command=True)
@click.option('-d', '--reports-dir', 'ib_reports_dir', default='ib_reports')
@click.pass_context
def cli(ctx, ib_reports_dir):
    """IB tax helper for Russia Federation.
    """
    class Context(object):
        def __init__(self):
            self.ib_reports_dir = 'ib_reports'

        @property
        def ib_reports_files(self):
            return glob.glob('{}/*.csv'.format(self.ib_reports_dir))

    ctx.obj = Context()

    import signal
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.option('-v', '--verbose', is_flag=True, default=False)
@click.argument('year', default=0, type=int)
@click.pass_obj
def trades(ctx, year, verbose):
    """Print trades info & tax.
    """
    process_trades(ctx, year, verbose=verbose)


@cli.command()
@click.argument('year', default=0, type=int)
@click.pass_obj
def dividends(ctx, year):
    """Print dividends info & tax.
    """
    process_dividends(ctx, year)


@cli.command()
@click.argument('year', default=0, type=int)
@click.pass_obj
def divs(ctx, year):
    """Print dividends info & tax.
    """
    process_dividends(ctx, year)


def main():
    cli()


if __name__ == '__main__':
    main()
