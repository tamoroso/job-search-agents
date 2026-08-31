.PHONY: dev db-shell reset

dev:
	docker compose up -d
	uv sync

db-shell:
	docker compose exec db psql -U jobagent -d jobagent

reset:
	docker compose down -v && docker compose up -d