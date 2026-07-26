# Persistent dev-agent box: runs Claude Code under Remote Control against a
# checkout of this repo, so Dylan can pair to it from browser/phone instead
# of needing his own laptop running. See AGENTS.md's "Dev-agent deployment"
# section for the full story (why Remote Control needs interactive OAuth
# login, why there's no [http_service], the manual bootstrap steps).
#
# Needs: Node (Claude Code CLI is an npm package), Python/uv (to run
# `cd backend && uv run pytest`), git + flyctl (to act on this repo and the
# other three apps the same way this sandbox already does), and tmux (so
# Dylan can `fly ssh console` in and attach to the supervised `claude`
# process to complete/renew the interactive OAuth login — see entrypoint.sh).
FROM node:22-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates tmux python3 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:/root/.fly/bin:${PATH}"

RUN curl -L https://fly.io/install.sh | sh

RUN npm install -g @anthropic-ai/claude-code

COPY entrypoint.sh /devagent-entrypoint.sh
RUN chmod +x /devagent-entrypoint.sh

CMD ["/devagent-entrypoint.sh"]
