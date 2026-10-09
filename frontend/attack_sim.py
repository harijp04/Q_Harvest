import os, socket, sys, time, threading
import psutil

def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))     # sends nothing, just picks the Wi-Fi address
        return s.getsockname()[0]
    finally:
        s.close()

def default_target():
    return ".".join(local_ip().split(".")[:3]) + ".1"   # usually the router

PKT = 1200  # bytes per packet, below the Wi-Fi MTU

def paced_send(target, kbps, seconds, tag):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    pps = kbps * 1024 / PKT
    batch = max(1, int(pps / 100))          # ~100 wakeups per second
    end = time.time() + seconds
    nxt, last = time.time(), time.time()
    while time.time() < end:
        for _ in range(batch):
            try:
                sock.sendto(os.urandom(PKT), (target, 9))
            except Exception:
                pass
        nxt += batch / pps
        time.sleep(max(0, nxt - time.time()))
        if tag and time.time() - last > 30:
            print(f"  ...{int(end - time.time())}s left"); last = time.time()
    sock.close()

def leak(kbps=30, minutes=8, target=None):
    target = target or default_target()
    print(f"SLOW LEAK: steady {kbps} KB/s of random data -> {target} for {minutes} min")
    paced_send(target, kbps, minutes * 60, tag=True)
    print("Leak finished.")

def dos(seconds=30, target=None, kbps=2000):
    target = target or default_target()
    print(f"VOLUME FLOOD: ~{kbps} KB/s -> {target} for {seconds}s")
    paced_send(target, kbps, seconds, tag=False)
    print("Flood finished.")

def check():
    target = default_target()
    print(f"Test leak of 30 KB/s -> {target}")
    a = psutil.net_io_counters(pernic=True)
    threading.Thread(target=paced_send, args=(target, 30, 12, False), daemon=True).start()
    time.sleep(10)
    b = psutil.net_io_counters(pernic=True)
    print("bytes/sec sent per interface:")
    for k in b:
        if k in a:
            print(f"  {k}: {(b[k].bytes_sent - a[k].bytes_sent) / 10:.0f}")

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    args = sys.argv[2:]
    try:
        if mode == "check": check()
        elif mode == "leak": leak(float(args[0]) if args else 30,
                                  float(args[1]) if len(args) > 1 else 8,
                                  args[2] if len(args) > 2 else None)
        elif mode == "dos": dos(float(args[0]) if args else 30,
                                args[1] if len(args) > 1 else None)
        else: print("usage: python attack_sim.py check | leak [KB/s] [minutes] [ip] | dos [seconds] [ip]")
    except KeyboardInterrupt:
        print("\nStopped.")