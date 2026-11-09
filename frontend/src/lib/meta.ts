import { useQuery } from '@tanstack/react-query';
import { api } from './api';
import type { Meta } from './types';

/** Server capabilities (demo mode, OCR, voice). Cached: it only changes on redeploy. */
export function useMeta() {
  return useQuery({ queryKey: ['meta'], queryFn: () => api<Meta>('/api/meta', { auth: false }), staleTime: 10 * 60_000 });
}
