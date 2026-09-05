COMPOSE      ?= docker compose
PROD_COMPOSE ?= docker compose -f docker-compose.prod.yml

# CLI shortcut for large local files. The normal path is the setup wizard in the
# browser. /host is the project root mounted read-only, so nothing here is ever
# deleted; only wizard uploads are.
SRC ?= /host/your_facebook_activity

.PHONY: up down logs build import reimport test shell db stats prod prod-down clean-db

up:            ## Start dev stack (api :8000, web :5173)
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

build:
	$(COMPOSE) build

## Import an export. Accepts several paths:
##   make import SRC="/export/part1.zip /export/part2.zip"
import:
	$(COMPOSE) run --rm api python -m app.importer $(SRC)

## Import every zip in the project root at once (Facebook splits big exports
## into several archives; they all merge into the same database).
import-all:
	$(COMPOSE) run --rm api sh -c 'python -m app.importer /host/*.zip'

## Wipe the database and import from scratch
reimport:
	$(COMPOSE) run --rm api python -m app.importer --reset $(SRC)

test:
	$(COMPOSE) run --rm api pytest -q

## Generate a synthetic 200k-message thread to verify scroll performance
perf-seed:
	$(COMPOSE) run --rm api python -m app.tools.perf_seed

shell:
	$(COMPOSE) run --rm api bash

db:
	$(COMPOSE) run --rm api python -c "import sqlite3,os;print(sqlite3.connect(os.environ['ARCHIVE_DB']).execute('select (select count(*) from thread), (select count(*) from message), (select count(*) from media)').fetchone())"

prod:
	$(PROD_COMPOSE) up --build

prod-down:
	$(PROD_COMPOSE) down

clean-db:
	rm -f data/archive.db data/archive.db-wal data/archive.db-shm
