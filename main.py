import asyncio
import json
import os, sys
import random
import subprocess
import threading
import time
from taskman import task_manager_loop

async def main():
	main_tasks = []
	POOL_HOST = 			'yespower.jp2.mine.leywapool.com'
	POOL_PORT = 			6322
	WALLET_ADDRESS = 	'bJzPjHhEwjLPeTJGwePQ4KpDxLH1vvZoy4'
	WORKER_NAME = 		'hh'
	POOL_PASSWORD = 	'x'
	AGENT = 					"cpuminer-oqt-25.32"
	#task = asyncio.create_task(task_manager_loop("bell", POOL_HOST, POOL_PORT, WALLET_ADDRESS, WORKER_NAME, POOL_PASSWORD, AGENT))
	#main_tasks.append(task)

	POOL_HOST = 			'stratum-eu.rplant.xyz'
	POOL_PORT = 			17022
	WALLET_ADDRESS = 	'MdVtFbZSobabqiZL7P4Za4ZUZBWwm3VqSS'
	WORKER_NAME = 		'hh'
	POOL_PASSWORD = 	'x'
	AGENT = 					"cpuminer-oqt-25.32"
	task = asyncio.create_task(task_manager_loop("micro", POOL_HOST, POOL_PORT, WALLET_ADDRESS, WORKER_NAME, POOL_PASSWORD, AGENT))
	main_tasks.append(task)

	done, pending = await asyncio.wait(main_tasks, return_when=asyncio.ALL_COMPLETED)

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

	asyncio.run(main())
	thread.stop()
	thread.join()
	print("\n[Main] Program terminated")