import sqlite3
from collections import defaultdict

DB_PATH = "/opt/bourse-bot/data/bourse.db"
INITIAL_CAPITAL = 100_000_000

# پارامترهای استراتژی V4
START_DATE = "20250101"
MIN_VALUE = 2_000_000_000 
VOL_MULT = 2.5             
PRICE_CHANGE_MIN = 3.0     
HARD_STOP_LOSS = -0.04     
TRAILING_TRIGGER = 0.05    
TRAILING_STEP = 0.025      
MAX_HOLD_DAYS = 12         
COMMISSION = 0.01          
MAX_POSITIONS = 5          

def run_backtest():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT inscode, symbol FROM symbols")
    sym_map = {row[0]: row[1] for row in cur.fetchall()}
    
    query = """
        SELECT inscode, trade_date, close_price, volume, value
        FROM daily_prices
        WHERE close_price > 0 AND trade_date >= ?
        ORDER BY trade_date ASC
    """
    cur.execute(query, (START_DATE,))
    records = cur.fetchall()
    conn.close()

    if not records:
        print("خطا: رکوردی یافت نشد.")
        return

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
    sim_dates = set()

    for s, rows in sym_data.items():
        if len(rows) < 21:
            continue
        for i in range(20, len(rows)):
            cur_bar = rows[i]
            prev_bar = rows[i-1]
            c_date = cur_bar['date']
            sim_dates.add(c_date)

            if prev_bar['close'] <= 0:
                continue

            ret = ((cur_bar['close'] - prev_bar['close']) / prev_bar['close']) * 100
            avg_vol = sum(rows[k]['vol'] for k in range(i-20, i)) / 20.0

            if (c_date >= START_DATE and 
                cur_bar['val'] >= MIN_VALUE and 
                ret >= PRICE_CHANGE_MIN and 
                avg_vol > 0 and 
                cur_bar['vol'] >= (avg_vol * VOL_MULT)):
                daily_signals[c_date].append((s, cur_bar['close']))

    sorted_dates = sorted(list(sim_dates))
    cash = INITIAL_CAPITAL
    positions = []
    trades = []
    equity_curve = []

    sym_date_price = {s: {r['date']: r['close'] for r in rows} for s, rows in sym_data.items()}

    for cur_date in sorted_dates:
        # ۱. مدیریت خروج پوزیشن‌ها
        rem_pos = []
        for pos in positions:
            s = pos['symbol']
            curr_price = sym_date_price[s].get(cur_date, pos['entry_price'])
            pos['days_held'] += 1

            if curr_price > pos['highest_price']:
                pos['highest_price'] = curr_price

            pnl_pct = (curr_price - pos['entry_price']) / pos['entry_price']
            peak_gain_pct = (pos['highest_price'] - pos['entry_price']) / pos['entry_price']

            exit_t = False
            reason = ""

            if pnl_pct <= HARD_STOP_LOSS:
                exit_t = True
                reason = "SL"
            elif peak_gain_pct >= TRAILING_TRIGGER:
                pullback = (pos['highest_price'] - curr_price) / pos['highest_price']
                if pullback >= TRAILING_STEP:
                    exit_t = True
                    reason = "TRAILING_STOP"
            elif pos['days_held'] >= MAX_HOLD_DAYS:
                exit_t = True
                reason = "MAX_DAYS"

            if exit_t:
                sell_val = pos['shares'] * curr_price * (1 - COMMISSION)
                cash += sell_val
                pnl_rial = sell_val - (pos['shares'] * pos['entry_price'] * (1 + COMMISSION))
                trades.append({
                    'symbol': s,
                    'entry_date': pos['entry_date'],
                    'exit_date': cur_date,
                    'entry_price': pos['entry_price'],
                    'exit_price': curr_price,
                    'pnl_rial': pnl_rial,
                    'pnl_pct': pnl_pct * 100,
                    'days': pos['days_held'],
                    'reason': reason
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
                shares = int(alloc / (entry_p * (1 + COMMISSION)))
                if shares > 0:
                    cash -= shares * entry_p * (1 + COMMISSION)
                    positions.append({
                        'symbol': s,
                        'entry_date': cur_date,
                        'entry_price': entry_p,
                        'highest_price': entry_p,
                        'shares': shares,
                        'days_held': 0
                    })

        # ۳. ثبت منحنی سرمایه
        cur_equity = cash + sum(p['shares'] * sym_date_price[p['symbol']].get(cur_date, p['entry_price']) for p in positions)
        equity_curve.append((cur_date, cur_equity))

    # محاسبات آماری و ریسک
    final_eq = equity_curve[-1][1] if equity_curve else INITIAL_CAPITAL
    total_ret = ((final_eq / INITIAL_CAPITAL) - 1) * 100
    win_trades = [t for t in trades if t['pnl_rial'] > 0]
    loss_trades = [t for t in trades if t['pnl_rial'] <= 0]
    win_rate = (len(win_trades) / len(trades) * 100) if trades else 0

    # محاسبه Max Drawdown
    peak_eq = INITIAL_CAPITAL
    max_dd = 0.0
    for _, eq in equity_curve:
        if eq > peak_eq:
            peak_eq = eq
        dd = (peak_eq - eq) / peak_eq * 100
        if dd > max_dd:
            max_dd = dd

    # خروجی عملکرد کل
    print("\n" + "=" * 65)
    print("                 گزارش عملکرد استراتژی V4")
    print("=" * 65)
    print(f"سرمایه اولیه         : {INITIAL_CAPITAL:>15,.0f} ریال")
    print(f"ارزش نهایی پورتفوی   : {final_eq:>15,.0f} ریال")
    print(f"بازدهی کل دوره       : {total_ret:>14.2f}%")
    print(f"حداکثر افت سرمایه (MDD): {max_dd:>13.2f}%")
    print(f"تعداد کل معاملات    : {len(trades):>15}")
    print(f"نرخ برد (Win Rate)   : {win_rate:>14.1f}%")
    
    # دلایل خروج
    reasons = defaultdict(int)
    for t in trades:
        reasons[t['reason']] += 1
    print("\nتفکیک معاملات بر اساس نوع خروج:")
    for r in ["TRAILING_STOP", "MAX_DAYS", "SL"]:
        print(f" - {r:<15}: {reasons[r]} مورد")

    # بازدهی ماهانه
    monthly_data = defaultdict(list)
    for d, eq in equity_curve:
        m_key = f"{d[:4]}-{d[4:6]}"
        monthly_data[m_key].append(eq)

    print("\n" + "-" * 65)
    print("               تفکیک عملکرد ماهانه")
    print("-" * 65)
    prev_eq = INITIAL_CAPITAL
    for m in sorted(monthly_data.keys()):
        end_m_eq = monthly_data[m][-1]
        m_ret = ((end_m_eq / prev_eq) - 1) * 100
        print(f"ماه {m} | ارزش پایان ماه: {end_m_eq:>13,.0f} ریال | بازدهی: {m_ret:>+6.2f}%")
        prev_eq = end_m_eq

    # ۵ معامله پرسود و پرضرر
    trades_sorted = sorted(trades, key=lambda x: x['pnl_pct'], reverse=True)
    print("\n" + "-" * 65)
    print("          ۵ معامله با بالاترین بازدهی (Top 5 Wins)")
    print("-" * 65)
    for t in trades_sorted[:5]:
        print(f"{t['symbol']:<10} | ورود: {t['entry_date']} | خروج: {t['exit_date']} | سود: {t['pnl_pct']:>+6.2f}% | دلیل: {t['reason']}")

    print("\n" + "-" * 65)
    print("         ۵ معامله با بیشترین زیان (Top 5 Losses)")
    print("-" * 65)
    for t in trades_sorted[-5:]:
        print(f"{t['symbol']:<10} | ورود: {t['entry_date']} | خروج: {t['exit_date']} | زیان: {t['pnl_pct']:>+6.2f}% | دلیل: {t['reason']}")
    print("=" * 65 + "\n")

if __name__ == "__main__":
    run_backtest()
