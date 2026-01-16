-- Database initialization SQL
-- This runs automatically when PostgreSQL container starts

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Jobs table
CREATE TABLE IF NOT EXISTS jobs (
    job_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL,
    job_type VARCHAR(50) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    config JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_user_status ON jobs(user_id, status);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);

-- Platform content table
CREATE TABLE IF NOT EXISTS platform_content (
    content_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID REFERENCES jobs(job_id) ON DELETE CASCADE,
    platform VARCHAR(50) NOT NULL,
    platform_video_id VARCHAR(255) NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    description TEXT,
    author VARCHAR(255),
    views BIGINT,
    likes BIGINT,
    comments BIGINT,
    duration_seconds INTEGER,
    upload_date TIMESTAMP WITH TIME ZONE,
    trending_score FLOAT,
    metadata JSONB,
    discovered_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(platform, platform_video_id)
);

CREATE INDEX IF NOT EXISTS idx_content_job_platform ON platform_content(job_id, platform);
CREATE INDEX IF NOT EXISTS idx_content_trending ON platform_content(trending_score DESC);

-- Video analysis table
CREATE TABLE IF NOT EXISTS video_analysis (
    analysis_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    content_id UUID REFERENCES platform_content(content_id) ON DELETE CASCADE,
    ai_model VARCHAR(100) NOT NULL,
    quality_score FLOAT,
    virality_score FLOAT,
    relevance_score FLOAT,
    content_summary TEXT,
    detected_topics TEXT[],
    visual_analysis JSONB,
    sentiment VARCHAR(50),
    recommended BOOLEAN DEFAULT FALSE,
    analyzed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_analysis_recommended ON video_analysis(content_id, recommended);
CREATE INDEX IF NOT EXISTS idx_analysis_scores ON video_analysis(quality_score, virality_score, relevance_score);

-- Downloaded videos table
CREATE TABLE IF NOT EXISTS downloaded_videos (
    download_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    content_id UUID REFERENCES platform_content(content_id) ON DELETE CASCADE,
    local_path TEXT NOT NULL,
    s3_path TEXT,
    file_size_bytes BIGINT,
    resolution VARCHAR(20),
    format VARCHAR(20),
    fps INTEGER,
    duration_seconds FLOAT,
    downloaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_download_content ON downloaded_videos(content_id);

-- Output videos table
CREATE TABLE IF NOT EXISTS output_videos (
    output_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID REFERENCES jobs(job_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    tags TEXT[],
    ranking_items JSONB,
    local_path TEXT NOT NULL,
    s3_path TEXT,
    duration_seconds FLOAT,
    resolution VARCHAR(20),
    file_size_bytes BIGINT,
    manual_edits JSONB,
    render_settings JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_output_job ON output_videos(job_id);

-- Customization presets table
CREATE TABLE IF NOT EXISTS customization_presets (
    preset_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL,
    preset_name VARCHAR(255) NOT NULL,
    caption_style JSONB,
    audio_settings JSONB,
    transition_style VARCHAR(50),
    ranking_overlay JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_preset_user ON customization_presets(user_id);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger for jobs table
DROP TRIGGER IF EXISTS update_jobs_updated_at ON jobs;
CREATE TRIGGER update_jobs_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
