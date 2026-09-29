# KisanSaathi — `make up` builds and runs the whole stack.
#
# The Makefile is glue, not policy. Every target is the one command you could
# have read in the README and typed yourself, and `make help` prints that command
# next to each target, so this file can never hide what it does to your machine.
#
#   make up       build the images and run Postgres, the API and nginx
#   make dev      run the API and Vite locally instead, on SQLite, no Docker
#   make check    tests, lint, types and the production build
#   make verify   check, plus the API contract and a real-browser sweep
#   make help     every target
#
# Requires Docker with Compose v2, Node 20+ and Python 3.11+ for the local path.

SHELL := /bin/sh
.DEFAULT_GOAL := help

COMPOSE  := docker compose
VENV     := .venv
PY       := $(VENV)/bin/python
PIP      := $(VENV)/bin/pip
ENV_FILE := .env
# Where `make verify` and `make up` expect the app. The port comes from
# FRONTEND_PORT in .env; override on the command line, `make verify APP_URL=...`.
APP_URL  ?= http://localhost:8080
# Seconds `make up` waits for the API to report ready. A cold start seeds 120
# days of prices, so this is generous on purpose.
READY_TIMEOUT ?= 300

VENV_STAMP := $(VENV)/.deps-installed
NPM_STAMP  := frontend/node_modules/.deps-installed

# The pinned psycopg-binary has no wheel for Python 3.14, and `python3` is 3.14
# on this machine, so the interpreter is chosen rather than assumed. 3.13 first:
# it has a wheel for everything pinned. Override with `make install PYTHON=...`.
PYTHON ?= $(shell command -v python3.13 >/dev/null && echo python3.13 || \
	(command -v python3.12 >/dev/null && echo python3.12) || \
	(command -v python3.11 >/dev/null && echo python3.11) || echo python3)

.PHONY: help env secrets rotate-jwt install up wait info dev down reset build \
        logs ps psql test check contract ui verify clean

# ---------------------------------------------------------------- help ------

# One printf piped into cat, rather than a dozen echoes, so `make help | head`
# closes the pipe without make reporting a broken pipe as an error.
help:
	@printf '%s\n' \
	'KisanSaathi' \
	'' \
	'  make up        build the images and run the whole stack   -> $(APP_URL)' \
	'  make dev       run the API and Vite locally, no Docker' \
	'  make check     backend tests, lint, frontend types and build' \
	'  make verify    check, then the API contract and a browser sweep' \
	'' \
	'Setup' \
	'  make env       create $(ENV_FILE) from the example with generated secrets' \
	'  make secrets   list every credential, in full, in SECRETS.local.md' \
	'  make rotate-jwt  new signing key, which signs everyone out' \
	'  make install   create $(VENV) and install the node modules' \
	'' \
	'The stack' \
	'  make down      stop the containers, keep the database' \
	'  make reset     stop and delete the database, then make up again' \
	'  make build     build the images without starting anything' \
	'  make logs      follow the container logs      (make logs SERVICE=backend)' \
	'  make ps        container status' \
	'  make psql      open a psql prompt on the compose database' \
	'' \
	'Checks' \
	'  make test      backend tests only' \
	'  make contract  frontend/backend contract check, needs a running API' \
	'  make ui        sign in as all eight demo accounts in Chrome and walk the routes' \
	'' \
	'Housekeeping' \
	'  make clean     remove build output and caches, never dependencies' \
	'' \
	'Every target is one command you could type yourself. Overridable:' \
	'  APP_URL  READY_TIMEOUT  PYTHON  SERVICE  PHONE' \
	| cat

# --------------------------------------------------------------- setup ------

env:
	@if [ -f $(ENV_FILE) ]; then \
	  echo '==> $(ENV_FILE) already exists, leaving it alone (it holds real secrets)'; \
	else \
	  cp $(ENV_FILE).example $(ENV_FILE); \
	  python3 -c 'import pathlib,re,secrets; \
p = pathlib.Path("$(ENV_FILE)"); t = p.read_text(); \
t = re.sub(r"(?m)^JWT_SECRET_KEY=.*$$", "JWT_SECRET_KEY=" + secrets.token_hex(32), t); \
t = re.sub(r"(?m)^POSTGRES_PASSWORD=.*$$", "POSTGRES_PASSWORD=" + secrets.token_urlsafe(12), t); \
p.write_text(t)'; \
	  echo '==> created $(ENV_FILE) with a generated JWT_SECRET_KEY and POSTGRES_PASSWORD'; \
	fi

