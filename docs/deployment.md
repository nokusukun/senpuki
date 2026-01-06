# Deployment Guide

This guide covers deploying Senpuki applications in production environments.

## Architecture Overview

A Senpuki deployment consists of:

1. **Database** - PostgreSQL (recommended) or SQLite for persistence
2. **Workers** - Process that executes durable functions
3. **Dispatchers** - Application code that dispatches workflows
4. **Notification Backend** (optional) - Redis for real-time notifications

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Client    │     │   Client    │     │   Client    │
│ Application │     │ Application │     │ Application │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       └───────────┬───────┴───────────┬───────┘
                   │                   │
                   ▼                   ▼
            ┌─────────────┐     ┌─────────────┐
            │  PostgreSQL │     │    Redis    │
            │  (Backend)  │     │(Notifications)
            └──────┬──────┘     └──────┬──────┘
                   │                   │
       ┌───────────┼───────────────────┼───────────┐
       │           │                   │           │
       ▼           ▼                   ▼           ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│   Worker    │ │   Worker    │ │   Worker    │ │   Worker    │
│  (Pod 1)    │ │  (Pod 2)    │ │  (Pod 3)    │ │  (Pod N)    │
└─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘
```

## Database Setup

### PostgreSQL (Recommended for Production)

```python
from senpuki import Senpuki

# Connection string
dsn = "postgresql://user:password@host:5432/senpuki"

backend = Senpuki.backends.PostgresBackend(dsn)
await backend.init_db()

executor = Senpuki(backend=backend)
```

**Recommended PostgreSQL settings:**

```sql
-- Create database and user
CREATE DATABASE senpuki;
CREATE USER senpuki_app WITH PASSWORD 'secure_password';
GRANT ALL PRIVILEGES ON DATABASE senpuki TO senpuki_app;

-- Performance tuning for workload
ALTER SYSTEM SET max_connections = 200;
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET effective_cache_size = '1GB';
ALTER SYSTEM SET work_mem = '16MB';
```

### SQLite (Development/Small Scale)

```python
backend = Senpuki.backends.SQLiteBackend("/data/senpuki.sqlite")
await backend.init_db()
```

SQLite is suitable for:
- Development and testing
- Single-worker deployments
- Low throughput (< 100 tasks/second)

## Redis Notifications (Optional but Recommended)

Redis provides real-time notifications for faster task completion detection:

```python
notification_backend = Senpuki.notifications.RedisBackend("redis://localhost:6379")

executor = Senpuki(
    backend=backend,
    notification_backend=notification_backend
)
```

Without Redis, Senpuki polls the database for task updates.

## Docker Deployment

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Run worker by default
CMD ["python", "-m", "myapp.worker"]
```

### docker-compose.yml

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: senpuki
      POSTGRES_USER: senpuki
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U senpuki"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  worker:
    build: .
    command: python -m myapp.worker
    environment:
      DATABASE_URL: postgresql://senpuki:${DB_PASSWORD}@postgres:5432/senpuki
      REDIS_URL: redis://redis:6379
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    deploy:
      replicas: 3

  api:
    build: .
    command: uvicorn myapp.api:app --host 0.0.0.0 --port 8000
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://senpuki:${DB_PASSWORD}@postgres:5432/senpuki
      REDIS_URL: redis://redis:6379
    depends_on:
      postgres:
        condition: service_healthy

volumes:
  postgres_data:
```

### Worker Script

```python
# myapp/worker.py
import asyncio
import os
import signal
import logging
from senpuki import Senpuki

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import your durable functions to register them
from myapp import workflows  # noqa

async def main():
    # Configuration from environment
    database_url = os.environ["DATABASE_URL"]
    redis_url = os.environ.get("REDIS_URL")
    
    # Initialize backends
    backend = Senpuki.backends.PostgresBackend(database_url)
    await backend.init_db()
    
    notification_backend = None
    if redis_url:
        notification_backend = Senpuki.notifications.RedisBackend(redis_url)
    
    # Create executor
    executor = Senpuki(
        backend=backend,
        notification_backend=notification_backend
    )
    
    # Create lifecycle handle for graceful shutdown
    lifecycle = executor.create_worker_lifecycle(name=f"worker-{os.getpid()}")
    
    # Handle shutdown signals
    def request_shutdown():
        logger.info("Shutdown requested, draining...")
        executor.request_worker_drain(lifecycle)
    
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, request_shutdown)
    
    # Start serving
    logger.info("Worker starting...")
    await executor.serve(
        lifecycle=lifecycle,
        max_concurrency=10,
        poll_interval=0.5
    )
    logger.info("Worker stopped")

if __name__ == "__main__":
    asyncio.run(main())
```

## Kubernetes Deployment

### Deployment Manifest

```yaml
# worker-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: senpuki-worker
  labels:
    app: senpuki-worker
