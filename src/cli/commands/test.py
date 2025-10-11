from src.core.data.fetcher import DataFetcher
from src.core.execution.mt5_connection import MT5Connection

def run_system_tests(
    test_connection: bool = False,
    test_data: bool = False,
    test_strategy: bool = False,
    verbose: bool = False
):
    """Run system tests and diagnostics"""
    results = {}
    
    if test_connection:
        try:
            conn = MT5Connection()
            success = conn.test_connection()
            results['connection'] = {
                'passed': success,
                'message': 'Connection test passed' if success else 'Connection failed'
            }
        except Exception as e:
            results['connection'] = {'passed': False, 'message': str(e)}
    
    if test_data:
        try:
            fetcher = DataFetcher()
            symbols = fetcher.get_available_symbols()
            results['data'] = {
                'passed': len(symbols) > 0,
                'message': f'Found {len(symbols)} symbols' if symbols else 'No symbols found'
            }
        except Exception as e:
            results['data'] = {'passed': False, 'message': str(e)}
    
    return results
"""System tests command implementation"""
from src.core.data.fetcher import DataFetcher
from src.core.execution.mt5_connection import MT5Connection

def run_system_tests(
    test_connection: bool = False,
    test_data: bool = False,
    test_strategy: bool = False,
    verbose: bool = False
):
    """Run system tests and diagnostics"""
    results = {}
    
    if test_connection:
        try:
            conn = MT5Connection()
            success = conn.test_connection()
            results['connection'] = {
                'passed': success,
                'message': 'Connection test passed' if success else 'Connection failed'
            }
        except Exception as e:
            results['connection'] = {'passed': False, 'message': str(e)}
    
    if test_data:
        try:
            fetcher = DataFetcher()
            symbols = fetcher.get_available_symbols()
            results['data'] = {
                'passed': len(symbols) > 0,
                'message': f'Found {len(symbols)} symbols' if symbols else 'No symbols found'
            }
        except Exception as e:
            results['data'] = {'passed': False, 'message': str(e)}
    
    return results
