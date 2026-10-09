"""
Q-Harvest Manual Traffic Simulator
SAFE LAB-ONLY DEMO: targets only http://127.0.0.1:8080

Menu:
1 - Controlled DoS-like request burst
2 - Controlled slow data leak
3 - Normal traffic
4 - Exit

Run the dummy cloud server first:
    py frontend\dummy_cloud_server.py

Then:
    py frontend\manual_attack_tool.py
"""

import concurrent.futures
import json
import time
import urllib.request
import urllib.error

TARGET = "http://127.0.0.1:8080"


def get_once(timeout=2):
    try:
        with urllib.request.urlopen(TARGET, timeout=timeout) as r:
            return r.status
    except Exception:
        return None


def post_once(payload, timeout=2):
    req = urllib.request.Request(
        TARGET,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/octet-stream"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except Exception:
        return None


def dos_demo():
    print("\n[1] CONTROLLED DoS DEMO")
    print("Target:", TARGET)
    print("Generating a short, bounded local request burst...\n")

    duration = 12
    workers = 25
    end = time.time() + duration
    total = 0

    def worker():
        count = 0
        while time.time() < end:
            get_once()
            count += 1
        return count

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(worker) for _ in range(workers)]
        for f in futures:
            total += f.result()

    print(f"\n[Q-Harvest] DoS demo completed. Requests generated: {total}")
    print("Check manual_status.json / dashboard for DOS_DETECTED.")


def slow_leak_demo():
    print("\n[2] CONTROLLED SLOW-LEAK DEMO")
    print("Target:", TARGET)
    print("Sending small uploads steadily for 45 seconds...\n")

    payload = b"Q-HARVEST-DEMO-" + (b"X" * 4096)

    for i in range(45):
        status = post_once(payload)
        print(f"[{i+1:02d}/45] sent {len(payload)} bytes | HTTP={status}")
        time.sleep(1)

    print("\n[Q-Harvest] Slow-leak demo completed.")
    print("Check manual_status.json / dashboard for SLOW_LEAK_DETECTED.")


def normal_demo():
    print("\n[3] NORMAL TRAFFIC DEMO")
    print("Target:", TARGET)
    print("Generating low-rate normal requests...\n")

    for i in range(12):
        status = get_once()
        print(f"[{i+1:02d}/12] normal request | HTTP={status}")
        time.sleep(2)

    print("\n[Q-Harvest] Normal traffic demo completed.")
    print("Expected state: NORMAL.")


def main():
    while True:
        print("\n" + "=" * 64)
        print(" Q-HARVEST MANUAL DEMO")
        print("=" * 64)
        print("1. DoS Attack Simulation")
        print("2. Slow Data Leak Simulation")
        print("3. Normal Traffic")
        print("4. Exit")

        choice = input("\nSelect option: ").strip()

        if choice == "1":
            dos_demo()
        elif choice == "2":
            slow_leak_demo()
        elif choice == "3":
            normal_demo()
        elif choice == "4":
            print("Exiting Q-Harvest manual demo.")
            break
        else:
            print("Invalid option. Choose 1, 2, 3, or 4.")


if __name__ == "__main__":
    main()