# The live credentials, in one readable file. It is git-ignored and never
# committed, which is why the README documents every variable but no value: a
# tracked file is the wrong home for a signing key. Run this after changing
# $(ENV_FILE), and delete the file before sharing a screenshot.
secrets: env
	@python3 scripts/write_secrets_doc.py

# A new signing key invalidates every access and refresh token, so everyone is
# signed out and has to sign in again. Run `make up` afterwards to rebuild.
rotate-jwt: env
	@python3 -c 'import pathlib,re,secrets; \
p = pathlib.Path("$(ENV_FILE)"); t = p.read_text(); \
t = re.sub(r"(?m)^JWT_SECRET_KEY=.*$$", "JWT_SECRET_KEY=" + secrets.token_hex(32), t); \
p.write_text(t)'
	@python3 scripts/write_secrets_doc.py >/dev/null
	@echo '==> new JWT_SECRET_KEY in $(ENV_FILE). Every session is now invalid.'
	@echo '    Run `make up` to apply it. The database password is untouched.'

# Stamps rather than phony targets, so a second `make install` does nothing and a
# changed requirement file reinstalls exactly once.
$(VENV_STAMP): backend/requirements-dev.txt backend/requirements.txt
	@# A venv from an earlier session is usually already right. Verify by import
	@# rather than by the presence of the directory: a venv built with the wrong
	@# interpreter looks fine and fails on the first run.
	@if [ -x $(PY) ] && $(PY) -c 'import fastapi, sqlalchemy, psycopg, alembic, pytest, ruff' 2>/dev/null; then \
	  echo '==> $(VENV) already has the backend dependencies'; touch $@; exit 0; \
	fi
	@$(PYTHON) -c 'import sys; sys.exit(0 if sys.version_info < (3, 14) else 1)' || { \
	  echo '==> $(PYTHON) is too new for the pinned dependencies.'; \
	  echo '    Install Python 3.13, 3.12 or 3.11, or pass one: make install PYTHON=python3.13'; \
	  exit 1; }
	@if [ -d $(VENV) ]; then \
	  echo '==> $(VENV) exists but is unusable, rebuilding it with $(PYTHON)'; rm -rf $(VENV); \
	fi
	@echo '==> creating $(VENV) with $(PYTHON)'
	@$(PYTHON) -m venv $(VENV)
	@$(PIP) install --quiet --upgrade pip
	@$(PIP) install --quiet -r backend/requirements-dev.txt
	@touch $@
	@echo '==> backend dependencies installed in $(VENV)'

$(NPM_STAMP): frontend/package.json frontend/package-lock.json
	@echo '==> installing node modules in frontend/'
	@cd frontend && (npm ci 2>/dev/null || npm install)
	@touch $@
	@echo '==> node modules installed'

install: $(VENV_STAMP) $(NPM_STAMP)

# ----------------------------------------------------------- the stack ------

# The hero target. Builds both images from scratch, starts the stack, waits for
# the API to report ready and prints where to sign in.
up: env
	@$(MAKE) --no-print-directory build
	@$(COMPOSE) up -d --remove-orphans
	@$(MAKE) --no-print-directory wait
	@$(MAKE) --no-print-directory info

build: env
	@echo '==> building images'
	@$(COMPOSE) build

# Polls the API through nginx, so a 200 here means the whole chain is serving.
wait:
	@port=$$(sed -n 's/^FRONTEND_PORT=//p' $(ENV_FILE) 2>/dev/null | tail -1); \
	 port=$${port:-8080}; \
	 elapsed=0; \
	 until curl -fsS -o /dev/null "http://localhost:$$port/ready" 2>/dev/null; do \
	   elapsed=$$((elapsed + 2)); \
	   if [ $$elapsed -ge $(READY_TIMEOUT) ]; then \
	     echo; echo '==> the stack did not become ready within $(READY_TIMEOUT)s'; \
	     $(COMPOSE) ps; echo; $(COMPOSE) logs --tail=40 backend; exit 1; \
	   fi; \
	   printf '\r==> waiting for the API to be ready ... %ds' $$elapsed; sleep 2; \
	 done; printf '\r==> the API is ready                            \n'

