import sys
from pathlib import Path

# Add project root to Python path (not just src/)
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Now we can import using absolute paths from project root
from src.cli.main import cli

if __name__ == "__main__":
    cli()
