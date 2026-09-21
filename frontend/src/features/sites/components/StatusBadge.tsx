import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

import type { CookieStatus } from '../types'

const LABELS: Record<CookieStatus, string> = {
  none: 'No cookies',
  valid: 'Valid',
  expiring: 'Expiring',
  expired: 'Expired',
  flagged: 'Possibly invalid',
}

const TONES: Record<CookieStatus, string> = {
  none: '',
  valid: '',
  expiring: 'border-amber-500 text-amber-600 dark:text-amber-400',
  expired: 'border-destructive text-destructive',
  flagged: 'border-destructive text-destructive',
}

export default function StatusBadge({ status }: { status: CookieStatus }) {
  return (
    <Badge variant={status === 'valid' ? 'default' : 'outline'} className={cn(TONES[status])}>
      {LABELS[status]}
    </Badge>
  )
}