info:
	@port=$$(sed -n 's/^FRONTEND_PORT=//p' $(ENV_FILE) 2>/dev/null | tail -1); \
	 port=$${port:-8080}; \
	 echo; \
	 echo '  app        http://localhost:'$$port; \
	 echo '  api docs   http://localhost:'$$port'/api/docs   (DOCS_ENABLED=false hides it)'; \
	 echo '  demo login 9000000001 admin, 9000000002 farmer, 9000000005 buyer ... Demo@1234'; \
	 echo '  logs       make logs        stop       make down'; \
	 echo

down:
	@$(COMPOSE) down --remove-orphans

# Destructive, and says so before it does it. The database and uploaded media
# live in named volumes; losing them means a full reseed on the next `make up`.
reset:
	@printf 'This deletes the database and uploaded media, then rebuilds and reseeds.\n'
	@printf 'Type "reset" to continue: '; read answer; \
	 [ "$$answer" = reset ] || { echo 'cancelled'; exit 1; }
	@$(COMPOSE) down -v --remove-orphans
	@$(MAKE) --no-print-directory up

logs:
	@$(COMPOSE) logs -f --tail=100 $(SERVICE)

ps:
	@$(COMPOSE) ps

psql:
	@user=$$(sed -n 's/^POSTGRES_USER=//p' $(ENV_FILE) 2>/dev/null | tail -1); \
	 db=$$(sed -n 's/^POSTGRES_DB=//p' $(ENV_FILE) 2>/dev/null | tail -1); \
	 $(COMPOSE) exec db psql -U "$${user:-kisan}" -d "$${db:-kisansaathi}"

# ------------------------------------------------------- local dev mode ------

# Both processes in one command, which is otherwise two terminals. Ctrl-C stops
# both. SQLite is used automatically outside Docker, so there is no database to
# install and no migration story beyond `alembic upgrade head`.
dev: install
	@set -e; \
	 jwt=$$(sed -n 's/^JWT_SECRET_KEY=//p' $(ENV_FILE) 2>/dev/null | tail -1); \
	 [ -n "$$jwt" ] || jwt=dev-only-not-a-secret; \
	 echo '==> migrating and seeding the local SQLite database (both are idempotent)'; \
	 ( cd backend && JWT_SECRET_KEY=$$jwt ../$(VENV)/bin/alembic upgrade head >/dev/null ); \
	 ( cd backend && JWT_SECRET_KEY=$$jwt ../$(PY) -m app.db.seed | tail -3 ); \
	 echo '==> API on http://localhost:8000, app on http://localhost:5173, Ctrl-C stops both'; \
	 ( cd backend && JWT_SECRET_KEY=$$jwt ../$(VENV)/bin/uvicorn app.main:app --reload --port 8000 ) & \
	 api=$$!; \
	 trap 'kill $$api 2>/dev/null' EXIT INT TERM; \
	 ( cd frontend && npm run dev )

# --------------------------------------------------------------- checks ------

test:
	@cd backend && ../$(VENV)/bin/pytest -q

# Everything that does not need a running API: the tests, both linters, the
# type check and the production build. This is the fast gate.
check: test
	@cd backend && ../$(VENV)/bin/ruff check app tests alembic
	@cd backend && ../$(VENV)/bin/ruff format --check app tests alembic | tail -1
	@cd frontend && npm run typecheck && echo 'typecheck: clean'
	@cd frontend && npm run lint && echo 'lint: clean'
	@cd frontend && npm run build >/dev/null && echo 'build: clean'
	@$(VENV)/bin/python scripts/gen_config_table.py --check

# Signs in as all eight demo accounts and calls every endpoint a screen uses.
# Needs something serving the API: `make up` or `make dev`.
contract:
	@BASE_URL=$(APP_URL)/api/v1 node scripts/verify_api.mjs

# Loads the app in real Chrome as every account and walks every route it can
# reach, failing on an uncaught exception or a console error. Needs the app.
ui:
	@node scripts/browser_sweep.mjs $(APP_URL)
	@node scripts/browser_check.mjs $(APP_URL) $(PHONE)

# The full gate. Assumes `make up`, since the contract and the browser both need
# a serving API. This is the run that catches a blank page.
verify: check contract ui
	@echo
	@echo 'all checks passed against $(APP_URL)'

# --------------------------------------------------------- housekeeping ------

# Build output and caches only. Never touches .venv, node_modules, the compose
# volumes or the local SQLite database: those are all expensive to rebuild.
clean:
	@rm -rf frontend/dist frontend/.vite backend/.pytest_cache backend/.ruff_cache
	@find backend -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@echo 'cleaned build output and caches'
