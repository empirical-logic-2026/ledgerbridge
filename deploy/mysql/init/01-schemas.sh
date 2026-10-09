#!/bin/bash
# Runs once, on a fresh MySQL volume (docker-entrypoint-initdb.d).
# Creates the four data-plane databases (schema.md Section 2) and gives the
# application user rights on them. M2 replaces the grants with the
# migrator / app_rw / report_ro / ai_ro users from schema.md Section 2.1.
#
# Uses the plain mysql client rather than the image's docker_process_sql helper: files
# bind-mounted from Windows look executable, so the entrypoint runs this script as a
# separate process (not sourced) and its helper functions are not available.
# The temporary init server listens on the local socket only; MYSQL_PWD keeps the
# root password off the command line.
set -euo pipefail

MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" mysql --protocol=socket -uroot <<-EOSQL
	CREATE DATABASE IF NOT EXISTS \`raw\`  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
	CREATE DATABASE IF NOT EXISTS \`core\` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
	CREATE DATABASE IF NOT EXISTS \`rpt\`  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
	CREATE DATABASE IF NOT EXISTS \`app\`  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
	GRANT ALL PRIVILEGES ON \`raw\`.*  TO '${MYSQL_USER}'@'%';
	GRANT ALL PRIVILEGES ON \`core\`.* TO '${MYSQL_USER}'@'%';
	GRANT ALL PRIVILEGES ON \`rpt\`.*  TO '${MYSQL_USER}'@'%';
	GRANT ALL PRIVILEGES ON \`app\`.*  TO '${MYSQL_USER}'@'%';
	FLUSH PRIVILEGES;
EOSQL
