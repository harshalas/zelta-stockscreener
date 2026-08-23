ALTER TABLE analysis_jobs
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

ALTER TABLE analysis_jobs
    DROP CONSTRAINT IF EXISTS analysis_jobs_status_check;

ALTER TABLE analysis_jobs
    ADD CONSTRAINT analysis_jobs_status_check
    CHECK (
        status IN (
            'queued',
            'gathering_data',
            'reading_news',
            'calculating_risk',
            'complete',
            'failed'
        )
    );
