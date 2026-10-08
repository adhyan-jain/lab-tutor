.PHONY: deploy refresh-llm-cache list-llm-cache

# Create/verify the native Vertex context caches for the currently
# configured cacheable experiments, and delete any that no longer match
# the current source (stale fingerprint). See docs/LLM_CACHING.md.
refresh-llm-cache:
	.venv/bin/python -m backend.llm.context_cache --refresh --delete-stale

# List LabTutor's live context caches (display name and expiry).
list-llm-cache:
	.venv/bin/python -m backend.llm.context_cache --list

# Pull the latest master, rebuild changed images and (re)start the stack.
# Also resumes stopped or paused containers. Data volumes are never touched.
deploy:
	git pull --ff-only origin master
	-docker compose -f infra/docker-compose.yml unpause 2>/dev/null
	docker compose -f infra/docker-compose.yml up -d --build
	docker compose -f infra/docker-compose.yml ps
