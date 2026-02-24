import sys
from pathlib import Path

# Add project root to Python path (not just src/)
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Now we can import using absolute paths from project root
from src.cli.two_hunters import two_hunters_cli
from src.strategies.tweny import Tweny

if __name__ == "__main__":
    from datetime import datetime
    tweny = Tweny()

    from src.core.data.fetcher import DataFetcher
    fetcher = DataFetcher()

    # print(fetcher.get_latest_bars("GBPUSD."))

    tweny.symbol = "GBPUSD."
    # results = tweny.run(datetime(2025, 1, 1), datetime(2026, 2,  21))
    # TODO: 1 DEC 2025; 27 NOV 2025 needs check
    two_hunters_cli()

# TODO: FIND A BETTER WAY TO SET SL/TP FOR RECOVERY SIGNALS IN CUSTOM()