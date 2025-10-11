import json
import asyncio
import websockets
from typing import Dict, Set
from datetime import datetime

class LiveTradingMonitor:
    """
    WebSocket-based monitoring system for live trading
    """
    
    def __init__(self, trading_engine):
        self.trading_engine = trading_engine
        self.connected_clients: Set = set()
        self.is_running = False
        
    async def register_client(self, websocket):
        """Register new monitoring client"""
        self.connected_clients.add(websocket)
        try:
            await websocket.wait_closed()
        finally:
            self.connected_clients.remove(websocket)
    
    async def broadcast_update(self, data: Dict):
        """Broadcast update to all connected clients"""
        if self.connected_clients:
            message = json.dumps({
                'timestamp': datetime.now().isoformat(),
                'type': 'trading_update',
                'data': data
            })
            
            # Send to all clients
            disconnected = set()
            for client in self.connected_clients:
                try:
                    await client.send(message)
                except websockets.exceptions.ConnectionClosed:
                    disconnected.add(client)
            
            # Clean up disconnected clients
            self.connected_clients -= disconnected
    
    async def start_monitoring(self, host='localhost', port=8765):
        """Start monitoring server"""
        self.is_running = True
        
        async def handle_client(websocket, path):
            await self.register_client(websocket)
        
        # Start periodic status updates
        asyncio.create_task(self._periodic_updates())
        
        # Start WebSocket server
        start_server = websockets.serve(handle_client, host, port)
        print(f"🔍 Live trading monitor started on ws://{host}:{port}")
        
        await start_server
        await asyncio.Future()  # Run forever
    
    async def _periodic_updates(self):
        """Send periodic status updates"""
        while self.is_running:
            try:
                status = self.trading_engine.get_trading_status()
                await self.broadcast_update(status)
                await asyncio.sleep(5)  # Update every 5 seconds
            except Exception as e:
                print(f"Error in periodic updates: {e}")
                await asyncio.sleep(10)
