import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Markdown } from './md'
import { Card, Header, useTheme } from './ui'
import type { Status } from './data'
import {
  ApiError,
  getFleetWorklist,
  postAgentChat,
  type AgentBackend,
  type AgentToolCall,
  type ChatMessage,
  type PriorityWheel,
} from './agentApi'

// A chat turn keeps the wire fields (role + content) plus the agent's investigation metadata,
// so a rendered assistant answer can show its tool trace and provenance.
type Turn = ChatMessage & { trace?: AgentToolCall[]; backend?: string; asOf?: string }

const BACKENDS: { value: AgentBackend; label: string; hint: string }[] = [
  { value: 'auto', label: 'Auto', hint: 'First configured LLM, else the offline planner' },
  { value: 'mock', label: 'Offline', hint: 'Deterministic planner — no API key needed' },
  { value: 'openai', label: 'OpenAI', hint: 'Needs OPENAI_API_KEY on the server' },
  { value: 'bedrock', label: 'Bedrock', hint: 'Needs AWS credentials on the server' },
]

const EXAMPLES = [
  'What should I do about VN-A300 mlg_r_inbd?',
  "Plan tonight's tire maintenance for SGN",
  'Where is the damage on VN-A300 mlg_r_inbd?',
  'What if VN-A300 mlg_r_inbd flies 6 landings per day?',
]

// The pipeline tools the agent can call — shown so the demo reads as a real agentic workflow.
const TOOLS = [
  'list_priority_wheels',
  'get_wheel_status',
  'run_rul_prediction',
  'get_tire_scan',
  'get_damage_area',
  'check_dispatch',
  'get_amm_thresholds',
  'check_spares',
  'search_defect_history',
]

const POSITION_LABEL: Record<string, string> = {
  nlg_l: 'NLG L',
  nlg_r: 'NLG R',
  mlg_l_inbd: 'MLG L INBD',
  mlg_l_outbd: 'MLG L OUTBD',
  mlg_r_inbd: 'MLG R INBD',
  mlg_r_outbd: 'MLG R OUTBD',
}

