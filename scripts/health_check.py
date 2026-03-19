"""Check health of all services and exit non-zero if any are down."""
import sys, urllib.request

def check(url: str, name: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            ok = r.status == 200
            print(f"  {'✓' if ok else '✗'} {name}: {r.status}")
            return ok
    except Exception as e:
        print(f"  ✗ {name}: {e}")
        return False

if __name__ == "__main__":
    results = [
        check("http://localhost:8000/health", "API"),
    ]
    sys.exit(0 if all(results) else 1)
