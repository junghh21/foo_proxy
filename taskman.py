import asyncio
import json
import os
import random
import time
import concurrent.futures

from client import AioStratumClient

def blocking_worker(job, extranonce2_hex, start_nonce, end_nonce):
	"""
	This is a synchronous, blocking function that simulates CPU-bound work.
	In a real miner, this would contain the hashing algorithm.
	It runs in a separate process and should NOT use 'await'.
	"""
	# In a real miner, you'd construct the block header here once.
	# header = build_header(job, extranonce2_hex)
	for nonce in range(start_nonce, end_nonce):
		# This simulates the intensive hashing and checking loop.
		# We check for a "found" share at a regular interval.
		if nonce > 0 and nonce % 750000 == 0:
			print(f"[Worker-{os.getpid()}] Found a potential share at nonce {nonce}!")
			# Return all necessary info to submit the share
			return (job['job_id'], extranonce2_hex, job['ntime'], f'{nonce:08x}')
	return None  # No share found in this nonce range


async def task_manager_loop (client: AioStratumClient):
	"""
	Manages mining tasks, dispatching work to a process pool executor.
	This keeps the main asyncio event loop non-blocked.
	"""
	return
	mining_tasks = []
	num_workers = os.cpu_count() or 4  # Default to 4 if cpu_count fails
	executor = concurrent.futures.ProcessPoolExecutor(max_workers=num_workers)
	print(f"[Manager] Starting miner manager with {executor._max_workers} worker processes...")
	while True:#not client._is_closed:		
		try:
			await asyncio.sleep(0)

			job = await client.job_queue.get()

			if queue_watcher in done:
				new_job = queue_watcher.result()
				
			else:
				for task in done:
					result = task.result()
					if result:
						print(f"[Manager] Share found by a worker: {result}")
						await client.submit(*result)
						break  # A share was found, stop processing others and get a new job.

			# Cancel any remaining pending tasks before the next loop iteration.
			for task in pending:
				task.cancel()
			await asyncio.gather(*pending, return_exceptions=True)

			# Wait for a new job from the server
			job = await asyncio.wait_for(client.job_queue.get(), timeout=60)
			# When a new job arrives, cancel all previous mining tasks
			if mining_tasks:
					print(f"[Manager] New job {job['job_id']} received, cancelling {len(mining_tasks)} old tasks.")
					for task in mining_tasks:
							task.cancel()
					await asyncio.gather(*mining_tasks, return_exceptions=True)
					mining_tasks.clear()
			print(f"[Manager] Got new job: {job['job_id']}. Distributing to workers...")
			extranonce2_hex = os.urandom(client.extranonce2_size).hex()
			# Divide the 4-byte nonce space among the available worker processes
			num_workers = executor._max_workers
			nonce_space = 2**32
			nonce_chunk_size = nonce_space // num_workers
			loop = asyncio.get_running_loop()
			for i in range(num_workers):
				start_nonce = i * nonce_chunk_size
				end_nonce = (i + 1) * nonce_chunk_size
				if i == num_workers - 1:
						end_nonce = nonce_space  # Ensure the last worker covers the full range
				task = loop.create_task	
				(
					loop.run_in_executor(executor, blocking_miner_worker, job, extranonce2_hex, start_nonce, end_nonce)
				)
				mining_tasks.add(task)
			
		except asyncio.CancelledError:
			break # The manager task itself was cancelled
		except asyncio.TimeoutError:
			continue # No job for 60 seconds, just continue waiting
		except Exception as e:
			print(f"[Manager] Error in manager loop: {e}")
			await asyncio.sleep(5)