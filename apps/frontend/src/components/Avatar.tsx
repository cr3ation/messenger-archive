import { Users } from 'lucide-react'
import { avatarStyle, initials } from '../lib/format'

interface Props {
  name: string
  hue: number
  size?: number
  group?: boolean
  className?: string
}

export function Avatar({ name, hue, size = 36, group = false, className = '' }: Props) {
  const style = { ...avatarStyle(hue), width: size, height: size, fontSize: size * 0.36 }

  return (
    <div
      className={`flex shrink-0 select-none items-center justify-center rounded-full font-semibold ${className}`}
      style={style}
      title={name}
      aria-hidden
    >
      {group ? <Users size={size * 0.45} /> : initials(name)}
    </div>
  )
}
