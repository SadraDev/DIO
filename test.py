import MetaTrader5 as mt5
from datetime import datetime, timedelta

# Connect to MT5
if not mt5.initialize():
    print("Failed to initialize MT5")
    exit()

symbol = "EURUSD."  # Adjust to your broker's symbol format

try:
    print("TIMESTAMP DEBUGGING")
    print("=" * 40)
    
    # Test 1: Raw MT5 timestamps
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 1)
    if rates:
        rate_time = rates[0]['time']
        print(f"Raw rate timestamp: {rate_time}")
        print(f"utcfromtimestamp: {datetime.utcfromtimestamp(rate_time)}")
        print(f"fromtimestamp: {datetime.fromtimestamp(rate_time)}")
    
    # Test 2: Tick timestamps
    ticks = mt5.copy_ticks_from(symbol, datetime.now(), 1, mt5.COPY_TICKS_ALL)
    if ticks:
        tick_time = ticks[0]['time']
        print(f"Raw tick timestamp: {tick_time}")
        print(f"utcfromtimestamp: {datetime.utcfromtimestamp(tick_time)}")  
        print(f"fromtimestamp: {datetime.fromtimestamp(tick_time)}")
    
    # Test 3: Current times
    print(f"System local time: {datetime.now()}")
    print(f"System UTC time: {datetime.utcnow()}")
    
    # Test 4: Account info
    account = mt5.account_info()
    if account:
        print(f"Broker server: {account.server}")
        
finally:
    mt5.shutdown()
