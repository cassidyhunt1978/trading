# 🚫 NO LOCALHOST RULE

## ⚠️ HARD FAST RULE: `localhost` IS BANNED FROM CODE

**Effective Date:** February 17, 2026  
**Status:** MANDATORY  
**Applies To:** All Python code, JavaScript, configuration files, and scripts

---

## Why This Rule Exists

Using hardcoded `localhost` in code causes the system to **FAIL** when:
- Accessing from remote machines (e.g., `http://172.16.1.92:8010`)
- Running in containers or distributed systems
- Deploying to cloud environments
- Using reverse proxies or load balancers

The system must work from **ANY** network location, not just the local machine.

---

## ✅ ALLOWED Alternatives

### 1. **Dynamic Detection (JavaScript/Frontend)**
```javascript
// GOOD: Detects current hostname automatically
const API_HOST = window.location.hostname;
fetch(`http://${API_HOST}:8015/api/data`);
```

### 2. **Configuration-Based (Python/Backend)**
```python
# GOOD: Use configuration with 127.0.0.1 default
from shared.config import get_settings
settings = get_settings()

url = f"http://{settings.service_host}:{settings.port_signal_api}/signals"
```

### 3. **IP Address 127.0.0.1**
```python
# ACCEPTABLE: Use IP instead of hostname
DATABASE_URL = 'postgresql://user:pass@127.0.0.1:5432/db'
```

### 4. **0.0.0.0 for Binding**
```python
# GOOD: Server binds to all interfaces
app.run(host='0.0.0.0', port=8010)
```

### 5. **Environment Variables**
```bash
# GOOD: Configurable via environment
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/trading_system
SERVICE_HOST=127.0.0.1
```

---

## ❌ BANNED Patterns

### ❌ Hardcoded localhost
```python
# BAD: Never do this!
response = requests.get('http://localhost:8015/api/data')
```

### ❌ localhost in URLs
```javascript
// BAD: Breaks remote access!
fetch('http://localhost:8016/portfolio')
```

### ❌ localhost in Database URLs
```python
# BAD: Use 127.0.0.1 or config instead
conn = psycopg2.connect('postgresql://user@localhost:5432/db')
```

---

## 📋 Enforcement Checklist

Before committing code, verify:

- [ ] No `localhost` in Python files (`.py`)
- [ ] No `localhost` in JavaScript files (`.js`, `.html`)
- [ ] No `localhost` in configuration files (`.py`, `.env`)
- [ ] All service URLs use dynamic detection or config
- [ ] Database URLs use IP address or environment variable

### Quick Check Command
```bash
# Search for localhost in code (excluding logs/docs)
grep -r "localhost" --include="*.py" --include="*.js" --include="*.html" \
  --exclude-dir="venv" --exclude-dir="logs" --exclude-dir="node_modules" .
```

---

## 🔧 Migration Guide

### If You Find `localhost` in Code:

1. **Frontend/JavaScript:**
   ```javascript
   // Replace this:
   fetch('http://localhost:8015/api/data')
   
   // With this:
   const API_HOST = window.location.hostname;
   fetch(`http://${API_HOST}:8015/api/data`)
   ```

2. **Backend Services (Python):**
   ```python
   # Replace this:
   url = f"http://localhost:{port}/endpoint"
   
   # With this:
   from shared.config import get_settings
   settings = get_settings()
   url = f"http://{settings.service_host}:{port}/endpoint"
   ```

3. **Configuration Files:**
   ```python
   # Replace this:
   database_url: str = 'postgresql://user@localhost:5432/db'
   
   # With this:
   database_url: str = 'postgresql://user@127.0.0.1:5432/db'
   ```

---

## 📁 Files Already Updated

The following files have been cleaned of `localhost`:
- ✅ `ui/index.html` - Uses dynamic `window.location.hostname`
- ✅ `shared/config.py` - Uses `127.0.0.1` and `service_host` config
- ✅ `shared/database.py` - Uses `127.0.0.1` in default
- ✅ `celery_worker/tasks.py` - Uses `settings.service_host`

---

## 🎯 Configuration Variables

Add these to `shared/config.py`:

```python
class Settings(BaseSettings):
    # Service Communication
    service_host: str = '127.0.0.1'  # Internal service-to-service calls
    
    # Database
    database_url: str = 'postgresql://postgres:postgres@127.0.0.1:5432/trading_system'
    
    # Redis
    redis_url: str = 'redis://127.0.0.1:6379/0'
```

Override in `.env` file:
```bash
SERVICE_HOST=127.0.0.1
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/trading_system
REDIS_URL=redis://127.0.0.1:6379/0
```

---

## 📖 Exception: Documentation & Scripts

**Allowed exceptions** (but use sparingly):
- Documentation examples (`.md` files)
- Local testing scripts that explicitly state they run locally
- Print statements for user instructions

**Even then, prefer showing both options:**
```bash
# Access via localhost OR your server IP:
# - http://localhost:8010
# - http://172.16.1.92:8010
# - http://your-server-ip:8010
```

---

## 🚨 Violations

**If you commit code with hardcoded `localhost`:**
1. It will cause remote access failures
2. The UI will show CONNECTION REFUSED errors
3. Services won't discover each other in distributed setups
4. You must fix it immediately

---

## ✨ Summary

**NEVER use `localhost` in code.**

**ALWAYS use:**
- `window.location.hostname` (JavaScript)
- `settings.service_host` (Python)
- `127.0.0.1` (configuration defaults)
- Environment variables (production)

This ensures the system works **everywhere**, not just locally.

---

**Last Updated:** February 17, 2026  
**Maintained By:** Trading System Team
