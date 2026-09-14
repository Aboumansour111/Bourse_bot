import sqlite3
from collections import defaultdict

DB_PATH = "/opt/bourse-bot/data/bourse.db"
INITIAL_CAPITAL = 100_000_000

# پارامترهای استراتژی V3.1
START_DATE = "20250101"   # اصلاح شده به فرمت YYYYMMDD
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

    print("1. بارگذاری نمادها...")
    cur.execute("SELECT inscode, symbol FROM symbols")
    sym_map = {row[0]: row[1] for row in cur.fetchall()}

    print(f"2. بارگذاری داده‌های قیمت از تاریخ {START_DATE} به بعد...")
    # اصلاح کوئری برای تطابق با فرمت YYYYMMDD
    query = """
        SELECT inscode, trade_date, close_price, volume, value
        FROM daily_prices
        WHERE close_price IS NOT NULL AND close_price > 0
          AND trade_date >= ?
        ORDER BY trade_date ASC
    """
    cur.execute(query, (START_DATE,))
    records = cur.fetchall()
    conn.close()

    if not records:
        print("خطا: هیچ داده‌ای با این فرمت تاریخ پیدا نشد!")
        return

    print(f"تعداد رکوردهای لود شده: {len(records):,}")

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

            if c_date >= START_DATE and cur_bar['val'] >= MIN_VALUE and ret >= PRICE_CHANGE_MIN and avg_vol > 0 and cur_bar['vol'] >= (avg_vol * VOL_MULT):
                daily_signals[c_date].append((s, cur_bar['close']))

    sorted_dates = sorted(list(sim_dates))
    print(f"3. شبیه‌سازی روی {len(sorted_dates)} روز معاملاتی معتبر...")

    positions = []
    trades = []
    equity_curve = []
    sym_date_price = {s: {r['date']: r['close'] for r in rows} for s, rows in sym_data.items()}

    for cur_date in sorted_dates:
        rem_pos = []
        for pos in positions:
            s = pos['symbol']
            curr_price = sym_date_price[s].get(cur_date, pos['entry_price'])
            pos['days_held'] += 1

            if curr_price > pos['highest_price']:
                pos['highest_price'] = curr_price

            pnl_pct = (curr_price - pos['entry_price']) / pos['entry_price']
            peak_gain_pct = (pos['highest_price'] - pos['entry_price']) / pos['entry_price']

            exit_trade = False
            exit_reason = ""

            if pnl_pct <= HARD_STOP_LOSS:
                exit_trade = True
                exit_reason = "SL"
            elif peak_gain_pct >= TRAILING_TRIGGER:
                pullback = (pos['highest_price'] - curr_price) / pos['highest_price']
                if pullback >= TRAILING_STEP:
                    exit_trade = True
                    exit_reason = "TRAILING_STOP"
            elif pos['days_held'] >= MAX_HOLD_DAYS:
                exit_trade = True
                exit_reason = "MAX_DAYS"

            if exit_trade:
                sell_val = pos['shares'] * curr_price * (1 - COMMISSION)
                cash = pos.get('cash_at_entry', 0) # This is a logic simplification for the script
                # Re-calculating cash adjustment properly
                # In a real loop, cash is global, but for this script structure:
                # We'll use a more robust way in the next iteration if needed.
                # For now, we assume 'cash' is modified in the outer scope.
                pass 

        # Note: To keep the script clean and avoid scope issues, 
        # I will rewrite the core loop logic slightly more robustly below.
        pass

