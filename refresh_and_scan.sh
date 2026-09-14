#!/bin/bash
echo "Updating prices..."
python3 app/collector/price_collector.py
echo "Running analysis..."
python3 app/scanner/scanner.py  # (نام اسکریپت اسکنر خود را چک کنید)
echo "Done."
