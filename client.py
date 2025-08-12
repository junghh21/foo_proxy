import asyncio
import json
import os
import random
import time

class StratumError(Exception):
	"""Custom exception for Stratum-related errors."""
	def __init__(self, error_details):
		if isinstance(error_details, list) and len(error_details) >= 2:
				self.code = error_details[0]
				self.message = error_details[1]
		else:
				self.code = -1
				self.message = str(error_details)
		super().__init__(f"Stratum Error Code {self.code}: {self.message}")


class AioStratumClient:
	"""
	An asynchronous Stratum client using asyncio.

	This client handles the Stratum protocol (v1) over a raw TCP socket.
	While the request mentioned 'aiohttp', aiohttp is an HTTP client/server
	library. For raw TCP socket communication like Stratum, Python's built-in
	'asyncio' library is the correct and standard tool.
	"""

	def __init__(self, loop, host, port, username, password, agent):
		self.loop = loop
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

		# Concurrency and communication
		self._request_id = 1
		self._pending_requests = {}
		self.job_queue = asyncio.Queue()
		self._is_closed = True
	
		self.mask = 0x007F0000
		self.accept_cnt = 0
		self.reject_cnt = 0
		self.task = "bell"
		self.diff_delay = 30

	# async def _lower_mask(self):
	# 	while True:
	# 		await asyncio.sleep(self.diff_delay)
	# 		if self.accept_cnt == 0:				
	# 			self.mask *= 2
	# 			if self.mask > 0x007F0000:
	# 				self.mask = 0x007F0000	
	# 			print(f"========DOWN{self.mask=:08x}")
	# 		self.accept_cnt = 0
	# 		if self.reject_cnt > 2:				
	# 			self.reject_cnt = 0
	# 			self.mask //= 2
	# 			if self.mask < 0x0000FF00:
	# 				self.mask = 0x0000FF00
	# 			print(f"========UP{self.mask=:08x}")

	async def connect(self):
		"""Establishes a connection to the Stratum server."""
		print(f"[Client] Connecting to {self.host}:{self.port}...")
		if not self._is_closed:
			return False
		try:
			self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
			print("[Client] Connected successfully.")
			# Start the listener task to handle incoming messages
			self.loop.create_task(self._listen())
			#self.loop.create_task(self._lower_mask())
			self._is_closed = False
			return True
		except (OSError, asyncio.TimeoutError) as e:
			print(f"[Client] Connection failed: {e}")
			return False

	async def disconnect(self):
		"""Closes the connection to the server."""
		if self._is_closed:
			return
		self._is_closed = True
		if self.writer:
			print("[Client] Disconnecting...")
			self.writer.close()
			try:
				await self.writer.wait_closed()
			except Exception as e:
				print(f"[Client] Error during wait_closed: {e}")
			self.writer = None
			self.reader = None
			print("[Client] Disconnected.")

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
		
		future = self.loop.create_future()
		self._pending_requests[request_id] = future

		message = json.dumps(payload) + '\n'
		print(f"[Client] -> {message.strip()}")
		self.writer.write(message.encode('utf-8'))
		await self.writer.drain()

		try:
			# Wait for the response from the listener task
			result = await asyncio.wait_for(future, timeout=30.0)
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
						data = await self.reader.readline()
						if not data:
								if not self._is_closed:
										print("[Client] Connection closed by server.")
										await self.disconnect()
								break
						message = data.decode('utf-8').strip()
						if not message:
								continue
						print(f"[Client] <- {message}")
						response = json.loads(message)
						await self._handle_response(response)
				except (ConnectionResetError, BrokenPipeError):
						if not self._is_closed:
								print("[Client] Connection lost.")
				except json.JSONDecodeError:
						print(f"[Client] Error decoding JSON: {message}")
				except Exception as e:
						if not self._is_closed:
								print(f"[Client] An unexpected error occurred in listener: {e}")
				finally:
					await self.disconnect()
					await self.connect()
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
				else:
						print(f"[Client] Unhandled notification: {method}")
		else:
				print(f"[Client] Received unknown message: {response}")

	async def _handle_notify(self, params):
		"""Handles 'mining.notify' messages."""
		(job_id, prevhash, coinb1, coinb2, merkle_branch, version, nbits, ntime, clean_jobs) = params
		self.job = {
				"type": 1,
				"job_id": job_id,
				"prevhash": prevhash,
				"coinb1": coinb1,
				"coinb2": coinb2,
				"merkle_branch": merkle_branch,
				"version": version,
				"nbits": nbits,
				"ntime": ntime,
				"clean_jobs": clean_jobs,
		}
		print(f"[Client] New job received: {job_id}")
		# # If it's a clean job, we should clear the queue to prioritize this one.
		# if clean_jobs:
		# 		while not self.job_queue.empty():
		# 				try:
		# 						self.job_queue.get_nowait()
		# 				except asyncio.QueueEmpty:
		# 						break
		await self.job_queue.put(self.job)

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
		print(f"[Client] New pool difficulty: {self.pool_difficulty}, {self.mask:08x}, {pool_rate=:.2f} H/s")

	async def subscribe(self):
		"""Subscribes to mining notifications."""
		print("[Client] Subscribing to pool...")
		result = await self._send_request('mining.subscribe', [self.agent])
		# result = ([('mining.notify', 'subscription_id'), ...], extranonce1, extranonce2_size)
		(subscriptions, self.extranonce1, self.extranonce2_size) = result
		# Extract session ID from subscriptions if needed by the pool
		for sub in subscriptions:
				if sub[0] == 'mining.notify':
						self.session_id = sub[1]
						break
		print("[Client] Subscribed successfully!")
		print(f"  - Session ID: {self.session_id}")
		print(f"  - Extranonce1: {self.extranonce1}")
		print(f"  - Extranonce2 Size: {self.extranonce2_size}")
		return True

	async def authorize(self):
		"""Authorizes the worker."""
		print(f"[Client] Authorizing worker: {self.username}...")
		result = await self._send_request('mining.authorize', [self.username, self.password])
		if result:
			print("[Client] Worker authorized.")
			return True
		else:
			print("[Client] Worker authorization failed.")
			return False
	
	async def subscribe_extranonce(self):
		print(f"[Client] subscribe_extranonce...")
		result = await self._send_request('mining.extranonce.subscribe', [])
		if result:
			print("[Client] subscribe_extranonce authorized.")
			return True
		else:
			print("[Client] subscribe_extranonce failed.")
			return False

	async def submit(self, job_id, extranonce2, ntime, nonce):
		"""Submits a found share to the pool."""
		params = [self.username, job_id, extranonce2, ntime, nonce]
		print(f"[Client] Submitting share for job {job_id} with nonce {nonce}...")
		try:
			result = await self._send_request('mining.submit', params)
			if result:
				print(f"[Client] Share ACCEPTED for job {job_id}.")
				self.accept_cnt += 1
				return True
			else:
				print(f"[Client] Share REJECTED for job {job_id} (result: {result}).")
				return False
		except StratumError as e:
			print(f"[Client] Share REJECTED for job {job_id} with error: {e}")
			if e.code in [23, 26]:
				self.reject_cnt += 1
			return False
