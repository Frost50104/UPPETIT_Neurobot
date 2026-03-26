const isStaging = import.meta.env.VITE_APP_ENV === 'staging'

export default function StagingBadge() {
  if (!isStaging) return null

  return (
    <span style={{
      background: '#FDB913',
      color: '#111',
      fontSize: '.65rem',
      fontWeight: 600,
      padding: '.15rem .5rem',
      borderRadius: 6,
      letterSpacing: '.04em',
      textTransform: 'uppercase',
      lineHeight: 1,
      flexShrink: 0,
    }}>
      staging
    </span>
  )
}
