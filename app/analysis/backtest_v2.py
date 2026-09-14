import sqlite3
from collections import defaultdict

DB_PATH = "/opt/bourse-bot/data/bourse.db"
INITIAL_CAPITAL = 100_000_000

# پارامترهای استراتژی V1
MIN_VALUE = 2_000_000_000   # ارزش معاملات > ۲ میلیارد ریال
VOL_MULT = 2.5              # ضریب حجم میانگین ۲۰ روزه
PRICE_CHANGE_MIN = 3.0      # بازدهی روز ورود > ۳٪
TAKE_PROFIT = 0.08          # حد سود ۸٪
STOP_LOSS = -0.04           # حد ضرر ۴٪
MAX_HOLD_DAYS = 10          # حداکثر روز نگهداری
COMMISSION = 0.01           # کارمزد خرید و فروش (۱٪)
MAX_POSITIONS = 5           # حداکثر موقعیت باز همزمان

def run_backtest():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    print("Loading symbol mapping...")
    cur.execute("SELECT inscode, symbol FROM symbols")
    sym_map = {row[0]: row[1] for row in cur.fetchall()}

    print("Loading price and volume records from daily_prices...")
    query = """
        SELECT inscode, trade_date, close_price, volume, value
        FROM daily_prices
        WHERE close_price IS NOT NULL AND close_price > 0
        ORDER BY trade_date ASC
    """
    cur.execute(query)
    records = cur.fetchall()
    conn.close()

    print(f"Loaded {len(records):,} records. Processing indicators...")

    sym_data = defaultdict(list)
    for inscode, trade_date, close_price, volume, value in records:
        sym_name = sym_map.get(inscode, str(inscode))
        sym_data[sym_name].append({
            'date': str(trade_date),
            'close': float(close_price),
            'vol': float(volume or 0),
            'val': float(value or 0)
        })

    daily_signals = defaultdict(list)
    all_dates = set()

    for s, rows in sym_data.items():
        if len(rows) < 25:
            continue
        for i in range(20, len(rows)):
            cur_bar = rows[i]
            prev_bar = rows[i-1]
            all_dates.add(cur_bar['date'])

            if prev_bar['close'] <= 0:
                continue
            ret = ((cur_bar['close'] - prev_bar['close']) / prev_bar['close']) * 100
            avg_vol = sum(rows[k]['vol'] for k in range(i-20, i)) / 20.0

            if cur_bar['val'] >= MIN_VALUE and ret >= PRICE_CHANGE_MIN and avg_vol > 0 and cur_bar['vol'] >= (avg_vol * VOL_MULT):
                daily_signals[cur_bar['date']].append((s, cur_bar['close']))

    sorted_dates = sorted(list(all_dates))
    print(f"Executing simulation over {len(sorted_dates)} trading dates...")

    cash = INITIAL_CAPITAL
    positions = []
    trades = []
    equity_curve = []

    sym_date_price = {s: {r['date']: r['close'] for r in rows} for s, rows in sym_data.items()}

    for cur_date in sorted_dates:
        # ۱. بررسی خروج
        rem_pos = []
        for pos in positions:
            s = pos['symbol']
            curr_price = sym_date_price[s].get(cur_date, pos['entry_price'])
            pos['days_held'] += 1

            pnl_pct = (curr_price - pos['entry_price']) / pos['entry_price']
            exit_trade = False
            exit_reason = ""

            if pnl_pct >= TAKE_PROFIT:
                exit_trade = True
                exit_reason = "TP"
            elif pnl_pct <= STOP_LOSS:
                exit_trade = True
                exit_reason = "SL"
            elif pos['days_held'] >= MAX_HOLD_DAYS:
                exit_trade = True
                exit_reason = "MAX_DAYS"

            if exit_trade:
                sell_val = pos['shares'] * curr_price * (1 - COMMISSION)
                cash += sell_val
                pnl = sell_val - (pos['shares'] * pos['entry_price'])
                trades.append({
                    'symbol': s, 'entry_date': pos['entry_date'], 'exit_date': cur_date,
                    'pnl': pnl, 'pnl_pct': pnl_pct, 'reason': exit_reason
                })
            else:
                rem_pos.append(pos)
        positions = rem_pos

        # ۲. ورود به موقعیت‌های جدید
        if len(positions) < MAX_POSITIONS and cur_date in daily_signals:
            slots = MAX_POSITIONS - len(positions)
            signals = daily_signals[cur_date][:slots]
            for s, entry_p in signals:
                alloc = cash / (MAX_POSITIONS - len(positions))
                if alloc > 1_000_000:
                    cost_per_share = entry_p * (1 + COMMISSION)
                    shares = int(alloc / cost_per_share)
                    if shares > 0:
                        cash -= shares * cost_per_share
                        positions.append({
                            'symbol': s, 'entry_date': cur_date, 'entry_price': entry_p,
                            'shares': shares, 'days_held': 0
                        })

        # ۳. محاسبه ارزش جاری سبد
        cur_equity = cash
        for pos in positions:
            p = sym_date_price[pos['symbol']].get(cur_date, pos['entry_price'])
            cur_equity += pos['shares'] * p
        equity_curve.append((cur_date, cur_equity))

    # --- خروجی و گزارش ---
    print("\n" + "=" * 60)
    print(" BACKTEST V2 PERFORMANCE SUMMARY")
    print("=" * 60)
    final_equity = equity_curve[-1][1] if equity_curve else INITIAL_CAPITAL
    total_ret = ((final_equity / INITIAL_CAPITAL) - 1) * 100
    win_trades = [t for t in trades if t['pnl'] > 0]
    win_rate = (len(win_trades) / len(trades) * 100) if trades else 0

    print(f"Initial Capital : {INITIAL_CAPITAL:,.0f}")
    print(f"Final Equity    : {final_equity:,.0f}")
    print(f"Total Return    : {total_ret:+.2f}%")
    print(f"Total Trades    : {len(trades)}")
    print(f"Win Rate        : {win_rate:.1f}%")

    # تفکیک ماهانه
    monthly_data = defaultdict(list)
    for d, eq in equity_curve:
        clean_d = d.replace("-", "").replace("/", "")
        m_fmt = f"{clean_d[:4]}-{clean_d[4:6]}" if len(clean_d) >= 6 else clean_d
        monthly_data[m_fmt].append(eq)

    print("\n" + "=" * 60)
    print(" MONTHLY PERFORMANCE")
    print("=" * 60)
    prev_eq = INITIAL_CAPITAL
    annual_tracker = defaultdict(lambda: {'start': None, 'end': None})

    for m in sorted(monthly_data.keys()):
        end_eq = monthly_data[m][-1]
        m_ret = ((end_eq / prev_eq) - 1) * 100
        y = m[:4]
        if annual_tracker[y]['start'] is None:
            annual_tracker[y]['start'] = prev_eq
        annual_tracker[y]['end'] = end_eq

        print(f"{m} | End Equity: {end_eq:,.0f} | Return: {m_ret:+.2f}%")
        prev_eq = end_eq

    print("\n" + "=" * 60)
    print(" ANNUAL PERFORMANCE")
    print("=" * 60)
    for y in sorted(annual_tracker.keys()):
        s_eq = annual_tracker[y]['start']
        e_eq = annual_tracker[y]['end']
        y_ret = ((e_eq / s_eq) - 1) * 100 if s_eq else 0
        print(f"Year {y} | Return: {y_ret:+.2f}% | Final Equity: {e_eq:,.0f}")
    print("=" * 60)

if __name__ == "__main__":
    run_backtest()
