"""Agent runtime. Must not import FastAPI or app.db: it takes a resolved AgentConfig plus
message history and yields typed AgentEvents."""
