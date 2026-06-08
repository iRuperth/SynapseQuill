// Mirrors the backend's BrandProfile.to_dict() and API responses.

export interface ProfileSummary {
  id: string
  name: string
  team: string
  language: string
}

export interface Profile {
  id: string
  name: string
  team: string
  language: string
  competition: { league_id: number; season: number }
  llm_provider: string
  voice: { provider: string; voice: string; rate: string }
  media: { sources: string[]; image_provider: string }
  style: { visual_style: string }
  youtube: { practice_mode: boolean; privacy: string }
  has_system_preamble: boolean
}

export interface Match {
  fixture_id: number
  status: string
  home: string
  away: string
  home_goals: number | null
  away_goals: number | null
  home_logo: string
  away_logo: string
  finished: boolean
  scoreline: string
}

export interface ContentRecord {
  fixture_id: number
  scoreline: string
  narration?: string
  metadata?: { title: string; description: string; tags: string[] }
  video?: string
  youtube_url?: string
  generated_at?: string
  status?: string
}

export interface GenerationStatus {
  state: 'idle' | 'running' | 'done' | 'error'
  step?: string
  message?: string
  fixture_id?: number
  result?: ContentRecord
}

export interface GlobalConfig {
  llm_providers: string[]
  image_providers: string[]
  media_sources: string[]
  tts_providers: string[]
  languages: string[]
  youtube_privacy: string[]
}
