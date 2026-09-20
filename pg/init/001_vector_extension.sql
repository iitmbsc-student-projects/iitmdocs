-- The ONLY hand-written SQL in this project.
--
-- pgvector must exist before the `faqs` table can have a `vector(1024)` column, and
-- enabling a Postgres extension is not something SQLAlchemy's ORM can express. The
-- `faqs` table itself is created from the Faq model in pg/faq_api/orm.py by
-- `Base.metadata.create_all` in embed.py - do not add table DDL here.
--
-- Docker runs this once, on first initialisation of the postgres data volume.
CREATE EXTENSION IF NOT EXISTS vector;
