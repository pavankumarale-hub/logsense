"""Generate a larger synthetic log file for performance/load testing.

Usage:
  python scripts/generate_synthetic_logs.py --count 10000 --output /tmp/synthetic.log
"""

import argparse
import random
import uuid
from datetime import datetime, timedelta, timezone

SERVICES = [
    "payment-service", "order-service", "auth-service",
    "inventory-service", "notification-service", "api-gateway", "user-service",
]

ERROR_TEMPLATES = [
    ("ERROR", "Database connection timeout after {ms}ms: Unable to acquire JDBC Connection"),
    ("ERROR", "java.lang.NullPointerException: Cannot invoke \"{method}\" because \"{var}\" is null"),
    ("ERROR", "JWT validation failed: Token expired at {ts} for user {user}"),
    ("WARN",  "Circuit breaker OPEN for downstream service {svc} after {n} consecutive failures"),
    ("ERROR", "OutOfMemoryError: Java heap space"),
    ("WARN",  "Rate limit exceeded for client {ip}: {n} requests in 60s"),
    ("ERROR", "Connection refused to {svc}:{port}"),
    ("WARN",  "Slow query detected: {ms}ms for SELECT * FROM orders WHERE customer_id = {n}"),
    ("INFO",  "Cache miss for product SKU-{sku}, falling back to database"),
    ("ERROR", "Upstream timed out after {ms}ms waiting for response from {svc}"),
]


def _fill(template: str) -> str:
    return (
        template
        .replace("{ms}", str(random.randint(28000, 32000)))
        .replace("{method}", random.choice(["getId", "getName", "getEmail", "getOrder"]) + "()")
        .replace("{var}", random.choice(["customer", "order", "user", "product"]))
        .replace("{ts}", "2024-01-15T09:00:00Z")
        .replace("{user}", f"user-{random.randint(1000, 9999)}")
        .replace("{svc}", random.choice(SERVICES))
        .replace("{port}", str(random.randint(8080, 8090)))
        .replace("{n}", str(random.randint(3, 10)))
        .replace("{ip}", f"192.168.{random.randint(0,255)}.{random.randint(1,254)}")
        .replace("{sku}", str(random.randint(10000, 99999)))
    )


def generate(count: int) -> list[str]:
    lines = []
    ts = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    for _ in range(count):
        ts += timedelta(milliseconds=random.randint(50, 500))
        service = random.choice(SERVICES)
        level, tmpl = random.choice(ERROR_TEMPLATES)
        message = _fill(tmpl)
        trace = str(uuid.uuid4())[:8]
        line = f"{ts.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} {level:5s} [{service}] [trace={trace}] - {message}"
        lines.append(line)
    return lines


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic log files")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--output", default="/tmp/synthetic_logs.log")
    args = parser.parse_args()

    lines = generate(args.count)
    with open(args.output, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Generated {len(lines)} log lines → {args.output}")


if __name__ == "__main__":
    main()
