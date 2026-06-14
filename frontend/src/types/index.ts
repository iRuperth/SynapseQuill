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
  competition: {
    preset: string
    provider: string
    league_id: number
    season: number
    mode: string
  }
  llm_provider: string
  voice: { preset: string; provider: string; voice: string; rate: string }
  media: { sources: string[]; image_provider: string }
  style: { visual_style: string }
  youtube: { practice_mode: boolean; privacy: string; auto_upload?: boolean }
  has_system_preamble: boolean
}

export interface CompetitionOption {
  key: string
  label: string
  scorers: string
}

export interface VoiceOption {
  key: string
  label: string
  language: string
}

export interface CalendarMatch {
  team1: string
  team2: string
  time: string
  group: string
  round: string
  ground: string
}

export interface CalendarDay {
  date: string
  phase: string
  count: number
  matches: CalendarMatch[]
}

export interface CalendarSummary {
  total_matches: number
  total_days: number
  start: string
  end: string
  next_match_day: string | null
  next_match_day_count: number
  days_until_next: number | null
  days: CalendarDay[]
}

// ── World Cup knockout bracket ──────────────────────────────────────
export interface BracketSlot {
  label: string          // placeholder shown until resolved, e.g. "2A", "W74"
  name: string | null    // real team once known
  flag: string | null
  score: number | null
  winner: boolean
}

export interface BracketMatch {
  num: number
  round: string
  date: string
  time: string
  status: string         // SCHEDULED | LIVE | FINISHED
  team1: BracketSlot
  team2: BracketSlot
}

export interface BracketRound {
  key: string            // r32 | r16 | qf | sf | final | third
  round: string
  matches: BracketMatch[]
}

export interface Bracket {
  rounds: BracketRound[]
  updated_at: string
}

// ── Power ranking (FIFA World Ranking of the 48 WC2026 teams) ───────
export interface PowerRankingRow {
  pos: number        // display position 1..48 among WC teams
  rank: number       // global FIFA rank
  team: string
  points: number
  group: string
  flag: string
}

export interface PowerRanking {
  source: string
  as_of: string
  count: number
  rows: PowerRankingRow[]
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
  competition?: string
  date?: string
  kickoff?: string                  // full ISO datetime (UTC) for date + time
}

export interface MatchGoal {
  player: string
  team: string
  minute: string
  kind: string
  description: string
}

export interface MatchCard {
  player: string
  team: string
  minute: string
  color: string
}

export interface MatchDetail extends Match {
  venue: string
  city: string
  country: string
  goals: MatchGoal[]
  cards: MatchCard[]
}

export interface ContentRecord {
  id?: string                       // stable stem for playback/deletion
  fixture_id?: number               // absent for digests (keyed by id/day)
  scoreline: string
  day?: string                      // digests use day instead of scoreline
  type?: string                     // 'digest' for daily digests
  narration?: string
  metadata?: { title: string; description: string; tags: string[] }
  video?: string
  video_url?: string
  youtube_url?: string
  generated_at?: string
  status?: string
}

export interface GenerationStatus {
  state: 'idle' | 'running' | 'done' | 'error'
  step?: string
  message?: string
  progress?: number
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
  competitions: CompetitionOption[]
  voices: VoiceOption[]
}

// ── Freeform content (essential level) ──────────────────────────────
export interface FreeformResult {
  topic: string
  audience: string
  content: Record<string, string>   // { platform: text }
}

// ── Advanced / expert feature responses ─────────────────────────────
export interface ScienceResult {
  topic: string
  explanation: string
}

export interface FinanceResult {
  ticker: string
  summary: string
}

export interface AgentRouteResult {
  request: string
  result: string
}

// One saved Laboratorio IA / free-topic request (history).
export interface LabHistoryRecord {
  id: string
  kind: 'science' | 'finance' | 'agents' | 'freeform'
  prompt: string
  result: string
  meta?: Record<string, unknown>
  created_at?: string
}

// ── Architecture page (self-describing system map from /api/architecture) ──
export interface ArchService {
  name: string
  easy: string
  model: string
  env: string
  file: string
  free: 'yes' | 'tier' | 'key' | 'local' | 'oauth'
  detail: string
}
export interface ArchServiceGroup {
  group: string
  items: ArchService[]
}
export interface ArchStep {
  easy: string
  tech: string
  file: string
  detail: string
}
export interface ArchFlow {
  id: string
  title: string
  easy: string
  input: string
  output: string
  orchestrator: string
  endpoint: string
  steps: ArchStep[]
}
export interface Architecture {
  services: ArchServiceGroup[]
  flows: ArchFlow[]
}
