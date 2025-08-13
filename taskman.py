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
import importlib
import urls  # Your module


async def worker1(id, url, client, job, bin, no, mask):
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
			async def send_submit (data, job, no_show):
				if "result" in data:
					if data['result'] == "True":
						print(f"{id} : {data['mask']}({mask})")
						await client.job_queue.put({
							'type': 2,
							'job_id': job['job_id'],
							'extranonce2': job['extranonce2'],
							'ntime': job['ntime'], # ntime is typically part of the job
							'nonce': data['no'] # Nonce must be a hex string for submission
						})
				else:
					if no_show == 0:
						print(f"{id}({cnt}) ... {url}")

			if ".vercel.app/" in url or ":3000/" in url:
				while True:
					async with session.post(url, json={'bin': f"{bin}", 'no': f"{no}", 'mask': f"{mask}"}) as response:
						try:
							content = await response.text()
							data = json.loads(content)
							await send_submit (data, job, 1)
							no = int(data['no'], 16)+1
						except Exception as e:
							print(e)
							break
			else:
				async with session.post(url, json={'bin': f"{bin}", 'no': f"{no}", 'mask': f"{mask}"}) as response:
					cnt = 0
					async for line in response.content:
						#print(line)
						line = line.decode('utf-8')
						data = json.loads(line)
						cnt += 1
						await send_submit (data, job, cnt%10)

	except asyncio.CancelledError:
		pass
		#print(f"Worker {id} cancelled.")
	except aiohttp.ClientConnectorError as e:
		print(f"Connection error to {url}: {e}")
	except aiohttp.ClientResponseError as e:
		print(f"Client response error from {url}: {e.status} - {e.message}")
	except json.JSONDecodeError:
		print(f"JSON decode error from {url}. Response was not valid JSON.")
	except Exception as e:
		print(f"An unexpected error occurred in worker {id} for {url}: {e}")
		traceback.print_exc()

async def task_manager_loop (client: AioStratumClient):
	while True:
		try:
			#await asyncio.sleep(0)
			# Wait for a new job from the server
			job = await asyncio.wait_for(client.job_queue.get(), timeout=1)
			if client._is_closed:
				await client.shutdown_mining_tasks()
			if job['type'] == 99:
				await client.shutdown_mining_tasks()
			elif job['type'] == 2:
				await client.submit(job['job_id'], job['extranonce2'], job['ntime'], job['nonce'])
			elif job['type'] == 1:
				# When a new job arrives, cancel all previous mining tasks
				await client.shutdown_mining_tasks()
				print(f"[Manager] Got new job: {job['job_id']}. Distributing to workers...")
				job['extranonce2'] = os.urandom(client.extranonce2_size).hex()#(b'\x00'*client.extranonce2_size).hex()#

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

				#nonce_space = 2**32
				nonce_chunk_size = 200*50 # 200try 50 iter nonce_space // num_workers				#

				# for i in range(num_workers):
				# 	start_nonce = i * nonce_chunk_size
				# 	end_nonce = (i + 1) * nonce_chunk_size
				# 	if i == num_workers - 1:
				# 			end_nonce = nonce_space  # Ensure the last worker covers the full range
				bin = input_swap.hex()
				no = random.randint(0xA0000000, 0xB0000000)#os.urandom(4).hex()#"40000000"#
				#mask = client.mask.hex()  #"001D0000"
				mask_hex = f"{client.mask:08x}"
				loop = asyncio.get_running_loop()
				importlib.reload(urls)
				if client.task == "micro":
					for i, url in enumerate(urls.urls_m):
						no += nonce_chunk_size
						no_hex = f"{no:08x}"
						task = loop.create_task	(worker1(i, url, client, job, bin, no_hex, mask_hex))
						client.mining_tasks.append(task)
					for i, url in enumerate(urls.urls_brg_m):
						no += 0x10000000
						no_hex = f"{no:08x}"
						task = loop.create_task	(worker1(i, url, client, job, bin, no_hex, mask_hex))
						client.mining_tasks.append(task)
				if client.task == "bell":
					for i, url in enumerate(urls.urls_b):
						no += nonce_chunk_size
						no_hex = f"{no:08x}"
						task = loop.create_task	(worker1(i, url, client, job, bin, no_hex, mask_hex))
						client.mining_tasks.append(task)
		except asyncio.CancelledError:
			print(f"[Manager] The manager task itself was cancelled")
			break # The manager task itself was cancelled
		except asyncio.TimeoutError:
			continue # No job for 60 seconds, just continue waiting
		except Exception as e:
			print(f"[Manager] Error in manager loop: {e}")
			traceback.print_exc()
			await asyncio.sleep(5)