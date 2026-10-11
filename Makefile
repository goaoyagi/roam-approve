.DEFAULT_GOAL := help

.PHONY: help install up down bridge test lint fw-build fw-test fw-upload sim e2e gen-tokens check-secrets

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

install: ## Sync the uv workspace (requires uv)
	uv sync --all-packages

up: ## Start mosquitto via docker compose (requires docker)
	docker compose up -d mosquitto

down: ## Stop docker compose services
	docker compose down

bridge: ## Run the Bridge locally (binds 127.0.0.1:8000 by default)
	uv run uvicorn roam_approve_bridge.main:app --host $${ROAM_BIND:-127.0.0.1} --port $${ROAM_PORT:-8000}

test: ## Run host tests and the secrets check
	uv run pytest host
	$(MAKE) check-secrets

lint: ## Ruff check on host/ and tools/
	uv run ruff check host tools

fw-build: ## Build firmware for M5StickC PLUS SE (requires pio)
	cd device/firmware && pio run -e m5stickc-plus-se

fw-test: ## Run native firmware tests (requires pio)
	cd device/firmware && pio test -e native

fw-upload: ## Flash firmware to device (requires pio)
	cd device/firmware && pio run -e m5stickc-plus-se -t upload

sim: ## Fake device simulator
	@echo "TODO: not implemented yet (see GitHub issues)"; exit 1

e2e: ## End-to-end test
	@echo "TODO: not implemented yet (see GitHub issues)"; exit 1

gen-tokens: ## Generate agent/device tokens into .env (never prints values)
	tools/gen_tokens.sh

check-secrets: ## Verify no secrets are tracked (requires gitleaks)
	tools/check_secrets.sh