spec:
  replicas: 3
  selector:
    matchLabels:
      app: senpuki-worker
  template:
    metadata:
      labels:
        app: senpuki-worker
    spec:
      terminationGracePeriodSeconds: 300  # 5 minutes for graceful shutdown
      containers:
      - name: worker
        image: myapp:latest
        command: ["python", "-m", "myapp.worker"]
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: senpuki-secrets
              key: database-url
        - name: REDIS_URL
          valueFrom:
            secretKeyRef:
              name: senpuki-secrets
              key: redis-url
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 10
```

### Health Check Endpoint

Add a health check server to your worker:

```python
# myapp/worker.py
import asyncio
from aiohttp import web
from senpuki import Senpuki

async def create_health_server(executor: Senpuki):
    """Create health check HTTP server."""
    
    async def health_handler(request):
        """Liveness probe - is the process alive?"""
        return web.Response(text="OK")
    
    async def ready_handler(request):
        """Readiness probe - is the worker ready to accept work?"""
        status = executor.worker_status_overview()
        if status["ready"]:
            return web.Response(text="Ready")
        return web.Response(text="Not Ready", status=503)
    
    app = web.Application()
    app.router.add_get("/health", health_handler)
    app.router.add_get("/ready", ready_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    return runner

async def main():
    # ... setup executor ...
    
    # Start health server
    health_runner = await create_health_server(executor)
    
    try:
        await executor.serve(...)
    finally:
        await health_runner.cleanup()
```

### Horizontal Pod Autoscaler

```yaml
# hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: senpuki-worker-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: senpuki-worker
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

## Systemd Deployment

For bare-metal or VM deployments:

### Service File

```ini
# /etc/systemd/system/senpuki-worker.service
[Unit]
Description=Senpuki Worker
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=senpuki
Group=senpuki
WorkingDirectory=/opt/senpuki
Environment="DATABASE_URL=postgresql://senpuki:password@localhost/senpuki"
Environment="REDIS_URL=redis://localhost:6379"
ExecStart=/opt/senpuki/venv/bin/python -m myapp.worker
Restart=always
RestartSec=5

# Graceful shutdown
TimeoutStopSec=300
KillMode=mixed
KillSignal=SIGTERM

# Security
NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
```

### Installation

```bash
# Create user
sudo useradd -r -s /bin/false senpuki

# Setup application
sudo mkdir -p /opt/senpuki
sudo chown senpuki:senpuki /opt/senpuki

# Install
cd /opt/senpuki
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable senpuki-worker
sudo systemctl start senpuki-worker

# Check status
sudo systemctl status senpuki-worker
sudo journalctl -u senpuki-worker -f
```

## Scaling Strategies

### Horizontal Scaling (More Workers)

Add more worker replicas:

```yaml
# Kubernetes
kubectl scale deployment senpuki-worker --replicas=10

# Docker Compose
docker-compose up -d --scale worker=10
```

### Vertical Scaling (More Concurrency per Worker)

Increase `max_concurrency`:

```python
await executor.serve(
    max_concurrency=50,  # More concurrent tasks per worker
)
```

### Queue-Based Scaling

Use separate workers for different queues:

```python
# High-priority worker
await executor.serve(
    queues=["critical", "high"],
    max_concurrency=20
)

# Low-priority worker (can scale independently)
await executor.serve(
    queues=["low", "batch"],
    max_concurrency=50
)
```

### Tag-Based Scaling

Scale workers with specific capabilities:

```python
# GPU worker
await executor.serve(
    tags=["gpu", "ml"],
    max_concurrency=4  # Limited by GPU memory
)

# CPU worker
await executor.serve(
    tags=["cpu"],
    max_concurrency=20
)
```

## Database Maintenance

### Cleanup Old Data

Senpuki automatically cleans up completed executions:

```python
await executor.serve(
    cleanup_interval=3600.0,  # Run cleanup every hour
    retention_period=timedelta(days=7)  # Keep 7 days
)
```

### Manual Cleanup

```python
from datetime import datetime, timedelta

# Delete executions older than 30 days
cutoff = datetime.now() - timedelta(days=30)
count = await backend.cleanup_executions(cutoff)
print(f"Cleaned up {count} executions")
```

### Database Indexes

For PostgreSQL, ensure indexes are optimized:

```sql
-- Check index usage
SELECT indexrelname, idx_scan, idx_tup_read, idx_tup_fetch 
FROM pg_stat_user_indexes 
WHERE schemaname = 'public';

-- Vacuum and analyze
VACUUM ANALYZE tasks;
VACUUM ANALYZE executions;
```

## Monitoring in Production

### Prometheus Metrics

```python
from senpuki.metrics import MetricsRecorder
from prometheus_client import Counter, Histogram, Gauge, start_http_server

class PrometheusMetrics(MetricsRecorder):
    def __init__(self):
        self.tasks_claimed = Counter(
            'senpuki_tasks_claimed_total',
            'Total tasks claimed',
            ['queue', 'step_name', 'kind']
        )
        self.tasks_completed = Counter(
            'senpuki_tasks_completed_total',
            'Total tasks completed',
            ['queue', 'step_name', 'kind']
        )
        self.task_duration = Histogram(
            'senpuki_task_duration_seconds',
            'Task execution duration',
            ['queue', 'step_name', 'kind']
        )
        self.tasks_failed = Counter(
            'senpuki_tasks_failed_total',
            'Total tasks failed',
            ['queue', 'step_name', 'kind', 'retrying']
        )
        self.dead_letters = Counter(
            'senpuki_dead_letters_total',
            'Total tasks dead-lettered',
            ['queue', 'step_name', 'kind']
        )
    
    def task_claimed(self, queue, step_name, kind):
        self.tasks_claimed.labels(queue=queue or '', step_name=step_name, kind=kind).inc()
    
    def task_completed(self, queue, step_name, kind, duration_s):
        self.tasks_completed.labels(queue=queue or '', step_name=step_name, kind=kind).inc()
        self.task_duration.labels(queue=queue or '', step_name=step_name, kind=kind).observe(duration_s)
    
    def task_failed(self, queue, step_name, kind, reason, retrying):
        self.tasks_failed.labels(queue=queue or '', step_name=step_name, kind=kind, retrying=str(retrying)).inc()
    
    def dead_lettered(self, queue, step_name, kind, reason):
        self.dead_letters.labels(queue=queue or '', step_name=step_name, kind=kind).inc()
    
    def lease_renewed(self, task_id, success):
        pass  # Optional

# Usage
metrics = PrometheusMetrics()
start_http_server(9090)  # Expose /metrics

executor = Senpuki(backend=backend, metrics=metrics)
```

### Alerting Rules

```yaml
# prometheus-alerts.yaml
groups:
- name: senpuki
  rules:
  - alert: HighDLQCount
    expr: increase(senpuki_dead_letters_total[1h]) > 10
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High dead letter queue count"
      
  - alert: TaskProcessingDelay
    expr: senpuki_task_duration_seconds{quantile="0.99"} > 60
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "Task processing taking too long"
      
  - alert: WorkerDown
    expr: up{job="senpuki-worker"} == 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Senpuki worker is down"
```

## Security Best Practices

### 1. Secure Database Connections

```python
# Use SSL for PostgreSQL
dsn = "postgresql://user:pass@host:5432/db?sslmode=require"
```

### 2. Use Secrets Management

```python
import os
from aws_secretsmanager_caching import SecretCache

# Fetch secrets at startup
secrets = SecretCache()
db_password = secrets.get_secret_string("senpuki/database")
```

### 3. Network Isolation

- Place workers in private subnet
- Use VPC/firewall rules to restrict access
- Use mTLS for service-to-service communication

### 4. Least Privilege

```sql
-- Create limited user for workers
CREATE USER senpuki_worker WITH PASSWORD 'xxx';
GRANT SELECT, INSERT, UPDATE, DELETE ON tasks TO senpuki_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON executions TO senpuki_worker;
-- Don't grant DROP, TRUNCATE, etc.
```

## Troubleshooting

### Workers Not Processing Tasks

1. Check worker logs:
   ```bash
   kubectl logs -f deployment/senpuki-worker
   ```

2. Verify database connectivity:
   ```python
   # Test connection
   await backend.init_db()
   count = await backend.count_tasks(state="pending")
   print(f"Pending tasks: {count}")
   ```

3. Check queue configuration:
   ```python
   # Worker might be filtering by queue
   await executor.serve(queues=["default"])  # Ensure queue matches
   ```

### High Task Latency

1. Check worker concurrency:
   ```python
   # Increase if workers are bottleneck
   await executor.serve(max_concurrency=50)
   ```

2. Monitor database performance:
   ```sql
   -- Check slow queries
   SELECT * FROM pg_stat_statements ORDER BY total_time DESC LIMIT 10;
   ```

3. Add Redis for notifications:
   ```python
   notification_backend = Senpuki.notifications.RedisBackend(redis_url)
   ```

### Tasks Stuck in "running" State

Tasks stuck in "running" usually means a worker crashed:

1. Check lease expiration:
   ```python
   # Tasks are reclaimed after lease expires (default 5 minutes)
   await executor.serve(lease_duration=timedelta(minutes=5))
   ```

2. Manually reclaim (if urgent):
   ```python
   # Move task back to pending
   task = await backend.get_task(task_id)
   task.state = "pending"
   task.worker_id = None
   await backend.update_task(task)
   ```

## See Also

- [Configuration Reference](configuration.md) - All configuration options
- [Monitoring](guides/monitoring.md) - Detailed monitoring setup
- [Workers](guides/workers.md) - Worker configuration
