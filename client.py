import asyncio
import json
import os
import random
import time
import traceback
import hashlib
import struct

class StratumError(Exception):
	"""Custom exception for Stratum-related errors."""
	def __init__(self, error_details):
		if isinstance(error_details, list) and len(error_details) >= 2:
				self.code = error_details[0]
				self.message = error_details[1]
		else:
				self.code = -1
				self.message = str(error_details)
		super().__init__(f"Error {self.code}: {self.message}")


class AioStratumClient:
	"""
	An asynchronous Stratum client using asyncio.

	This client handles the Stratum protocol (v1) over a raw TCP socket.
	While the request mentioned 'aiohttp', aiohttp is an HTTP client/server
	library. For raw TCP socket communication like Stratum, Python's built-in
	'asyncio' library is the correct and standard tool.
	"""

	def __init__(self, name, urls, hash_cnt, block_time, algo, host, port, username, password, agent):
		self.name = name
		self.urls = urls
		self.hash_cnt = hash_cnt
		self.block_time = block_time
		self.host = host
		self.port = port
		self.username = username
		self.password = password
		self.agent = agent

		self.reader = None
		self.writer = None

		# Stratum state
		self.session_id = None
		self.extranonce1 = None
		self.extranonce2_size = None
		self.target = None
		self.pool_difficulty = None
		self.job = None
		self.accept_cnt = 0
		self.reject_cnt = 0
		# Concurrency and communication
		self._request_id = 1
		self._pending_requests = {}
		self.job_queue = asyncio.Queue()
		self._is_closed = True

		self.mask = 0x007F0000
		self.algo = algo

		self.mining_tasks = []

	async def shutdown_mining_tasks(self):
		if len(self.mining_tasks) > 0:
			#print(f"[{self.name}] New job cancelling {len(self.mining_tasks)} old tasks.")
			for task in self.mining_tasks:
				task.cancel()
			results = await asyncio.gather(*self.mining_tasks, return_exceptions=True)
			self.mining_tasks = []
			#print(results)

	async def connect(self):
		"""Establishes a connection to the Stratum server."""
		print(f"[{self.name}] Connecting to {self.host}:{self.port}...")
		if not self._is_closed:
			return False
		try:
			self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
			print(f"[{self.name}] Connected successfully.")
			# Start the listener task to handle incoming messages
			asyncio.create_task(self._listen())
			self._is_closed = False
			return True
		except (OSError, asyncio.TimeoutError) as e:
			print(f"[{self.name}] Connection failed: {e}")
			return False

	async def disconnect(self):
		"""Closes the connection to the server."""
		if self._is_closed:
			return
		self._is_closed = True
		if self.writer:
			print(f"[{self.name}] Disconnecting...")
			self.writer.close()
			try:
				await self.writer.wait_closed()
			except Exception as e:
				print(f"[{self.name}] Error during wait_closed: {e}")
			self.writer = None
			self.reader = None
			print(f"[{self.name}] Disconnected.")

	async def _send_request(self, method, params=None):
		"""Sends a JSON-RPC request and waits for the response."""
		if not self.writer:
			raise ConnectionError("Not connected to the server.")

		request_id = self._request_id
		self._request_id += 1

		payload = {
			"id": request_id,
			"method": method,
			"params": params or []
		}
		loop = asyncio.get_running_loop()
		future = loop.create_future()
		self._pending_requests[request_id] = future

		message = json.dumps(payload) + '\n'
		#print(f"[{self.name}] -> {message.strip()}")
		self.writer.write(message.encode('utf-8'))
		await self.writer.drain()

		try:
			# Wait for the response from the listener task
			result = await asyncio.wait_for(future, timeout=60.0)
			return result
		except asyncio.TimeoutError:
			self._pending_requests.pop(request_id, None)
			raise ConnectionAbortedError(f"Request {request_id} ({method}) timed out")
		except StratumError as e:
			raise e

	async def _listen(self):
		"""Listens for incoming messages from the server."""
		while not self._is_closed and self.reader:
				try:
						data = await asyncio.wait_for(self.reader.readline(), 90)
						if not data:
										print(f"[{self.name}] Connection closed by server. disconnect")
										await self.disconnect()
										return
						message = data.decode('utf-8').strip()
						if not message:
								continue
						#print(f"[{self.name}] <- {message}")
						response = json.loads(message)
						await self._handle_response(response)
				except asyncio.TimeoutError:
								print(f"[{self.name}] Connection Timeout  disconnect.")
								await self.disconnect()
								return
				except (ConnectionResetError, BrokenPipeError):
								print(f"[{self.name}] Connection lost. disconnect")
								await self.disconnect()
								return
				except json.JSONDecodeError:
						print(f"[{self.name}] Error decoding JSON: {message}")
				except Exception as e:
								print(f"[{self.name}] An unexpected error occurred in listener: {e} disconnect")
								traceback.print_exc()
								await self.disconnect()
								return


	async def _handle_response(self, response):
		"""Handles both RPC responses and server notifications."""
		request_id = response.get('id')
		if request_id is not None and request_id in self._pending_requests:
				future = self._pending_requests.pop(request_id)
				error = response.get('error')
				if error:
						future.set_exception(StratumError(error))
				else:
						future.set_result(response.get('result'))
		elif 'method' in response:
				# This is a server notification
				method = response.get('method')
				params = response.get('params', [])
				if method == 'mining.notify':
						await self._handle_notify(params)
				elif method == 'mining.set_difficulty':
						await self._handle_set_difficulty(params)
				elif method == 'mining.ping':
						payload = {
							"id": request_id,
							"result": "pong",
							"error": 'null'
						}
						message = json.dumps(payload) + '\n'
						self.writer.write(message.encode('utf-8'))
						await self.writer.drain()
				else:
						print(f"[{self.name}] Unhandled notification: {method}")
		else:
				print(f"[{self.name}] Received unknown message: {response}")

	async def _handle_notify(self, params):
		"""Handles 'mining.notify' messages."""
		(job_id, prevhash, coinb1, coinb2, merkle_branch, version, nbits, ntime, clean_jobs) = params
		job = {
				"type": 1,
				"job_id": job_id,
				"ntime": ntime,
		}
		#print(f"[{self.name}] New job received: {job_id}")
		job['extranonce2'] = os.urandom(self.extranonce2_size).hex()#(b'\x00'*client.extranonce2_size).hex()#
		coinbase_bin = bytes.fromhex(coinb1 + self.extranonce1 + job['extranonce2'] + coinb2)
		coinbase_hash_bin = hashlib.sha256(hashlib.sha256(coinbase_bin).digest()).digest()
		merkle_root_bin = coinbase_hash_bin
		if len(merkle_branch) > 0:
			print(f"merkel => ({len(merkle_branch)})")
		for branch in merkle_branch:
			merkle_root_bin = hashlib.sha256(hashlib.sha256((merkle_root_bin + bytes.fromhex(branch))).digest()).digest()
		merkle_root_1 = struct.unpack("<8I", merkle_root_bin)
		#print([f"{d:08x}" for d in merkle_root_1])
		merkle_root = ''.join([f"{d:08x}" for d in merkle_root_1])
		header_bin = bytes.fromhex(version) \
								+ bytes.fromhex(prevhash) \
								+ bytes.fromhex(merkle_root) \
								+ bytes.fromhex(ntime) \
								+ bytes.fromhex(nbits)

		nonce = "00000000"
		nonce_bin = bytes.fromhex(nonce)
		input = header_bin+nonce_bin

		inputs = struct.unpack("<20I", input)
		#print([f"{d:08x}" for d in inputs[:10]])
		#print([f"{d:08x}" for d in inputs[10:]])
		input_swap = struct.pack(">20I", *inputs)

		job['bin'] = input_swap.hex()
		job['mask']	=	f"{self.mask:08x}"
		await self.job_queue.put(job)

	async def _handle_set_difficulty(self, params):
		"""Handles 'mining.set_difficulty' messages."""
		self.pool_difficulty = params[0]
		# In a real miner, you'd convert this to a target.
		# For BTC: target = 0x00000000FFFF0000000000000000000000000000000000000000000000000000 / difficulty

		max_target_int = int("00FFFF00000000000000000000000000000000000000000000000000000000", 16)
		max_target_int2 = max_target_int
		pool_diff = self.pool_difficulty
		pool_int = int(max_target_int2/pool_diff)
		pool_h64 = f"{pool_int:064x}"
		pool_diff = max_target_int/pool_int
		pool_rate = pool_diff * 2**32 / 60
		self.mask = int(pool_h64[:8], 16)
		print(f"[{self.name}] New pool difficulty: {self.pool_difficulty}, {self.mask:08x}, {pool_rate=:.2f} H/s")

	async def subscribe(self):
		"""Subscribes to mining notifications."""
		print(f"[{self.name}] Subscribing to pool...")
		result = await self._send_request('mining.subscribe', [self.agent])
		# result = ([('mining.notify', 'subscription_id'), ...], extranonce1, extranonce2_size)
		(subscriptions, self.extranonce1, self.extranonce2_size) = result
		# Extract session ID from subscriptions if needed by the pool
		for sub in subscriptions:
				if sub[0] == 'mining.notify':
						self.session_id = sub[1]
						break
		print(f"[{self.name}] Subscribed successfully!")
		print(f"  - Session ID: {self.session_id}")
		print(f"  - Extranonce1: {self.extranonce1}")
		print(f"  - Extranonce2 Size: {self.extranonce2_size}")
		return True

	async def authorize(self):
		"""Authorizes the worker."""
		print(f"[{self.name}] Authorizing worker: {self.username}...")
		result = await self._send_request('mining.authorize', [self.username, self.password])
		if result:
			print(f"[{self.name}] Worker authorized.")
			return True
		else:
			print(f"[{self.name}] Worker authorization failed.")
			return False

	async def subscribe_extranonce(self):
		print(f"[{self.name}] subscribe_extranonce...")
		result = await self._send_request('mining.extranonce.subscribe', [])
		if result:
			print(f"[{self.name}] subscribe_extranonce authorized.")
			return True
		else:
			print(f"[{self.name}] subscribe_extranonce failed.")
			return False

	async def submit(self, job_id, extranonce2, ntime, nonce):
		"""Submits a found share to the pool."""
		params = [self.username, job_id, extranonce2, ntime, nonce]
		#print(f"[{self.name}] Submitting share for job {job_id} with nonce {nonce}...")
		try:
			result = await self._send_request('mining.submit', params)
			if result:
				print(f"[{self.name}] Share ACCEPTED for job {job_id}.")
				self.accept_cnt += 1
				return True
			else:
				print(f"[{self.name}] Share REJECTED for job {job_id} (result: {result}).")
				return False
		except StratumError as e:
			print(f"[{self.name}] Share REJECTED for job {job_id} with error: {e}")
			if e.code in [23, 26]:
				self.reject_cnt += 1
			return False
