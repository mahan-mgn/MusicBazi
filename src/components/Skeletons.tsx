function Bar({ className = '', style }: { className?: string; style?: React.CSSProperties }) {
  return <div className={`skeleton rounded ${className}`} style={style} />
}

export function ResultsSkeleton() {
  return (
    <div className="rise space-y-8 rounded-2xl border border-line-soft bg-panel/50 p-4">
      <section className="space-y-3">
        <Bar className="h-3 w-24" />
        <div className="flex items-center gap-3">
          <Bar className="size-14 shrink-0 rounded-lg" />
          <div className="flex-1 space-y-2">
            <Bar className="h-3 w-1/3" />
            <Bar className="h-2.5 w-1/5" />
          </div>
        </div>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-3">
            <Bar className="size-10 shrink-0 rounded-lg" />
            <div className="flex-1 space-y-2">
              <Bar className="h-2.5" style={{ width: `${45 + i * 8}%` }} />
              <Bar className="h-2 w-1/6" />
            </div>
          </div>
        ))}
      </section>

      <section className="space-y-3">
        <Bar className="h-3 w-20" />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="space-y-2">
              <Bar className="aspect-square rounded-lg" />
              <Bar className="h-2.5 w-3/4" />
              <Bar className="h-2 w-1/2" />
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}

export function AlbumSkeleton() {
  return (
    <div className="rise space-y-4 rounded-2xl border border-line-soft bg-panel/50 p-4">
      <div className="flex items-center gap-3 sm:gap-4">
        <Bar className="size-16 shrink-0 rounded-xl sm:size-20" />
        <div className="min-w-0 flex-1 space-y-2">
          <Bar className="h-4 w-2/3" />
          <Bar className="h-2.5 w-full" />
        </div>
        <Bar className="hidden h-9 w-28 shrink-0 rounded-full md:block" />
      </div>
      {Array.from({ length: 8 }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Bar className="size-10 shrink-0 rounded-lg" />
          <Bar className="h-2.5 min-w-0 flex-1" />
          <Bar className="h-2.5 w-10 shrink-0" />
        </div>
      ))}
    </div>
  )
}

export function ArtistSkeleton() {
  return (
    <div className="rise space-y-6 rounded-3xl border border-line-soft bg-panel/50 p-5 sm:p-7">
      <div className="flex flex-col items-center gap-6 sm:flex-row sm:items-end">
        <Bar className="size-36 shrink-0 rounded-full sm:size-44" />
        <div className="min-w-0 flex-1 space-y-3 text-center sm:text-start">
          <Bar className="mx-auto h-4 w-28 rounded-full sm:mx-0" />
          <Bar className="mx-auto h-8 w-2/3 sm:mx-0" />
          <Bar className="mx-auto h-3 w-1/3 sm:mx-0" />
          <div className="flex justify-center gap-2 sm:justify-start">
            <Bar className="size-14 rounded-full" />
            <Bar className="size-11 rounded-full" />
            <Bar className="h-11 w-28 rounded-full" />
          </div>
        </div>
      </div>
      {Array.from({ length: 5 }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Bar className="size-7 shrink-0 rounded-md" />
          <Bar className="size-10 shrink-0 rounded-lg" />
          <Bar className="h-2.5 min-w-0 flex-1" />
          <Bar className="hidden h-2.5 w-24 shrink-0 md:block" />
        </div>
      ))}
    </div>
  )
}
