---
tags: [infrastructure, database, postgresql, setup, arch, cachyos, local-dev]
cssclasses: [procurement-doc, infra-doc]
status: "#processed"
related: ["[[databases_postgresql_redis]]", "[[security_compliance]]", "[[data_pipeline_architecture]]"]
---

# PostgreSQL — Local Setup on CachyOS / Arch Linux

> [!info] Platform Note
> CachyOS is based on Arch Linux. The installation process is **identical to Arch**, but unlike Debian/Ubuntu-based distros, Arch does **not** automatically initialize the database cluster for you — you must run `initdb` manually before the service can start.

---

## 1. Install the Package

Use `pacman` to install the core PostgreSQL package:

```bash
sudo pacman -S postgresql
```

This creates a system user named `postgres` and installs the binaries, but does **not** start the service or create any data files yet.

---

## 2. Initialize the Database Cluster

> [!warning] Do not skip this step
> The service will fail to start if the data directory has not been initialized. This is the most common mistake on Arch-based systems.

Switch to the `postgres` system user and run `initdb` to create the data directory:

```bash
sudo -u postgres initdb -D /var/lib/postgres/data
```

| Flag | Meaning |
|------|---------|
| `-D /var/lib/postgres/data` | Path to the data directory — the default location for Arch-based systems |

---

## 3. Start and Enable the Service

Once initialized, manage the service with `systemctl`:

```bash
# Start the service immediately
sudo systemctl start postgresql

# Enable it to start automatically on every boot
sudo systemctl enable postgresql
```

Verify the service is running:

```bash
sudo systemctl status postgresql
```

> [!check] Expected output
> The status command should show `Active: active (running)`. If you see `failed`, the most likely cause is a missing or corrupted data directory — go back to Step 2.

---

## 4. Create Your First User (Recommended)

> [!tip] Why create a matching user?
> By default, only the `postgres` system user can log in to the database. Creating a PostgreSQL role that matches your Linux username (`carbaje`) lets you run `psql` directly from your normal terminal without switching accounts.

**Enter the PostgreSQL shell as the `postgres` user:**

```bash
sudo -u postgres psql
```

**Inside the shell, run the following SQL commands:**

```sql
-- Create a superuser role matching your Linux username
CREATE USER username WITH SUPERUSER PASSWORD 'yourpassword';

-- Create a default database with the same name (required for passwordless psql login)
CREATE DATABASE username;

-- Exit the shell
\q
```

Replace `yourpassword` with a strong password of your choice.

**From now on, simply type the following from any terminal to open a session:**

```bash
psql
```

---

## 5. Basic Usage

### Connect to a database

```bash
# Connect to your default database
psql

# Connect to a specific database
psql -d mydatabase

# Connect as a specific user
psql -U carbaje -d mydatabase
```

### Common psql meta-commands

| Command | Description |
|---------|-------------|
| `\l` | List all databases |
| `\c dbname` | Connect to a database |
| `\dt` | List tables in the current database |
| `\d tablename` | Describe a table's schema |
| `\du` | List all users/roles |
| `\q` | Quit the shell |
| `\?` | Help for meta-commands |
| `\h CREATE TABLE` | SQL syntax help |

### Creating a database and table

```sql
-- Create a new database
CREATE DATABASE myproject;

-- Connect to it
\c myproject

-- Create a table
CREATE TABLE orders (
    id        SERIAL PRIMARY KEY,
    item      VARCHAR(255) NOT NULL,
    quantity  INTEGER      NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert a row
INSERT INTO orders (item, quantity) VALUES ('Laptop', 5);

-- Query the table
SELECT * FROM orders;
```

---

## 6. Configuration Files

All configuration lives inside the data directory:

| File | Purpose |
|------|---------|
| `/var/lib/postgres/data/postgresql.conf` | Main server configuration (port, memory, logging, etc.) |
| `/var/lib/postgres/data/pg_hba.conf` | Client authentication rules (who can connect, from where, and how) |

### Allow remote connections

1. In `postgresql.conf`, change:
   ```
   listen_addresses = 'localhost'
   ```
   to:
   ```
   listen_addresses = '*'
   ```

2. In `pg_hba.conf`, add a line to allow your remote client:
   ```
   host    all    all    <client_ip>/32    md5
   ```

3. Restart the service:
   ```bash
   sudo systemctl restart postgresql
   ```

> [!guardrail] Security Warning
> Opening PostgreSQL to remote connections exposes it to the network. Always restrict `pg_hba.conf` to specific trusted IPs and use strong passwords. For production, place PostgreSQL behind a VPN or firewall.

---

## 7. GUI Tools

If you prefer a visual interface over the `psql` CLI:

```bash
# DBeaver — universal database GUI, supports PostgreSQL and many others
sudo pacman -S dbeaver

# pgAdmin 4 — PostgreSQL-specific, feature-rich web-based GUI
sudo pacman -S pgadmin4
```

**Connection settings for both tools:**

| Field | Value |
|-------|-------|
| Host | `localhost` |
| Port | `5432` |
| Database | `carbaje` |
| Username | `carbaje` |
| Password | *(the password you set in Step 4)* |

---

## 8. Troubleshooting

### Service fails to start

```bash
# Check detailed error logs
journalctl -u postgresql -n 50
```

Most common causes:
- Data directory not initialized → re-run `initdb` (Step 2)
- Port 5432 already in use → check with `ss -tlnp | grep 5432`
- Wrong ownership on `/var/lib/postgres/data` → fix with `sudo chown -R postgres:postgres /var/lib/postgres/data`

### Cannot connect / authentication error

Check `/var/lib/postgres/data/pg_hba.conf`. The `local` authentication method should be `trust` or `md5` for your user.

### CachyOS performance note

> [!tip] Optimized Repositories
> CachyOS ships `cachyos-v3` / `cachyos-v4` repositories with CPU-optimized builds. The standard `postgresql` Arch package is already excellent, but you can check for a `postgresql-cachyos` variant in the CachyOS repositories for potential micro-architecture optimizations.

---

## Quick Reference

```bash
# Install
sudo pacman -S postgresql

# Initialize (run once)
sudo -u postgres initdb -D /var/lib/postgres/data

# Start / stop / restart
sudo systemctl start postgresql
sudo systemctl stop postgresql
sudo systemctl restart postgresql

# Check status
sudo systemctl status postgresql

# Open a psql session
psql

# Open as postgres superuser
sudo -u postgres psql
```
