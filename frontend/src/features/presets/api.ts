import { request } from '@/api/client'

import type { Preset, PresetCreate, PresetUpdate } from './types'

export const presetsQueryKey = ['presets'] as const

export const listPresets = () => request<Preset[]>('GET', '/api/presets')

export const createPreset = (body: PresetCreate) => request<Preset>('POST', '/api/presets', body)

export const updatePreset = (id: number, body: PresetUpdate) =>
  request<Preset>('PATCH', `/api/presets/${id}`, body)

export const deletePreset = (id: number) => request<void>('DELETE', `/api/presets/${id}`)
