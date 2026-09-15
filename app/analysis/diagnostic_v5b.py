import sqlite3
from collections import defaultdict

import backtest_final_v5b as v5b


DB_PATH = v5b.DB_PATH

PERIODS = [
    ("TRAIN", 20250101, 20260331),
    ("OOS",   20260401, 20260915),
]


def diagnose(data, breadth, start_date, end_date):

    stats = defaultdict(int)

    # برای اینکه بفهمیم چند signal در هر مرحله داریم
    signal_dates = set()

    for inscode, item in data.items():

        dates = item["dates"]
        closes = item["closes"]
        highs = item["highs"]
        lows = item["lows"]
        volumes = item["volumes"]

        for i in range(len(dates) - 1):

            signal_date = dates[i]
            entry_date = dates[i + 1]

            if entry_date < start_date or entry_date > end_date:
                continue

            stats["signals"] += 1
            signal_dates.add(signal_date)

            signal = v5b.technical_signal(
                closes[:i + 1],
                highs[:i + 1],
                lows[:i + 1],
                volumes[:i + 1],
            )

            if signal is None:
                continue

            stats["technical_signal"] += 1

            # هر شرط را مستقل بررسی می‌کنیم
            trend = signal["trend"]
            macd = signal["macd_hist"]
            rsi = signal["rsi"]
            vol = signal["volume_ratio"]
            quality = signal["quality"]
            atr = signal["atr"]

            if trend >= 4:
                stats["trend_4"] += 1
            else:
                continue

            if macd is not None and macd > 0:
                stats["macd_positive"] += 1
            else:
                continue

            if rsi is not None and rsi < 75:
                stats["rsi_under_75"] += 1
            else:
                continue

            if vol is not None and 1.2 <= vol <= 3.0:
                stats["volume_1.2_3"] += 1
            else:
                continue

            if quality >= 75:
                stats["quality_75"] += 1
            else:
                continue

            if atr is not None and atr > 0:
                stats["atr_valid"] += 1
            else:
                continue

            market = breadth.get(signal_date)

            if market is None:
                continue

            stats["breadth_available"] += 1

            if market["breadth"] >= 0.42:
                stats["breadth_42"] += 1
            else:
                continue

            stats["FINAL_CANDIDATE"] += 1

    return stats, signal_dates


def print_period(name, stats, signal_dates):

    print()
    print("=" * 70)
    print(f"{name}")
    print("=" * 70)

    labels = [
        ("signals",          "Raw signal opportunities"),
        ("technical_signal", "Technical signal valid"),
        ("trend_4",          "Trend >= 4"),
        ("macd_positive",    "MACD > 0"),
        ("rsi_under_75",     "RSI < 75"),
        ("volume_1.2_3",     "Volume ratio 1.2 - 3.0"),
        ("quality_75",       "Quality >= 75"),
        ("atr_valid",        "ATR valid"),
        ("breadth_available","Breadth available"),
        ("breadth_42",       "Breadth >= 0.42"),
        ("FINAL_CANDIDATE",  "FINAL CANDIDATE"),
    ]

    previous = None

    for key, label in labels:

        value = stats[key]

        if previous is None:
            retention = 100.0
        elif previous > 0:
            retention = value / previous * 100
        else:
            retention = 0.0

        print(
            f"{label:<28} "
            f"{value:>7} "
            f"({retention:>6.2f}% of previous)"
        )

        previous = value

    print()
    print("Unique signal dates:", len(signal_dates))


def main():

    conn = sqlite3.connect(DB_PATH)

    print("Loading data...")

    data = v5b.load_data(conn)

    conn.close()

    print("Valid symbols:", len(data))

    print("Building breadth...")

    breadth = v5b.build_breadth(data)

    print("Breadth dates:", len(breadth))

    for name, start_date, end_date in PERIODS:

        stats, signal_dates = diagnose(
            data,
            breadth,
            start_date,
            end_date,
        )

        print_period(
            name,
            stats,
            signal_dates,
        )


if __name__ == "__main__":
    main()
