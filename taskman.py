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


async def worker1(id, url, client, job, no):
	cert_file = 'cert.pem'
	key_file = 'key.pem'
	ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
	ssl_context.check_hostname = False
	ssl_context.verify_mode = ssl.CERT_NONE
	ssl_context.load_cert_chain(certfile='cert.pem', keyfile='key.pem')
	#print(f"Successfully loaded certificate from '{cert_file}' and key from '{key_file}'.")

	try:
		async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90)) as session:
			async def send_submit (data, job, no_show):
				if "result" in data:
					#print(data)
					if data['result'] == "True":
						algo, job_id, bin, mask = struct.unpack("II32sI", bytes.fromhex(data['bin']))
						cur_job_id = int(job['job_id'], 16)
						if cur_job_id == job_id:
							print(f"{client.name}({id}) : {mask:08x} <= {job['mask']}")
							await client.submit(job['job_id'], job['extranonce2'], job['ntime'], data['no'])
						else:
							print (f"Invalid Job {cur_job_id:08x} : {job_id:08x}")
					if no_show == 0:
						print(f"{client.name}({cnt}) ... {url}")

			ALGO = struct.pack("<I", client.algo).hex()
			JOB_ID = int(job['job_id'], 16).to_bytes(4, byteorder='little').hex()
			MASK = struct.pack("<I", client.mask).hex()
			COUNT = struct.pack("<I", client.hash_cnt).hex()
			job['bin'] = ALGO + \
										JOB_ID + \
										job['bin'] + \
										MASK + \
										COUNT
			if ".vercel.app/" in url or ":3000/" in url:
				while True:
					async with session.post(url, 
								json={'bin': job['bin'], 'no': f"{no:08x}"}, 
								ssl=ssl_context) as response:
						try:
							content = await response.text()
							data = json.loads(content)
							await send_submit (data, job, 1)
							no = int(data['no'], 16)+1
						except Exception as e:
							print(e)
							break
			else:
				async with session.post(url, 
							json={'bin': job['bin'], 'no': f"{no:08x}", 'id': f"{id:08x}"}, 
							ssl=ssl_context) as response:
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
	except  asyncio.TimeoutError:
		print(f"Request timed out! {url}.")
	except Exception as e:
		print(f"An unexpected error occurred in worker {id} for {url}: {e}")
		traceback.print_exc()

async def task_manager_loop (CLIENT_NAME, CLIENT_URLS, CLIENT_HASH_CNT, CLIENT_BLOCK_TIME, ALGO, POOL_HOST, POOL_PORT, WALLET_ADDRESS, WORKER_NAME, POOL_PASSWORD, AGENT):
	client = AioStratumClient(CLIENT_NAME, CLIENT_URLS, CLIENT_HASH_CNT, CLIENT_BLOCK_TIME, ALGO, POOL_HOST, POOL_PORT, f"{WALLET_ADDRESS}.{WORKER_NAME}", POOL_PASSWORD, AGENT)
	while True:
		try:
			try:
				job = await asyncio.wait_for(client.job_queue.get(), timeout=1)
				client.job_queue.task_done()
			except asyncio.TimeoutError:
				if client._is_closed:
					await client.shutdown_mining_tasks()
					await asyncio.sleep(5)
					await client.connect()
					await client.subscribe()
					await client.authorize()
					await client.subscribe_extranonce()
				continue
			if job['type'] == 1:
				# When a new job arrives, cancel all previous mining tasks
				await client.shutdown_mining_tasks()
				print(f"[{client.name}] Got new job: {job['job_id']}.")			#
				no = random.randint(0xA0000000, 0xB0000000)#os.urandom(4).hex()#"40000000"#
				for i, url in enumerate(client.urls):
					task = asyncio.create_task(worker1(i, url, client, job, no))
					client.mining_tasks.append(task)
					no += client.hash_cnt*client.block_time
		except (KeyboardInterrupt, asyncio.CancelledError):
			print(f"[Manager] The manager task itself was cancelled")
			await client.shutdown_mining_tasks()
			break # The manager task itself was cancelled
		except Exception as e:
			print(f"[Manager] Error in manager loop: {e}")
			traceback.print_exc()