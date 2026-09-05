import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  Check,
  FileArchive,
  Loader2,
  MessagesSquare,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import { api, uploadArchive } from '../api'
import { formatBytes, formatNumber } from '../lib/format'
import type { ArchiveState, ImportProgress } from '../types'

interface Props {
  /** First run blocks the app; opening it later to add archives does not. */
  dismissable: boolean
  /** Existing contents, so "start over" can name exactly what it will delete. */
  existing?: ArchiveState | null
  onDone: () => void
  onClose?: () => void
}

type Mode = 'add' | 'replace'

type Stage = 'choose' | 'uploading' | 'importing' | 'done'

interface Queued {
  file: File
  loaded: number
  status: 'waiting' | 'uploading' | 'uploaded' | 'error'
  error?: string
}

const STATE_LABELS: Record<ImportProgress['state'], string> = {
  idle: 'Waiting',
  unpacking: 'Unpacking the archives',
  running: 'Reading conversations',
  deriving: 'Building search index and statistics',
  done: 'Done',
  error: 'Something went wrong',
}

export function SetupWizard({ dismissable, existing, onDone, onClose }: Props) {
  const [stage, setStage] = useState<Stage>('choose')
  const [queue, setQueue] = useState<Queued[]>([])
  const [dragging, setDragging] = useState(false)
  const [progress, setProgress] = useState<ImportProgress | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [free, setFree] = useState<number | null>(null)
  const [mode, setMode] = useState<Mode>('add')
  const [confirmedReplace, setConfirmedReplace] = useState(false)
  const abortRef = useRef<(() => void) | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api.disk().then((disk) => setFree(disk.free_bytes)).catch(() => setFree(null))
  }, [])

  const addFiles = useCallback((files: FileList | null) => {
    if (!files) return
    const zips = Array.from(files).filter((file) => file.name.toLowerCase().endsWith('.zip'))
    if (!zips.length) {
      setError('Only .zip files can be uploaded.')
      return
    }
    setError(null)
    setQueue((current) => {
      const names = new Set(current.map((entry) => entry.file.name))
      const added = zips
        .filter((file) => !names.has(file.name))
        .map<Queued>((file) => ({ file, loaded: 0, status: 'waiting' }))
      return [...current, ...added]
    })
  }, [])

  const totalBytes = queue.reduce((sum, entry) => sum + entry.file.size, 0)
  const uploadedBytes = queue.reduce((sum, entry) => sum + entry.loaded, 0)
  // The zip and its unpacked contents coexist until the archive is removed.
  const spaceTight = free !== null && free < totalBytes * 2
  const hasExisting = Boolean(existing?.has_data)
  const blockedByConfirm = mode === 'replace' && !confirmedReplace

  const start = async () => {
    setStage('uploading')
    setError(null)

    const names: string[] = []
    for (let index = 0; index < queue.length; index += 1) {
      if (queue[index].status === 'uploaded') {
        names.push(queue[index].file.name)
        continue
      }

      setQueue((current) =>
        current.map((entry, i) => (i === index ? { ...entry, status: 'uploading' } : entry)),
      )

      const { promise, abort } = uploadArchive(queue[index].file, (loaded) => {
        setQueue((current) => current.map((entry, i) => (i === index ? { ...entry, loaded } : entry)))
      })
      abortRef.current = abort

      try {
        const uploaded = await promise
        names.push(uploaded.name)
        setQueue((current) =>
          current.map((entry, i) =>
            i === index ? { ...entry, status: 'uploaded', loaded: entry.file.size } : entry,
          ),
        )
      } catch (problem) {
        const message = (problem as Error).message
        setQueue((current) =>
          current.map((entry, i) =>
            i === index ? { ...entry, status: 'error', error: message } : entry,
          ),
        )
        setError(`${queue[index].file.name}: ${message}`)
        setStage('choose')
        return
      } finally {
        abortRef.current = null
      }
    }

    setStage('importing')
    try {
      await api.startImport(names, mode === 'replace')
    } catch (problem) {
      setError((problem as Error).message)
      setStage('choose')
    }
  }

  // Poll the import job. The server does the unpacking, so this is the only
  // window into progress once the uploads are finished.
  useEffect(() => {
    if (stage !== 'importing') return
    const timer = setInterval(async () => {
      try {
        const status = await api.importStatus()
        setProgress(status)
        if (status.state === 'done') {
          clearInterval(timer)
          setStage('done')
        } else if (status.state === 'error') {
          clearInterval(timer)
          setError(status.error ?? 'The import failed')
          setStage('choose')
        }
      } catch {
        /* keep polling; the API may briefly be busy */
      }
    }, 700)
    return () => clearInterval(timer)
  }, [stage])

  const busy = stage === 'uploading' || stage === 'importing'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/80 p-4 backdrop-blur">
      <div className="panel w-full max-w-2xl animate-slide-up rounded-2xl border shadow-2xl">
        <header className="flex items-start gap-3 border-b border-zinc-200 p-5 dark:border-zinc-800">
          <div className="rounded-xl bg-indigo-500/15 p-2 text-indigo-500">
            <MessagesSquare size={22} />
          </div>
          <div className="min-w-0">
            <h1 className="text-lg font-semibold">Import your Messenger archive</h1>
            <p className="mt-0.5 text-sm text-zinc-500">
              Facebook splits the export across several zip files — one holds the text, the
              others hold the photos. <strong>Pick them all at once</strong> and they are merged
              into a single archive.
            </p>
          </div>
          {dismissable && onClose && (
            <button type="button" onClick={onClose} className="btn-ghost ml-auto px-2" aria-label="Close">
              <X size={16} />
            </button>
          )}
        </header>

        <div className="space-y-4 p-5">
          {stage === 'choose' && hasExisting && (
            <fieldset className="space-y-2">
              <legend className="mb-1 text-sm font-medium">
                You already have an archive imported
              </legend>

              <label
                className={`flex cursor-pointer gap-3 rounded-xl border p-3 transition-colors ${
                  mode === 'add'
                    ? 'border-indigo-500 bg-indigo-500/10'
                    : 'border-zinc-200 hover:border-zinc-300 dark:border-zinc-800'
                }`}
              >
                <input
                  type="radio"
                  name="import-mode"
                  checked={mode === 'add'}
                  onChange={() => setMode('add')}
                  className="mt-0.5"
                />
                <span className="text-sm">
                  <span className="font-medium">Add to the current archive</span>
                  <span className="mt-0.5 block text-xs text-zinc-500">
                    New conversations and messages are added. Duplicates are merged and your
                    saved memories survive. You have {formatNumber(existing!.messages)}{' '}
                    messages today, and will have at least as many afterwards.
                  </span>
                </span>
              </label>

              <label
                className={`flex cursor-pointer gap-3 rounded-xl border p-3 transition-colors ${
                  mode === 'replace'
                    ? 'border-red-500 bg-red-500/10'
                    : 'border-zinc-200 hover:border-zinc-300 dark:border-zinc-800'
                }`}
              >
                <input
                  type="radio"
                  name="import-mode"
                  checked={mode === 'replace'}
                  onChange={() => setMode('replace')}
                  className="mt-0.5"
                />
                <span className="text-sm">
                  <span className="font-medium">Start over from scratch</span>
                  <span className="mt-0.5 block text-xs text-zinc-500">
                    Deletes everything and imports only what you upload now.
                  </span>
                </span>
              </label>

              {mode === 'replace' && (
                <div className="space-y-2 rounded-xl border border-red-500/40 bg-red-500/10 p-3">
                  <p className="flex items-start gap-2 text-xs text-red-700 dark:text-red-300">
                    <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                    <span>
                      This deletes <strong>{formatNumber(existing!.messages)} messages</strong>{' '}
                      across {formatNumber(existing!.threads)} conversations,{' '}
                      <strong>{formatNumber(existing!.bookmarks)} saved memories</strong> and{' '}
                      <strong>the unpacked originals in ./exports/</strong> —{' '}
                      {existing!.archives.length} archives, {formatNumber(existing!.media)} photos
                      and files.
                      <br />
                      <br />
                      The files cannot be recovered without downloading the export from Facebook
                      again. Clearing only the database would not help: the importer reads the whole
                      export folder, so it would simply rebuild the same archive.
                    </span>
                  </p>
                  <label className="flex cursor-pointer items-center gap-2 text-xs font-medium text-red-700 dark:text-red-300">
                    <input
                      type="checkbox"
                      checked={confirmedReplace}
                      onChange={(event) => setConfirmedReplace(event.target.checked)}
                    />
                    I understand this permanently deletes my files
                  </label>
                </div>
              )}
            </fieldset>
          )}

          {stage === 'choose' && (
            <>
              <div
                onDragOver={(event) => {
                  event.preventDefault()
                  setDragging(true)
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(event) => {
                  event.preventDefault()
                  setDragging(false)
                  addFiles(event.dataTransfer.files)
                }}
                onClick={() => inputRef.current?.click()}
                className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
                  dragging
                    ? 'border-indigo-500 bg-indigo-500/10'
                    : 'border-zinc-300 hover:border-indigo-400 dark:border-zinc-700'
                }`}
              >
                <Upload size={26} className="mb-2 text-zinc-400" />
                <p className="text-sm font-medium">Drop your zip files here</p>
                <p className="mt-0.5 text-xs text-zinc-500">or click to browse</p>
                <input
                  ref={inputRef}
                  type="file"
                  accept=".zip,application/zip"
                  multiple
                  hidden
                  onChange={(event) => addFiles(event.target.files)}
                />
              </div>

              {queue.length > 0 && (
                <ul className="space-y-1">
                  {queue.map((entry, index) => (
                    <li
                      key={entry.file.name}
                      className="flex items-center gap-2 rounded-lg border border-zinc-200 px-3 py-2 text-sm dark:border-zinc-800"
                    >
                      <FileArchive size={15} className="shrink-0 text-zinc-400" />
                      <span className="min-w-0 flex-1 truncate">{entry.file.name}</span>
                      <span className="shrink-0 text-xs tabular-nums text-zinc-500">
                        {formatBytes(entry.file.size)}
                      </span>
                      <button
                        type="button"
                        onClick={() => setQueue((current) => current.filter((_, i) => i !== index))}
                        className="shrink-0 rounded p-1 text-zinc-400 hover:text-red-500"
                        aria-label="Ta bort"
                      >
                        <Trash2 size={14} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              {queue.length > 0 && (
                <p className="text-xs text-zinc-500">
                  {queue.length} archives · {formatBytes(totalBytes)} totalt
                  {free !== null && ` · ${formatBytes(free)} free on disk`}
                </p>
              )}

              {spaceTight && (
                <p className="flex items-start gap-2 rounded-lg bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-300">
                  <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                  While unpacking, each archive exists briefly both as a zip and unpacked.
                  Disk space looks tight — consider freeing some up first.
                </p>
              )}
            </>
          )}

          {stage === 'uploading' && (
            <div className="space-y-3">
              <p className="text-sm font-medium">Uploading to the server…</p>
              <div className="h-2 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
                <div
                  className="h-full rounded-full bg-indigo-500 transition-[width] duration-200"
                  style={{ width: `${totalBytes ? (uploadedBytes / totalBytes) * 100 : 0}%` }}
                />
              </div>
              <p className="text-xs tabular-nums text-zinc-500">
                {formatBytes(uploadedBytes)} of {formatBytes(totalBytes)}
              </p>

              <ul className="space-y-1">
                {queue.map((entry) => (
                  <li key={entry.file.name} className="flex items-center gap-2 text-xs">
                    {entry.status === 'uploaded' ? (
                      <Check size={13} className="shrink-0 text-emerald-500" />
                    ) : entry.status === 'uploading' ? (
                      <Loader2 size={13} className="shrink-0 animate-spin text-indigo-500" />
                    ) : (
                      <span className="h-3 w-3 shrink-0" />
                    )}
                    <span className="min-w-0 flex-1 truncate">{entry.file.name}</span>
                    <span className="shrink-0 tabular-nums text-zinc-500">
                      {Math.round((entry.loaded / entry.file.size) * 100)} %
                    </span>
                  </li>
                ))}
              </ul>

              <button
                type="button"
                onClick={() => {
                  abortRef.current?.()
                  setStage('choose')
                }}
                className="btn-ghost"
              >
                Cancel
              </button>
            </div>
          )}

          {stage === 'importing' && (
            <div className="space-y-3">
              <p className="flex items-center gap-2 text-sm font-medium">
                <Loader2 size={15} className="animate-spin text-indigo-500" />
                {progress ? STATE_LABELS[progress.state] : 'Starting…'}
              </p>

              {progress && progress.threads_total > 0 && (
                <>
                  <div className="h-2 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
                    <div
                      className="h-full rounded-full bg-indigo-500 transition-[width]"
                      style={{
                        width: `${(progress.threads_done / progress.threads_total) * 100}%`,
                      }}
                    />
                  </div>
                  <p className="text-xs tabular-nums text-zinc-500">
                    {formatNumber(progress.threads_done)} of {formatNumber(progress.threads_total)}{' '}
                    konversationer · {formatNumber(progress.messages)} meddelanden
                  </p>
                </>
              )}

              <p className="text-xs text-zinc-500">
                Unpacking takes a few minutes for large archives. The zip files are deleted
                automatically once they have been unpacked.
              </p>

              {progress?.log?.length ? (
                <pre className="max-h-32 overflow-y-auto rounded-lg bg-zinc-100 p-2 text-[0.6875rem] leading-relaxed text-zinc-600 dark:bg-zinc-950 dark:text-zinc-400">
                  {progress.log.slice(-8).join('\n')}
                </pre>
              ) : null}
            </div>
          )}

          {stage === 'done' && progress && (
            <div className="space-y-3 text-center">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-500">
                <Check size={24} />
              </div>
              <p className="text-sm font-medium">Archive imported</p>
              <p className="text-xs text-zinc-500">
                {formatNumber(progress.messages)} messages ·{' '}
                {formatNumber(progress.media)} media files
                {progress.owner && ` · you were identified as ${progress.owner}`}
              </p>
              <button type="button" onClick={onDone} className="btn-primary mx-auto">
                Open the archive
              </button>
            </div>
          )}

          {error && (
            <p className="flex items-start gap-2 rounded-lg bg-red-500/10 p-3 text-xs text-red-600 dark:text-red-400">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              {error}
            </p>
          )}
        </div>

        {stage === 'choose' && (
          <footer className="flex items-center gap-2 border-t border-zinc-200 p-4 dark:border-zinc-800">
            <p className="text-xs text-zinc-500">
              Files are unpacked into <code>./exports/</code> and stay there — that is where the
              photos are served from.
            </p>
            <button
              type="button"
              onClick={start}
              disabled={!queue.length || busy || blockedByConfirm}
              className={`ml-auto ${mode === 'replace' ? 'btn bg-red-600 text-white hover:bg-red-500' : 'btn-primary'}`}
            >
              <Upload size={15} />
              {mode === 'replace' ? 'Delete and import' : 'Import'}
              {queue.length > 0 && ` (${queue.length})`}
            </button>
          </footer>
        )}
      </div>
    </div>
  )
}
