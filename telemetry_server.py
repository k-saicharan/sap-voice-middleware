import asyncio
import json
import logging
from logging.handlers import RotatingFileHandler
import websockets
import os

# Configure Logger with both Stream (Console) and Rotating File Handler
logger = logging.getLogger("telemetry_server")
logger.setLevel(logging.INFO)

# Formatter
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# Console Handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# File Handler (Persists logs to file)
LOG_FILE = "telemetry.log"
file_handler = RotatingFileHandler(LOG_FILE, maxBytes=10*1024*1024, backupCount=5)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

clients = set()

async def broadcast(message: str):
    if not clients:
        return
    # Broadcast to all connected clients
    for client in list(clients):
        try:
            await client.send(message)
        except websockets.exceptions.ConnectionClosed:
            try:
                clients.remove(client)
            except KeyError:
                pass
        except Exception as e:
            logger.error(f"Error broadcasting to client: {e}")
            try:
                clients.remove(client)
            except KeyError:
                pass

async def handler(websocket):
    clients.add(websocket)
    logger.info(f"New client connected. Total clients: {len(clients)}")
    try:
        async for message in websocket:
            # We expect messages to be JSON strings containing event telemetry.
            # Log the raw message to the file via the logger
            logger.info(f"DATA: {message}")
            
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                continue

            await broadcast(message)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        try:
            clients.remove(websocket)
        except KeyError:
            pass
        logger.info(f"Client disconnected. Total clients: {len(clients)}")

async def main():
    # Allow port reuse just in case
    server = await websockets.serve(handler, "localhost", 8001)
    logger.info("Telemetry server started on ws://localhost:8001")
    logger.info(f"Logging telemetry data to {os.path.abspath(LOG_FILE)}")
    await server.wait_closed()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down telemetry server.")