export default function EngineerChat() {
  const [theme, setTheme] = useTheme()
  const [backend, setBackend] = useState<AgentBackend>('auto')
  const [input, setInput] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)

  const chat = useMutation({ mutationFn: (msgs: ChatMessage[]) => postAgentChat(msgs, backend) })
  const worklist = useQuery({
    queryKey: ['fleet-worklist'],
    queryFn: () => getFleetWorklist(6),
    retry: false,
    staleTime: 60_000,
  })

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [turns, chat.isPending])

  function send(text: string) {
    const q = text.trim()
    if (!q || chat.isPending) return
    const wire: ChatMessage[] = [...turns.map((t) => ({ role: t.role, content: t.content })), { role: 'user', content: q }]
    setTurns((prev) => [...prev, { role: 'user', content: q }])
    setInput('')
    chat.mutate(wire, {
      onSuccess: (res) => {
        setTurns((prev) => [
          ...prev,
          { role: 'assistant', content: res.answer, trace: res.trace, backend: res.backend, asOf: res.as_of_date },
        ])
      },
    })
  }

  const top = worklist.data?.wheels[0]
  const status: Status = top ? (top.priority >= 0.5 ? 'action' : top.priority >= 0.2 ? 'watch' : 'ok') : 'watch'
  const dataUnavailable = worklist.error instanceof ApiError && worklist.error.status === 503
  const busy = chat.isPending

  return (
    <div className="min-h-screen p-4 font-mono text-[var(--ink-2)] lg:p-6">
      <Header status={status} theme={theme} onTheme={setTheme} path="/engineer-chat" />

      <div className="grid gap-3 lg:grid-cols-12">
        {/* chat column */}
        <div className="lg:col-span-8">
          <Card title="Engineer Chat" tag="maintenance agent">
            <div className="flex min-h-[520px] flex-col">
              <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto pr-1" style={{ maxHeight: '62vh' }}>
                {turns.length === 0 && !busy && <EmptyState onPick={send} disabled={busy} />}
                {turns.map((t, i) => (
                  <Bubble key={i} turn={t} />
                ))}
                {busy && <Investigating />}
              </div>

              {chat.isError && (
                <p className="mt-3 border border-[var(--crit)] bg-[var(--panel)] px-3 py-2 text-xs" style={{ color: 'var(--crit)' }}>
                  ⚠ {(chat.error as Error).message}
                </p>
              )}

              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  send(input)
                }}
                className="mt-3 flex gap-2"
              >
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="Ask about any tire — situation, prediction, damage, dispatch, spares…"
                  className="flex-1 border border-[var(--line-2)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--ink)] outline-none focus:border-[var(--primary)]"
                />
                <button
                  type="submit"
                  disabled={busy || !input.trim()}
                  className="border border-[var(--primary-dim)] bg-[var(--primary-soft)] px-4 py-2 text-xs uppercase tracking-widest text-[var(--primary)] transition-opacity disabled:opacity-40"
                >
                  {busy ? 'Investigating…' : 'Send'}
                </button>
              </form>

              <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
                <BackendPicker value={backend} onChange={setBackend} />
                {turns.length > 0 && (
                  <button
                    onClick={() => {
                      setTurns([])
                      chat.reset()
                    }}
                    className="text-[10px] uppercase tracking-widest text-[var(--ink-4)] underline-offset-2 hover:text-[var(--ink-2)] hover:underline"
                  >
                    Reset conversation
                  </button>
                )}
              </div>
            </div>
          </Card>
        </div>

        {/* right rail */}
        <div className="flex flex-col gap-3 lg:col-span-4">
          <Card title="Fleet priority" tag="worklist · live">
            {worklist.isPending && <p className="text-xs text-[var(--ink-4)]">Loading worklist…</p>}
            {dataUnavailable && (
              <p className="text-xs leading-relaxed text-[var(--ink-3)]">
                Fleet dataset not loaded on the API. Run <code className="text-[var(--primary)]">make data</code> and{' '}
                <code className="text-[var(--primary)]">make train</code>, then start it with{' '}
                <code className="text-[var(--primary)]">make run</code>.
              </p>
            )}
            {worklist.isError && !dataUnavailable && (
              <p className="text-xs leading-relaxed" style={{ color: 'var(--crit)' }}>
                ⚠ {(worklist.error as Error).message}
              </p>
            )}
            {worklist.data && (
              <ul className="flex flex-col gap-1.5">
                {worklist.data.wheels.map((w) => (
                  <WorklistRow key={`${w.tail_number}-${w.position}`} wheel={w} disabled={busy} onPick={send} />
                ))}
              </ul>
            )}
          </Card>

          <Card title="How it works" tag="agentic">
            <p className="text-xs leading-relaxed text-[var(--ink-3)]">
              The agent investigates by autonomously calling pipeline tools, then reasons across the
              results — distinguishing gradual wear from acute damage and firing on the
              earliest-credible date.
            </p>
            <div className="mt-2 flex flex-wrap gap-1">
              {TOOLS.map((t) => (
                <code key={t} className="border border-[var(--line)] px-1.5 py-0.5 text-[10px] text-[var(--ink-4)]">
                  {t}
                </code>
              ))}
            </div>
          </Card>
        </div>
      </div>

      <footer className="mt-4 text-[10px] leading-relaxed text-[var(--ink-4)]">
        Decision support that prioritizes within existing AMM removal limits — it augments, never
        replaces, mandated inspections. All fleet data is synthetic.
      </footer>
    </div>
  )
}

