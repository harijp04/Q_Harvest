import socket
import time

TARGET = "192.0.2.1"   # TEST-NET address reserved for documentation/testing
PORT = 9999

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

payload = b"Q" * 8192   # 8 KB per send

print("[Q-Harvest] Controlled slow-leak simulation started")
print(f"Target: {TARGET}:{PORT}")
print("Sending ~8 KB/sec for 60 seconds...\n")

for i in range(60):
    sock.sendto(payload, (TARGET, PORT))
    print(f"[{i+1:02d}/60] leaked 8 KB")
    time.sleep(1)

sock.close()

print("\n[Q-Harvest] Slow-leak simulation completed.")