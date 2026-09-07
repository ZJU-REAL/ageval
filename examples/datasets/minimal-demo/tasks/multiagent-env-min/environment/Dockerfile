FROM ageval-attempt:base

# multiagent-env-min runs its PostgreSQL inside the Attempt box (task-local
# resource; no runtime-managed environment_resource behind it).
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql postgresql-client \
    && rm -rf /var/lib/apt/lists/*
USER ageval
