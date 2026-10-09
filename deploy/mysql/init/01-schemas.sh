#!/bin/bash
# Runs once, when MySQL initialises an empty volume (docker-entrypoint-initdb.d).
# Creates the four data-plane databases (schema.md Section 2, ADR-016) and the database
# users with their grants (schema.md Section 2.1). The application user ($MYSQL_USER,
# app_rw) is created by the MySQL image itself, before this script runs.
#
# Uses the plain mysql client rather than the image's docker_process_sql helper: files
# bind-mounted from Windows look executable, so the entrypoint runs this script as a
# separate process (not sourced) and its helper functions are not available.
# The temporary init server listens on the local socket only; MYSQL_PWD keeps the
# root password off the command line.
set -euo pipefail

: "${MYSQL_MIGRATOR_USER:?}" "${MYSQL_MIGRATOR_PASSWORD:?}"
: "${MYSQL_REPORT_USER:?}" "${MYSQL_REPORT_PASSWORD:?}"
: "${MYSQL_AI_USER:?}" "${MYSQL_AI_PASSWORD:?}"

# Escape single quotes for use inside SQL string literals.
q() { printf "%s" "${1//\'/\'\'}"; }

MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" mysql --protocol=socket -uroot <<-EOSQL
	CREATE DATABASE IF NOT EXISTS \`ledgerbridge_source\`     CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
	CREATE DATABASE IF NOT EXISTS \`ledgerbridge_accounting\` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
	CREATE DATABASE IF NOT EXISTS \`ledgerbridge_reporting\`  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
	CREATE DATABASE IF NOT EXISTS \`ledgerbridge_system\`     CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

	CREATE USER IF NOT EXISTS '$(q "$MYSQL_MIGRATOR_USER")'@'%' IDENTIFIED BY '$(q "$MYSQL_MIGRATOR_PASSWORD")';
	CREATE USER IF NOT EXISTS '$(q "$MYSQL_REPORT_USER")'@'%' IDENTIFIED BY '$(q "$MYSQL_REPORT_PASSWORD")';
	CREATE USER IF NOT EXISTS '$(q "$MYSQL_AI_USER")'@'%' IDENTIFIED BY '$(q "$MYSQL_AI_PASSWORD")';

	-- migrator: schema changes only (Alembic, in the one-off migrate container).
	GRANT ALL PRIVILEGES ON \`ledgerbridge_source\`.*     TO '$(q "$MYSQL_MIGRATOR_USER")'@'%';
	GRANT ALL PRIVILEGES ON \`ledgerbridge_accounting\`.* TO '$(q "$MYSQL_MIGRATOR_USER")'@'%';
	GRANT ALL PRIVILEGES ON \`ledgerbridge_reporting\`.*  TO '$(q "$MYSQL_MIGRATOR_USER")'@'%';
	GRANT ALL PRIVILEGES ON \`ledgerbridge_system\`.*     TO '$(q "$MYSQL_MIGRATOR_USER")'@'%';

	-- app_rw: data only, no DDL (API and workers).
	GRANT SELECT, INSERT, UPDATE, DELETE ON \`ledgerbridge_source\`.*     TO '$(q "$MYSQL_USER")'@'%';
	GRANT SELECT, INSERT, UPDATE, DELETE ON \`ledgerbridge_accounting\`.* TO '$(q "$MYSQL_USER")'@'%';
	GRANT SELECT, INSERT, UPDATE, DELETE ON \`ledgerbridge_reporting\`.*  TO '$(q "$MYSQL_USER")'@'%';
	GRANT SELECT, INSERT, UPDATE, DELETE ON \`ledgerbridge_system\`.*     TO '$(q "$MYSQL_USER")'@'%';

	-- report_ro: reporting endpoints read the canonical model and the semantic layer.
	GRANT SELECT ON \`ledgerbridge_accounting\`.* TO '$(q "$MYSQL_REPORT_USER")'@'%';
	GRANT SELECT ON \`ledgerbridge_reporting\`.*  TO '$(q "$MYSQL_REPORT_USER")'@'%';

	-- ai_ro: the semantic layer only (AI-003). Nothing else, ever.
	GRANT SELECT ON \`ledgerbridge_reporting\`.* TO '$(q "$MYSQL_AI_USER")'@'%';

	FLUSH PRIVILEGES;
EOSQL
