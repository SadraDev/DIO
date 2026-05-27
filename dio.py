import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.cli.two_hunters import two_hunters_cli

if __name__ == "__main__":
    two_hunters_cli()
