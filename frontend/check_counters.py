import os, socket, threading, time
import psutil

HOST, PORT = "127.0.0.1", 9091

def victim():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT)); srv.listen(5)
    def handle(c):
        try:
            while c.recv(65536):
                pass
        except Exception:
            pass
        finally:
            c.close()
    while True:
        c, _ = srv.accept()
        threading.Thread(target=handle, args=(c,), daemon=True).start()

def leak(seconds, kbps=30):
    try:
        s = socket.create_connection((HOST, PORT))
        chunk = int(kbps * 1024 * 0.1)
        end, nxt = time.time() + seconds, time.time()
        while time.time() < end:
            s.sendall(os.urandom(chunk))
            nxt += 0.1
            time.sleep(max(0, nxt - time.time()))
        s.close()
    except Exception as e:
        print("LEAK ERROR:", repr(e))

threading.Thread(target=victim, daemon=True).start()
time.sleep(1)
a = psutil.net_io_counters(pernic=True)
threading.Thread(target=leak, args=(12,), daemon=True).start()
time.sleep(10)
b = psutil.net_io_counters(pernic=True)
print("bytes/sec sent per interface during a 30 KB/s leak:")
for k in b:
    if k in a:
        print(f"  {k}: {(b[k].bytes_sent - a[k].bytes_sent) / 10:.0f}")