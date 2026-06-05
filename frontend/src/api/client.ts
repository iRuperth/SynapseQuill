// Single typed axios layer. Components call these functions directly.
import axios from 'axios'
import type {
  CalendarSummary,
  ContentRecord, GenerationStatus, GlobalConfig, Match, MatchDetail, Profile, ProfileSummary,
} from '../types'

const http = axios.create({ baseURL: '/api' })

export const getGlobalConfig = () =>
  http.get<GlobalConfig>('/config/global').then((r) => r.data)

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

export const generate = (id: string, fixtureId: number,
  opts?: { do_video?: boolean; do_upload?: boolean; format?: string }) =>
  http.post(`/profiles/${id}/generate`, {
    fixture_id: fixtureId,
    do_video: opts?.do_video ?? true,
    do_upload: opts?.do_upload ?? false,
    format: opts?.format ?? 'reel',
  }).then((r) => r.data)

export const generateDigest = (id: string, opts?: { day?: string; format?: string }) =>
  http.post(`/profiles/${id}/digest`, {
    day: opts?.day ?? null,
    format: opts?.format ?? 'reel',
  }).then((r) => r.data)

export const getWorldCupCalendar = () =>
  http.get<CalendarSummary>('/worldcup/calendar').then((r) => r.data)

export const getStatus = (id: string) =>
  http.get<GenerationStatus>(`/profiles/${id}/status`).then((r) => r.data)

export const cancelGeneration = (id: string) =>
  http.post(`/profiles/${id}/cancel`).then((r) => r.data)

export const publishVideo = (id: string, fixtureId: number, privacy: string) =>
  http.post<{ ok: boolean; youtube_url: string; privacy: string }>(
    `/profiles/${id}/publish`, { fixture_id: fixtureId, privacy },
  ).then((r) => r.data)