# Re-writing the loop core for absolute stability in one go:
def run_backtest_final():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT inscode, symbol FROM symbols")
    sym_map = {row[0]: row[1] for row in cur.fetchall()}
    cur.execute("SELECT inscode, trade_date, close_price, volume, value FROM daily_prices WHERE close_price > 0 AND trade_date >= ? ORDER BY trade_date ASC", (START_DATE,))
    records = cur.fetchall()
    conn.close()
    if not records: return print("No data found.")
    print(f"Data loaded: {len(records)} rows.")

    sym_data = defaultdict(list)
    for inscode, trade_date, close_price, volume, value in records:
        sym_name = sym_map.get(inscode, str(inscode))
        sym_data[sym_name].append({'date': str(trade_date), 'close': float(close_price), 'vol': float(volume or 0), 'val': float(value or 0)})

    daily_signals = defaultdict(list)
    sim_dates = set()
    for s, rows in sym_data.items():
        if len(rows) < 21: continue
        for i in range(20, len(rows)):
            cur_bar = rows[i]
            prev_bar = rows[i-1]
            c_date = cur_bar['date']
            sim_dates.add(c_date)
            ret = ((cur_bar['close'] - prev_bar['close']) / prev_bar['close']) * 100
            avg_vol = sum(rows[k]['vol'] for k in range(i-20, i)) / 20.0
            if c_date >= START_DATE and cur_bar['val'] >= MIN_VALUE and ret >= PRICE_CHANGE_MIN and avg_vol > 0 and cur_bar['vol'] >= (avg_vol * VOL_MULT):
                daily_signals[c_date].append((s, cur_bar['close']))

    sorted_dates = sorted(list(sim_dates))
    cash = INITIAL_CAPITAL
    positions = []
    trades = []
    equity_curve = []
    sym_date_price = {s: {r['date']: r['close'] for r in rows} for s, rows in sym_data.items()}

    for cur_date in sorted_dates:
        # 1. Exit positions
        rem_pos = []
        for pos in positions:
            s = pos['symbol']
            curr_price = sym_date_price[s].get(cur_date, pos['entry_price'])
            pos['days_held'] += 1
            if curr_price > pos['highest_price']: pos['highest_price'] = curr_price
            pnl_pct = (curr_price - pos['entry_price']) / pos['entry_price']
            peak_gain_pct = (pos['highest_price'] - pos['entry_price']) / pos['entry_price']
            
            exit_t, reason = False, ""
            if pnl_pct <= HARD_STOP_LOSS: exit_t, reason = True, "SL"
            elif peak_gain_pct >= TRAILING_TRIGGER and ((pos['highest_price'] - curr_price)/pos['highest_price'] >= TRAILING_STEP): exit_t, reason = True, "TRAILING_STOP"
            elif pos['days_held'] >= MAX_HOLD_DAYS: exit_t, reason = True, "MAX_DAYS"
            
            if exit_t:
                sell_val = pos['shares'] * curr_price * (1 - COMMISSION)
                cash += sell_val
                trades.append({'symbol': s, 'pnl': sell_val - (pos['shares'] * pos['entry_price'] * (1+COMMISSION)), 'pnl_pct': pnl_pct, 'reason': reason})
            else: rem_pos.append(pos)
        positions = rem_pos

        # 2. Enter positions
        if len(positions) < MAX_POSITIONS and cur_date in daily_signals:
            for s, entry_p in daily_signals[cur_date][:MAX_POSITIONS-len(positions)]:
                alloc = cash / (MAX_POSITIONS - len(positions))
                shares = int(alloc / (entry_p * (1 + COMMISSION)))
                if shares > 0:
                    cash -= shares * entry_p * (1 + COMMISSION)
                    positions.append({'symbol': s, 'entry_price': entry_p, 'highest_price': entry_p, 'shares': shares, 'days_held': 0})

        # 3. Equity
        cur_equity = cash + sum(p['shares'] * sym_date_price[p['symbol']].get(cur_date, p['entry_price']) for p in positions)
        equity_curve.append((cur_date, cur_equity))

    print("\n" + "="*40 + "\n RESULTS V3.1 \n" + "="*40)
    final_eq = equity_curve[-1][1] if equity_curve else INITIAL_CAPITAL
    print(f"Final Equity: {final_eq:,.0f} ({((final_eq/INITIAL_CAPITAL)-1)*100:+.2f}%)")
    print(f"Trades: {len(trades)} | Win Rate: {(len([t for t in trades if t['pnl']>0])/len(trades)*100 if trades else 0):.1f}%")
    for r in ["SL", "TRAILING_STOP", "MAX_DAYS"]:
        print(f"Exit {r}: {len([t for t in trades if t['reason']==r])}")

run_backtest_final()
