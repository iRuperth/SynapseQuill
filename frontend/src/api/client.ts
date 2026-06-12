// Single typed axios layer. Components call these functions directly.
import axios from 'axios'
import type {
  AgentRouteResult,
  Architecture,
  Bracket,
  CalendarSummary,
  ContentRecord, FinanceResult, FreeformResult, GenerationStatus, GlobalConfig,
  LabHistoryRecord, Match,
  MatchDetail, PowerRanking, Profile, ProfileSummary, ScienceResult,
} from '../types'

const http = axios.create({ baseURL: '/api' })

export const getGlobalConfig = () =>
  http.get<GlobalConfig>('/config/global').then((r) => r.data)

export const getArchitecture = () =>
  http.get<Architecture>('/architecture').then((r) => r.data)

export const listProfiles = () =>
  http.get<ProfileSummary[]>('/profiles').then((r) => r.data)

export const getProfile = (id: string) =>
  http.get<Profile>(`/profiles/${id}`).then((r) => r.data)

export const createProfile = (id: string, name?: string) =>
  http.post<Profile>('/profiles', { id, name }).then((r) => r.data)

export const updateProfile = (id: string, updates: Record<string, unknown>) =>
  http.patch<Profile>(`/profiles/${id}`, { updates }).then((r) => r.data)

export const getMatches = (id: string, day?: string) =>
  http.get<Match[]>(`/profiles/${id}/matches`, { params: { day } }).then((r) => r.data)

export const getMatchDetail = (id: string, fixtureId: number) =>
  http.get<MatchDetail>(`/profiles/${id}/matches/${fixtureId}`).then((r) => r.data)

export const getContent = (id: string) =>
  http.get<ContentRecord[]>(`/profiles/${id}/content`).then((r) => r.data)

export const deleteContent = (id: string, contentId: string) =>
  http.delete(`/profiles/${id}/content/${contentId}`).then((r) => r.data)

export const generate = (id: string, fixtureId: number,
  opts?: { do_video?: boolean; do_upload?: boolean; format?: string }) =>
  http.post(`/profiles/${id}/generate`, {
    fixture_id: fixtureId,
    do_video: opts?.do_video ?? true,
    do_upload: opts?.do_upload ?? false,
    format: opts?.format ?? 'reel',
  }).then((r) => r.data)

export const generateDigest = (
  id: string,
  opts?: { day?: string; format?: string; fixture_ids?: number[]; brief?: string },
) =>
  http.post(`/profiles/${id}/digest`, {
    day: opts?.day ?? null,
    format: opts?.format ?? 'youtube',
    fixture_ids: opts?.fixture_ids ?? null,
    brief: opts?.brief ?? '',
  }).then((r) => r.data)

export const getWorldCupCalendar = () =>
  http.get<CalendarSummary>('/worldcup/calendar').then((r) => r.data)

export const getWorldCupBracket = () =>
  http.get<Bracket>('/worldcup/bracket').then((r) => r.data)

export const getPowerRanking = () =>
  http.get<PowerRanking>('/worldcup/power-ranking').then((r) => r.data)

export const getStatus = (id: string) =>
  http.get<GenerationStatus>(`/profiles/${id}/status`).then((r) => r.data)

export const cancelGeneration = (id: string) =>
  http.post(`/profiles/${id}/cancel`).then((r) => r.data)

export const publishVideo = (id: string, fixtureId: number, privacy: string) =>
  http.post<{ ok: boolean; youtube_url: string; privacy: string }>(
    `/profiles/${id}/publish`, { fixture_id: fixtureId, privacy },
  ).then((r) => r.data)

// ── YouTube upload automation (bulk / scheduled) ────────────────────
export const getPendingUploads = (id: string) =>
  http.get<{ pending: string[] }>(`/profiles/${id}/uploads/pending`).then((r) => r.data.pending)

export const uploadAllPending = (id: string) =>
  http.post<{ uploaded: unknown[]; results: { content_id: string; ok: boolean; error?: string }[] }>(
    `/profiles/${id}/uploads/bulk`,
  ).then((r) => r.data)

export const scheduleUpload = (id: string, contentId: string, when: number) =>
  http.post(`/profiles/${id}/uploads/schedule`, { content_id: contentId, when }).then((r) => r.data)

export const getUploadSchedule = (id: string) =>
  http.get<{ schedule: { content_id: string; when: number; status: string; youtube_url?: string; error?: string }[] }>(
    `/profiles/${id}/uploads/schedule`,
  ).then((r) => r.data.schedule)

export const cancelScheduledUpload = (id: string, contentId: string) =>
  http.delete(`/profiles/${id}/uploads/schedule/${contentId}`).then((r) => r.data)

// ── Freeform content (essential level: any topic the user provides) ──
export const generateFreeform = (
  id: string,
  body: { topic: string; audience?: string; platforms?: string[]; language?: string; extra?: string },
) =>
  http.post<FreeformResult>(`/profiles/${id}/content/freeform`, body).then((r) => r.data)

// ── Topic / educational video (clean backdrop + logo + narration) ───
export const generateTopicVideo = (
  id: string,
  body: { topic: string; source_text?: string; audience?: string; format?: string; do_upload?: boolean },
) =>
  http.post(`/profiles/${id}/topic-video`, {
    topic: body.topic,
    source_text: body.source_text ?? '',
    audience: body.audience ?? '',
    format: body.format ?? 'reel',
    do_video: true,
    do_upload: body.do_upload ?? false,
  }).then((r) => r.data)

// ── Advanced / expert features ──────────────────────────────────────
export const getScienceTopics = () =>
  http.get<{ topics: string[] }>('/science/topics').then((r) => r.data.topics)

export const explainScience = (topic: string, language: string, useGraph = true, profileId?: string) =>
  http.post<ScienceResult>('/science/explain', { topic, language, use_graph: useGraph, profile_id: profileId })
    .then((r) => r.data)

export const financeNews = (ticker: string, profileId?: string) =>
  http.post<FinanceResult>('/finance/news', { ticker, profile_id: profileId }).then((r) => r.data)

export const routeAgent = (request: string, profileId?: string) =>
  http.post<AgentRouteResult>('/agents/route', { request, profile_id: profileId }).then((r) => r.data)

// ── Laboratorio IA / free-topic request history ─────────────────────
export const getLabHistory = (profileId: string) =>
  http.get<LabHistoryRecord[]>(`/profiles/${profileId}/lab/history`).then((r) => r.data)

export const deleteLabHistory = (profileId: string, id: string) =>
  http.delete(`/profiles/${profileId}/lab/history/${id}`).then((r) => r.data)
