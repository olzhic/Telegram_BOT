CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS sources (
  source_id   text PRIMARY KEY,
  title       text NOT NULL,
  publisher   text NOT NULL,
  url         text NOT NULL,
  language    text NOT NULL CHECK (language IN ('ru', 'kk')),
  category    text NOT NULL,
  checked_at  date NOT NULL,
  status      text NOT NULL CHECK (status IN ('verified', 'needs_verification', 'excluded'))
);

CREATE TABLE IF NOT EXISTS chunks (
  chunk_id    text PRIMARY KEY,
  source_id   text NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
  position    int NOT NULL,
  content     text NOT NULL,
  embedding   vector(1024) NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
  chat_key    text PRIMARY KEY,
  state       text NOT NULL,
  data        jsonb NOT NULL DEFAULT '{}',
  updated_at  timestamptz NOT NULL DEFAULT now()
);

GRANT USAGE ON SCHEMA public TO adal_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON sources, chunks TO adal_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON conversations TO adal_app;
