import asyncio
import json
import os
import random
import time
from taskman import task_manager_loop
from client import AioStratumClient

async def main():
	# --- Configuration ---
	# Replace with your actual pool details
	POOL_HOST = 	"solo.ckpool.org"
	POOL_PORT = 	3333
	BTC_ADDRESS = "13AM4VW2dhxYgXeQepoHkHSQuy6NgaEb94"
	WORKER_NAME = "MyAwesomeAsyncMiner"
	# Use a ProcessPoolExecutor for CPU-bound work to bypass the GIL.
	# The number of workers should ideally match the number of CPU cores.
	try:
		loop = asyncio.get_running_loop()
		client = AioStratumClient(loop, POOL_HOST, POOL_PORT, f"{BTC_ADDRESS}.{WORKER_NAME}", "x")
		task_manager = loop.create_task(task_manager_loop(client))
		while True:
			await asyncio.sleep(0)
			if client._is_closed:
				await client.connect()
				await client.subscribe()
				await client.authorize()
			else:
				await asyncio.sleep(30)				
	except (KeyboardInterrupt, asyncio.CancelledError):
		print("\n[Main] Shutting down...")		
	except Exception as e:
		print(f"[Main] An unexpected error occurred: {e}")
		print("[Main] Cleaning up and disconnecting.")
	finally:
		if task_manager != None:
			await client.job_queue.put({'type': 99, 'cmd': 'shutdown'})
			await task_manager
		await client.disconnect()

if __name__ == "__main__":
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		print("\n[Main] Program terminated by user.")