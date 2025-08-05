import asyncio
import json
import os
import random
import time
import concurrent.futures
import threading
import traceback	
import aiohttp
import hashlib
import struct
import ssl
from client import AioStratumClient

async def worker1(id, queue, job, input_swap, start_nonce):
	url = "https://127.0.0.1:8001/params"
	url = "https://foo-job.onrender.com/params"

	bin = input_swap.hex()
	no = 	os.urandom(4).hex()#"40000000"#
	mask = 	"00050000"

	cert_file = 'cert.pem'
	key_file = 'key.pem'
	ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
	ssl_context.check_hostname = False
	ssl_context.verify_mode = ssl.CERT_NONE
	ssl_context.load_cert_chain(certfile='cert.pem', keyfile='key.pem')
	#print(f"Successfully loaded certificate from '{cert_file}' and key from '{key_file}'.")
	
	try:
		connector = aiohttp.TCPConnector(ssl=ssl_context)
		async with aiohttp.ClientSession(connector=connector) as session:
			async with session.post(url, json={'bin': f"{bin}", 'no': f"{no}", 'mask': f"{mask}"}) as response:
				async for line in response.content:
					line = line.decode('utf-8')
					data = json.loads(line)
					#print(data)
					if data['result'] == "True":
						await queue.put({
							'type': 2,
							'job_id': job['job_id'],
							'extranonce2': job['extranonce2'],
							'ntime': job['ntime'], # ntime is typically part of the job
							'nonce': data['no'] # Nonce must be a hex string for submission
						})
					else:
						print(f"{id} ...")
	except asyncio.CancelledError:
		print(f"Worker {id} cancelled.")
	except:
		pass

async def worker2(id, queue, job, input_swap, start_nonce):
	url = "https://foo-render-hh.onrender.com/params"

	bin = input_swap.hex()
	no = 	os.urandom(4).hex()#"40000000"#
	mask = 	"00050000"

	cert_file = 'cert.pem'
	key_file = 'key.pem'
	ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
	ssl_context.check_hostname = False
	ssl_context.verify_mode = ssl.CERT_NONE
	ssl_context.load_cert_chain(certfile='cert.pem', keyfile='key.pem')
	#print(f"Successfully loaded certificate from '{cert_file}' and key from '{key_file}'.")
	
	try:
		connector = aiohttp.TCPConnector(ssl=ssl_context)
		async with aiohttp.ClientSession(connector=connector) as session:
			async with session.post(url, json={'bin': f"{bin}", 'no': f"{no}", 'mask': f"{mask}"}) as response:
				async for line in response.content:
					line = line.decode('utf-8')
					data = json.loads(line)
					#print(data)
					if data['result'] == "True":
						await queue.put({
							'type': 2,
							'job_id': job['job_id'],
							'extranonce2': job['extranonce2'],
							'ntime': job['ntime'], # ntime is typically part of the job
							'nonce': data['no'] # Nonce must be a hex string for submission
						})
					else:
						print(f"{id} ...")
	except asyncio.CancelledError:
		print(f"Worker {id} cancelled.")
	except:
		pass

mining_tasks = []
async def shutdown_mining_tasks():
	global mining_tasks
	if len(mining_tasks) > 0:
		print(f"[Manager] New job cancelling {len(mining_tasks)} old tasks.")
		for task in mining_tasks:
			task.cancel()
		results = await asyncio.gather(*mining_tasks, return_exceptions=True)
		mining_tasks = []
		#print(results)
	
async def task_manager_loop (client: AioStratumClient):
	global mining_tasks
	"""
	Manages mining tasks, dispatching work to a process pool executor.
	This keeps the main asyncio event loop non-blocked.
	"""	
	num_workers = 8#os.cpu_count() or 4  # Default to 4 if cpu_count fails
	while True:		
		try:
			#await asyncio.sleep(0)
			# Wait for a new job from the server
			job = await asyncio.wait_for(client.job_queue.get(), timeout=1)
			if client._is_closed:
				await shutdown_mining_tasks()
			if job['type'] == 99:
				await shutdown_mining_tasks()
			elif job['type'] == 2:
				await client.submit(job['job_id'], job['extranonce2'], job['ntime'], job['nonce'])			
			elif job['type'] == 1:
				# When a new job arrives, cancel all previous mining tasks
				await shutdown_mining_tasks()
				print(f"[Manager] Got new job: {job['job_id']}. Distributing to workers...")
				job['extranonce2'] = (b'\x00'*client.extranonce2_size).hex()#os.urandom(client.extranonce2_size).hex()

				coinbase_bin = bytes.fromhex(job['coinb1'] + client.extranonce1 + job['extranonce2'] + job['coinb2'])
				coinbase_hash_bin = hashlib.sha256(hashlib.sha256(coinbase_bin).digest()).digest()
				#coinbase_hash_bin = hashlib.sha256(coinbase_bin).digest()

				merkle_root_bin = coinbase_hash_bin
				for branch in job['merkle_branch']:
					merkle_root_bin = hashlib.sha256(hashlib.sha256((merkle_root_bin + bytes.fromhex(branch))).digest()).digest()
				merkle_root_1 = struct.unpack("<8I", merkle_root_bin)
				#print([f"{d:08x}" for d in merkle_root_1])
				merkle_root = ''.join([f"{d:08x}" for d in merkle_root_1])
				header_bin = bytes.fromhex(job['version']) \
										+ bytes.fromhex(job['prevhash']) \
										+ bytes.fromhex(merkle_root) \
										+ bytes.fromhex(job['ntime']) \
										+ bytes.fromhex(job['nbits'])

				nonce = "00000000"
				nonce_bin = bytes.fromhex(nonce)
				input = header_bin+nonce_bin

				inputs = struct.unpack("<20I", input)
				#print([f"{d:08x}" for d in inputs[:10]])
				#print([f"{d:08x}" for d in inputs[10:]])
				input_swap = struct.pack(">20I", *inputs)
		
				nonce_space = 2**32
				nonce_chunk_size = nonce_space // num_workers
				loop = asyncio.get_running_loop()
				for i in range(num_workers):
					start_nonce = i * nonce_chunk_size
					end_nonce = (i + 1) * nonce_chunk_size
					if i == num_workers - 1:
							end_nonce = nonce_space  # Ensure the last worker covers the full range
					task = loop.create_task	(worker1(i, client.job_queue, job, input_swap, start_nonce))
					mining_tasks.append(task)				
					task = loop.create_task	(worker2(i+4, client.job_queue, job, input_swap, start_nonce))
					mining_tasks.append(task)		
		except asyncio.CancelledError:
			break # The manager task itself was cancelled
		except asyncio.TimeoutError:
			continue # No job for 60 seconds, just continue waiting
		except Exception as e:
			print(f"[Manager] Error in manager loop: {e}")
			traceback.print_exc()	
			await asyncio.sleep(5)