import sys
from pathlib import Path

# Add project root to Python path (not just src/)
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Now we can import using absolute paths from project root
from src.cli.main import cli

if __name__ == "__main__":
    cli()

# TODO: the live runner and backtester does not generate signals
# TODO: the initial balance in the status command could be the accounts balance
# TODO: check the correctness of configurations about times
# TODO: add the plots to the backtest command
# TODO: add switching between accounts and account info to commands
# TODO: ask about monitoring and how its done
# TODO: ask about commands
# TODO: remove dry-run command entirely (there is backtest command for that)
# TODO: ask about portfolio
# TODO: ask what is chart_helpers.py used for
# TODO: test command is simple, test everything
# TODO: merge data, logs, outputs, reports to one folder
# TODO: todo in two_hunters.py