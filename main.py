import asyncio
import json
import os, sys
import random
import subprocess
import threading
import time
from taskman import task_manager_loop
from client import AioStratumClient

async def bell():
	# --- Configuration ---
	# Replace with your actual pool details
	POOL_HOST = 			"solo.ckpool.org"
	POOL_PORT = 			3333
	WALLET_ADDRESS = 	"13AM4VW2dhxYgXeQepoHkHSQuy6NgaEb94"
	WORKER_NAME = 		"hh"
	POOL_PASSWORD = 	"x"
	AGENT = 					"cpominer-25.32"

	POOL_HOST = 			'yespower.jp2.mine.leywapool.com'
	POOL_PORT = 			6322
	WALLET_ADDRESS = 	'bJzPjHhEwjLPeTJGwePQ4KpDxLH1vvZoy4'
	WORKER_NAME = 		'hh'
	POOL_PASSWORD = 	'x'
	AGENT = 					"cpuminer-oqt-25.32"

	try:
		loop = asyncio.get_running_loop()
		client = AioStratumClient(loop, "bell", POOL_HOST, POOL_PORT, f"{WALLET_ADDRESS}.{WORKER_NAME}", POOL_PASSWORD, AGENT)
		task_manager = loop.create_task(task_manager_loop(client))
		while True:
			await asyncio.sleep(0)
			if client._is_closed:
				await client.connect()
				await client.subscribe()
				await client.authorize()
				await client.subscribe_extranonce()
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

async def micro():
	# --- Configuration ---
	POOL_HOST = 			'stratum-eu.rplant.xyz'
	POOL_PORT = 			17022
	WALLET_ADDRESS = 	'MdVtFbZSobabqiZL7P4Za4ZUZBWwm3VqSS'
	WORKER_NAME = 		'hh'
	POOL_PASSWORD = 	'x'
	AGENT = 					"cpuminer-oqt-25.32"

	try:
		loop = asyncio.get_running_loop()
		client = AioStratumClient(loop, "micro", POOL_HOST, POOL_PORT, f"{WALLET_ADDRESS}.{WORKER_NAME}", POOL_PASSWORD, AGENT)
		client.task = "micro"
		client.diff_delay = 60
		task_manager = loop.create_task(task_manager_loop(client))
		while True:
			await asyncio.sleep(0)
			if client._is_closed:
				await client.connect()
				await client.subscribe()
				await client.authorize()
				await client.subscribe_extranonce()
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
		
async def main():
	asyncio.create_task(bell())
	asyncio.create_task(micro())
	while True:
		await asyncio.sleep(10) # sleep for 1 hour


def check_and_pull(repo_path):
	try:
		# Fetch latest changes from origin
		subprocess.run(["git", "-C", repo_path, "fetch"], check=True)
		# Get local and remote HEAD commit hashes
		local = subprocess.check_output(["git", "-C", repo_path, "rev-parse", "HEAD"]).strip()
		remote = subprocess.check_output(["git", "-C", repo_path, "rev-parse", "@{u}"]).strip()
		if local != remote:
			print("📥 Updates available. Pulling...")
			subprocess.run(["git", "-C", repo_path, "pull"], check=True)
			return True
		else:
			print("✅ Already up to date.")
	except subprocess.CalledProcessError as e:
		print(f"❌ Git command failed: {e}")
	except Exception as e:
		print(f"⚠️ Unexpected error: {e}")

def restart():
		print("🔁 Restarting script...")
		os.execv(sys.executable, ['python'] + sys.argv)
		
def periodic_git_check():
	while True:
		time.sleep(1800)
		if check_and_pull("./"):
			pass

if __name__ == "__main__":
	script_dir = os.path.dirname(os.path.abspath(__file__))
	os.chdir(script_dir)
	thread = threading.Thread(target=periodic_git_check, daemon=True)
	thread.start()
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		print("\n[Main] Program terminated by user.")