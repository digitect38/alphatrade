#!/bin/bash
# ===========================================
# AlphaTrade Database Backup Script
# v1.31 Section 16.5.4: RPO 5min, RTO 30min
#
# Usage:
#   ./scripts/backup.sh              # incremental (WAL)
#   ./scripts/backup.sh full         # full snapshot
#   ./scripts/backup.sh restore <file>  # restore from backup
#
# Cron (recommended):
#   */5 * * * * /path/to/backup.sh           # incremental every 5 min
#   0 3 * * *  /path/to/backup.sh full       # full daily at 03:00
# ===========================================

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/Users/woosj/DevelopMac/alpha_trade/data/backups}"
CONTAINER="alphatrade-timescaledb"
DB_USER="${POSTGRES_USER:-alphatrade}"
DB_NAME="${POSTGRES_DB:-alphatrade}"
RETENTION_DAYS=30
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

case "${1:-incremental}" in
  full)
    echo "[$(date)] Starting full backup..."
    BACKUP_FILE="$BACKUP_DIR/full_${DATE}.sql.gz"
    docker exec "$CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" --no-owner --no-acl --data-only --disable-triggers | gzip > "$BACKUP_FILE"
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "[$(date)] Full backup complete: $BACKUP_FILE ($SIZE)"

    # Cleanup old backups
    find "$BACKUP_DIR" -name "full_*.sql.gz" -mtime +$RETENTION_DAYS -delete
    echo "[$(date)] Cleaned backups older than ${RETENTION_DAYS} days"
    ;;

  incremental)
    echo "[$(date)] Starting incremental backup (critical tables)..."
    BACKUP_FILE="$BACKUP_DIR/incr_${DATE}.sql.gz"
    docker exec "$CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" --no-owner --no-acl \
      -t orders -t portfolio_positions -t portfolio_snapshots -t audit_log \
      --data-only | gzip > "$BACKUP_FILE"
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "[$(date)] Incremental backup complete: $BACKUP_FILE ($SIZE)"

    # Keep incremental for 7 days
    find "$BACKUP_DIR" -name "incr_*.sql.gz" -mtime +7 -delete
    ;;

  restore)
    RESTORE_FILE="${2:-}"
    if [ -z "$RESTORE_FILE" ] || [ ! -f "$RESTORE_FILE" ]; then
      echo "Usage: $0 restore <backup_file.sql.gz>"
      echo "Available backups:"
      ls -lht "$BACKUP_DIR"/*.sql.gz 2>/dev/null | head -10
      exit 1
    fi
    echo "[$(date)] WARNING: Restoring from $RESTORE_FILE"
    echo "This will OVERWRITE current data. Press Ctrl+C to cancel, Enter to continue..."
    read -r
    gunzip -c "$RESTORE_FILE" | docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME"
    echo "[$(date)] Restore complete from $RESTORE_FILE"
    ;;

  status)
    echo "=== Backup Status ==="
    echo "Backup directory: $BACKUP_DIR"
    echo ""
    echo "Latest full backups:"
    ls -lht "$BACKUP_DIR"/full_*.sql.gz 2>/dev/null | head -5 || echo "  (none)"
    echo ""
    echo "Latest incremental backups:"
    ls -lht "$BACKUP_DIR"/incr_*.sql.gz 2>/dev/null | head -5 || echo "  (none)"
    echo ""
    echo "Total backup size:"
    du -sh "$BACKUP_DIR" 2>/dev/null || echo "  (empty)"
    ;;

  *)
    echo "Usage: $0 [full|incremental|restore <file>|status]"
    exit 1
    ;;
esac