function EmptyState({ onPick, disabled }: { onPick: (q: string) => void; disabled: boolean }) {
  return (
    <div className="flex h-full flex-col justify-center gap-3 py-6">
      <p className="text-sm text-[var(--ink-2)]">
        Ask the maintenance agent about any tire — get its situation, trigger a fresh RUL forecast,
        locate damage, check dispatch and spares. Follow-ups keep context (“predict it”).
      </p>
      <div className="flex flex-col gap-2">
        <span className="text-[10px] uppercase tracking-widest text-[var(--ink-4)]">Try</span>
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              disabled={disabled}
              onClick={() => onPick(ex)}
              className="border border-[var(--line-2)] px-2.5 py-1.5 text-left text-xs text-[var(--ink-3)] transition-colors hover:border-[var(--primary)] hover:text-[var(--primary)] disabled:opacity-40"
            >
              {ex}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

function Bubble({ turn }: { turn: Turn }) {
  const isUser = turn.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[88%] border p-3 ${
          isUser ? 'border-[var(--primary-dim)] bg-[var(--primary-soft)]' : 'border-[var(--line)] bg-[var(--panel)]'
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap text-sm text-[var(--ink)]">{turn.content}</p>
        ) : (
          <>
            <Markdown text={turn.content} />
            {turn.trace && turn.trace.length > 0 && <Trace trace={turn.trace} />}
            {turn.backend && (
              <div className="mt-2 flex flex-wrap gap-x-3 text-[9px] uppercase tracking-widest text-[var(--ink-4)]">
                <span>backend · {turn.backend}</span>
                {turn.asOf && <span>as of · {turn.asOf}</span>}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function Trace({ trace }: { trace: AgentToolCall[] }) {
  return (
    <details className="mt-2 border-t border-[var(--line)] pt-2">
      <summary className="cursor-pointer text-[10px] uppercase tracking-widest text-[var(--ink-4)] hover:text-[var(--ink-3)]">
        🔍 trace · {trace.length} tool call{trace.length > 1 ? 's' : ''}
      </summary>
      <ol className="mt-2 flex flex-col gap-2">
        {trace.map((t, i) => (
          <li key={i} className="border border-[var(--line)] bg-[var(--bg)] p-2">
            <div className="text-xs">
              <span className="text-[var(--ink-4)]">{i + 1}.</span>{' '}
              <span className="text-[var(--primary)]">{t.tool}</span>
              {Object.keys(t.args).length > 0 && <span className="text-[var(--ink-4)]"> · {summarizeArgs(t.args)}</span>}
            </div>
            <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words text-[10px] leading-relaxed text-[var(--ink-3)]">
              {JSON.stringify(t.result, null, 2)}
            </pre>
          </li>
        ))}
      </ol>
    </details>
  )
}

function Investigating() {
  return (
    <div className="flex justify-start">
      <div className="flex items-center gap-2 border border-[var(--line)] bg-[var(--panel)] px-3 py-2 text-xs text-[var(--ink-3)]">
        <span className="inline-flex gap-1">
          <Dot delay="0ms" />
          <Dot delay="160ms" />
          <Dot delay="320ms" />
        </span>
        Agent is investigating — calling pipeline tools…
      </div>
    </div>
  )
}

function Dot({ delay }: { delay: string }) {
  return (
    <span
      className="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--primary)]"
      style={{ animationDelay: delay }}
    />
  )
}

function BackendPicker({ value, onChange }: { value: AgentBackend; onChange: (b: AgentBackend) => void }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] uppercase tracking-widest text-[var(--ink-4)]">Backend</span>
      <div className="flex border border-[var(--line-2)]">
        {BACKENDS.map((b) => {
          const on = b.value === value
          return (
            <button
              key={b.value}
              title={b.hint}
              onClick={() => onChange(b.value)}
              aria-pressed={on}
              className="border-r border-[var(--line-2)] px-2 py-1 text-[10px] uppercase tracking-widest transition-colors last:border-r-0"
              style={{
                color: on ? 'var(--primary)' : 'var(--ink-4)',
                background: on ? 'var(--primary-soft)' : 'transparent',
              }}
            >
              {b.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}

function WorklistRow({ wheel, disabled, onPick }: { wheel: PriorityWheel; disabled: boolean; onPick: (q: string) => void }) {
  const pos = POSITION_LABEL[wheel.position] ?? wheel.position
  return (
    <li>
      <button
        disabled={disabled}
        onClick={() => onPick(`What should I do about ${wheel.tail_number} ${wheel.position}?`)}
        className="w-full border border-[var(--line)] px-2 py-1.5 text-left transition-colors hover:border-[var(--primary)] disabled:opacity-40"
      >
        <div className="flex items-baseline justify-between gap-2 text-xs">
          <span className="text-[var(--ink-2)]">
            {wheel.tail_number} · {pos}
          </span>
          <span className="tabular-nums text-[var(--warn)]">{wheel.priority.toFixed(2)}</span>
        </div>
        <div className="mt-0.5 flex items-baseline justify-between gap-2 text-[10px] text-[var(--ink-4)]">
          <span className="tabular-nums">
            RUL {wheel.rul_median_landings} ldg · by {wheel.earliest_credible_date}
          </span>
          <span>{wheel.station}</span>
        </div>
      </button>
    </li>
  )
}

function summarizeArgs(args: Record<string, unknown>): string {
  return Object.entries(args)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
    .join(' · ')
}
