import { AnimatePresence, motion } from "motion/react"
import {
  BookOpen,
  Check,
  ChevronRight,
  CircleStop,
  ExternalLink,
  FileText,
  FolderOpen,
  Globe2,
  Laptop,
  LoaderCircle,
  Moon,
  Play,
  ScrollText,
  Sparkles,
  Sun,
  X,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"

import { FlickeringGrid } from "@/components/ui/flickering-grid"
import {
  MorphingDialog,
  MorphingDialogClose,
  MorphingDialogContainer,
  MorphingDialogContent,
  MorphingDialogDescription,
  MorphingDialogTitle,
  MorphingDialogTrigger,
} from "@/components/ui/morphing-dialog"
import { cn } from "@/lib/utils"

type Mode = "page" | "book"
type Theme = "light" | "dark" | "system"
type OutputFormat = "markdown" | "json" | "text"

type ExtractionForm = {
  mode: Mode
  url: string
  name: string
  outputDir: string
  format: OutputFormat
  startChapter: number
  endChapter: number
  delay: number
  playwright: boolean
  headed: boolean
  waitForUser: boolean
  overwrite: boolean
}

type BridgeEvent = {
  type: "output" | "saved" | "verification" | "finished" | "error"
  text?: string
  path?: string
  exitCode?: number
}

type BridgeStatus = {
  events: BridgeEvent[]
  cursor: number
  running: boolean
  exitCode: number | null
}

type DesktopApi = {
  choose_output_dir: (initial: string) => Promise<string | null>
  start_extraction: (payload: Record<string, unknown>) => Promise<{ ok: boolean; error?: string }>
  get_status: (cursor: number) => Promise<BridgeStatus>
  send_verification: () => Promise<{ ok: boolean }>
  stop_extraction: () => Promise<{ ok: boolean }>
  open_output_folder: (path: string) => Promise<{ ok: boolean; error?: string }>
}

declare global {
  interface Window {
    pywebview?: { api: DesktopApi }
  }
}

const initialForm: ExtractionForm = {
  mode: "book",
  url: "",
  name: "",
  outputDir: "outputs/book-name",
  format: "markdown",
  startChapter: 1,
  endChapter: 12,
  delay: 1,
  playwright: true,
  headed: true,
  waitForUser: true,
  overwrite: false,
}

const spring = { type: "spring" as const, stiffness: 420, damping: 34 }

function getEffectiveTheme(theme: Theme) {
  if (theme !== "system") return theme
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
}

function App() {
  const [form, setForm] = useState<ExtractionForm>(initialForm)
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem("pagebound-theme") as Theme) || "system")
  const [effectiveTheme, setEffectiveTheme] = useState<"light" | "dark">(() => getEffectiveTheme(theme))
  const [running, setRunning] = useState(false)
  const [verificationNeeded, setVerificationNeeded] = useState(false)
  const [logs, setLogs] = useState<string[]>([])
  const [savedCount, setSavedCount] = useState(0)
  const [status, setStatus] = useState("Ready to extract")
  const [error, setError] = useState("")
  const cursorRef = useRef(0)

  const expectedOutputs = form.mode === "book" ? Math.max(1, form.endChapter - form.startChapter + 1) : 1
  const progress = running || savedCount ? Math.min(100, Math.round((savedCount / expectedOutputs) * 100)) : 0

  useEffect(() => {
    localStorage.setItem("pagebound-theme", theme)
    const media = window.matchMedia("(prefers-color-scheme: dark)")
    const applyTheme = () => {
      const resolved = theme === "system" ? (media.matches ? "dark" : "light") : theme
      setEffectiveTheme(resolved)
      document.documentElement.classList.toggle("dark", resolved === "dark")
      document.documentElement.style.colorScheme = resolved
    }
    applyTheme()
    media.addEventListener("change", applyTheme)
    return () => media.removeEventListener("change", applyTheme)
  }, [theme])

  useEffect(() => {
    if (!running || !window.pywebview?.api) return
    const timer = window.setInterval(async () => {
      try {
        const update = await window.pywebview!.api.get_status(cursorRef.current)
        cursorRef.current = update.cursor
        consumeEvents(update.events)
        if (!update.running && update.exitCode !== null) setRunning(false)
      } catch (pollError) {
        setError(String(pollError))
        setRunning(false)
      }
    }, 300)
    return () => window.clearInterval(timer)
  }, [running])

  function updateForm<K extends keyof ExtractionForm>(key: K, value: ExtractionForm[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  function setMode(mode: Mode) {
    setForm((current) => ({
      ...current,
      mode,
      outputDir: mode === "book" ? "outputs/book-name" : "outputs/pages",
      playwright: mode === "book" ? true : current.playwright,
    }))
  }

  function setPlaywright(checked: boolean) {
    setForm((current) => ({
      ...current,
      playwright: checked,
      headed: checked ? current.headed : false,
      waitForUser: checked ? current.waitForUser : false,
    }))
  }

  function setHeaded(checked: boolean) {
    setForm((current) => ({
      ...current,
      headed: checked,
      waitForUser: checked ? current.waitForUser : false,
    }))
  }

  function consumeEvents(events: BridgeEvent[]) {
    for (const event of events) {
      if (event.type === "output" && event.text) setLogs((current) => [...current, event.text!])
      if (event.type === "saved") {
        setSavedCount((count) => count + 1)
        setStatus(form.mode === "book" ? "Extracting chapters" : "Saving page")
      }
      if (event.type === "verification") {
        setVerificationNeeded(true)
        setStatus("Waiting for browser verification")
      }
      if (event.type === "finished") {
        setRunning(false)
        setVerificationNeeded(false)
        if (event.exitCode === 0) {
          setSavedCount(expectedOutputs)
          setStatus("Extraction complete")
        } else {
          setStatus("Extraction stopped")
          setError("The crawler did not finish. Open activity for details.")
        }
      }
      if (event.type === "error") setError(event.text || "Something went wrong.")
    }
  }

  function validate() {
    if (!/^https?:\/\/\S+$/i.test(form.url.trim())) return "Enter a complete public http:// or https:// URL."
    if (!form.name.trim()) return form.mode === "book" ? "Enter a book name." : "Enter an output name."
    if (!form.outputDir.trim()) return "Choose an output folder."
    if (form.mode === "book" && (form.startChapter < 1 || form.endChapter < form.startChapter)) {
      return "The ending chapter must be at or after the starting chapter."
    }
    return ""
  }

  async function startExtraction() {
    const validationError = validate()
    if (validationError) {
      setError(validationError)
      return
    }
    if (!window.pywebview?.api) {
      setError("Launch the desktop interface with `python app.py` to run the crawler.")
      return
    }

    setError("")
    setLogs([])
    setSavedCount(0)
    setVerificationNeeded(false)
    cursorRef.current = 0
    const result = await window.pywebview.api.start_extraction({
      mode: form.mode,
      url: form.url,
      name: form.name,
      output_dir: form.outputDir,
      output_format: form.format,
      start_chapter: form.startChapter,
      end_chapter: form.endChapter,
      delay: form.delay,
      playwright: form.mode === "book" ? true : form.playwright,
      headed: form.headed,
      wait_for_user: form.waitForUser,
      overwrite: form.overwrite,
    })
    if (!result.ok) {
      setError(result.error || "The crawler could not start.")
      return
    }
    setRunning(true)
    setStatus(form.playwright || form.mode === "book" ? "Launching browser" : "Fetching page")
  }

  async function chooseOutput() {
    if (!window.pywebview?.api) return
    const selection = await window.pywebview.api.choose_output_dir(form.outputDir)
    if (selection) updateForm("outputDir", selection)
  }

  async function confirmVerification() {
    const result = await window.pywebview?.api.send_verification()
    if (result?.ok) {
      setVerificationNeeded(false)
      setStatus("Verification confirmed")
    }
  }

  async function stopExtraction() {
    await window.pywebview?.api.stop_extraction()
    setRunning(false)
    setVerificationNeeded(false)
    setStatus("Extraction stopped")
  }

  async function openOutput() {
    if (!window.pywebview?.api) return
    const result = await window.pywebview.api.open_output_folder(form.outputDir)
    if (!result.ok) setError(result.error || "Could not open the output folder.")
  }

  return (
    <div className="relative min-h-screen overflow-hidden bg-slate-100 text-slate-950 transition-colors duration-500 dark:bg-[#070b12] dark:text-white">
      <FlickeringGrid
        className="pointer-events-none fixed inset-0 z-0 h-screen w-screen opacity-55 [mask-image:radial-gradient(ellipse_at_center,black_10%,transparent_76%)] dark:opacity-35"
        squareSize={3}
        gridGap={8}
        flickerChance={0.08}
        maxOpacity={effectiveTheme === "dark" ? 0.28 : 0.16}
        color={effectiveTheme === "dark" ? "#60a5fa" : "#2563eb"}
      />
      <div className="pointer-events-none fixed inset-0 z-0 bg-[radial-gradient(circle_at_15%_10%,rgba(59,130,246,0.14),transparent_28%),radial-gradient(circle_at_90%_78%,rgba(14,165,233,0.10),transparent_26%)]" />

      <main className="relative z-10 mx-auto flex min-h-screen w-full max-w-6xl flex-col px-4 py-6 sm:px-6 lg:px-8 lg:py-10">
        <header className="mb-8 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="grid size-11 place-items-center rounded-2xl bg-blue-600 text-white shadow-lg shadow-blue-600/25">
              <Sparkles size={21} />
            </div>
            <div>
              <p className="text-lg font-extrabold tracking-tight">Web Extractor</p>
              <p className="text-xs text-slate-500 dark:text-slate-400">Pages in. Clean knowledge out.</p>
            </div>
          </div>
          <ThemeSwitcher theme={theme} onChange={setTheme} />
        </header>

        <section className="mb-7 max-w-3xl">
          <motion.p
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className="mb-3 text-xs font-bold tracking-[0.18em] text-blue-600 uppercase dark:text-blue-400"
          >
            Local extraction workspace
          </motion.p>
          <motion.h1
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.04 }}
            className="text-3xl leading-tight font-black tracking-[-0.035em] text-balance sm:text-4xl lg:text-5xl"
          >
            Extract one page—or an entire book.
          </motion.h1>
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.12 }}
            className="mt-4 max-w-2xl text-sm leading-6 text-slate-600 sm:text-base dark:text-slate-400"
          >
            Choose a workflow, keep human verification in your hands, and save structured output without repeating terminal commands.
          </motion.p>
        </section>

        <ModePicker mode={form.mode} onChange={setMode} />

        <motion.section layout transition={spring} className="glass-card mt-5 p-5 sm:p-7 lg:p-8">
          <div className="mb-7 flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-xl font-extrabold tracking-tight">
                {form.mode === "book" ? "Whole-book extraction" : "Web-page extraction"}
              </h2>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                {form.mode === "book"
                  ? "One browser session, one clean file per chapter."
                  : "Capture a single public page with only the rendering you need."}
              </p>
            </div>
            <span className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-bold text-blue-700 dark:border-blue-400/20 dark:bg-blue-400/10 dark:text-blue-300">
              {form.mode === "book" ? `${expectedOutputs} chapters` : "1 page"}
            </span>
          </div>

          <div className="grid min-w-0 grid-cols-1 gap-5 md:grid-cols-2">
            <Field label={form.mode === "book" ? "Book URL" : "Page URL"} className="md:col-span-2">
              <div className="relative">
                <Globe2 className="pointer-events-none absolute top-1/2 left-4 -translate-y-1/2 text-slate-400" size={17} />
                <input
                  className="control pl-11"
                  value={form.url}
                  onChange={(event) => updateForm("url", event.target.value)}
                  placeholder={form.mode === "book" ? "https://example.com/book/" : "https://example.com/article"}
                  spellCheck={false}
                />
              </div>
            </Field>

            <Field label={form.mode === "book" ? "Book name" : "Output name"}>
              <input
                className="control"
                value={form.name}
                onChange={(event) => updateForm("name", event.target.value)}
                placeholder={form.mode === "book" ? "Book Name" : "Article notes"}
              />
            </Field>

            <Field label="Output folder">
              <div className="flex min-w-0 gap-2">
                <input
                  className="control min-w-0 flex-1"
                  value={form.outputDir}
                  onChange={(event) => updateForm("outputDir", event.target.value)}
                  placeholder="outputs/book-name"
                />
                <motion.button whileHover={{ y: -2 }} whileTap={{ scale: 0.96 }} className="icon-button" onClick={chooseOutput} title="Choose folder">
                  <FolderOpen size={18} />
                </motion.button>
              </div>
            </Field>

            {form.mode === "book" && (
              <motion.div
                key="chapter-range"
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={spring}
                className="grid grid-cols-2 gap-3 md:col-span-2 md:max-w-md"
              >
                <Field label="Start chapter">
                  <input className="control" type="number" min={1} value={form.startChapter} onChange={(event) => updateForm("startChapter", Number(event.target.value))} />
                </Field>
                <Field label="End chapter">
                  <input className="control" type="number" min={1} value={form.endChapter} onChange={(event) => updateForm("endChapter", Number(event.target.value))} />
                </Field>
              </motion.div>
            )}

            <Field label="Output format">
              <select className="control appearance-none" value={form.format} onChange={(event) => updateForm("format", event.target.value as OutputFormat)}>
                <option value="markdown">Markdown (.md)</option>
                <option value="json">JSON (.json)</option>
                <option value="text">Plain text (.txt)</option>
              </select>
            </Field>

            <Field label={form.mode === "book" ? "Delay between chapters" : "Delay before fetching"}>
              <div className="relative">
                <input className="control pr-20" type="number" min={0} step={0.5} value={form.delay} onChange={(event) => updateForm("delay", Number(event.target.value))} />
                <span className="pointer-events-none absolute top-1/2 right-4 -translate-y-1/2 text-xs font-semibold text-slate-400">seconds</span>
              </div>
            </Field>
          </div>

          <div className="mt-7 border-t border-slate-200 pt-6 dark:border-white/10">
            <p className="field-label">Browser options</p>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              <Toggle label="Render JavaScript" checked={form.mode === "book" || form.playwright} disabled={form.mode === "book"} onChange={setPlaywright} />
              <Toggle label="Show browser" checked={form.headed} disabled={form.mode === "page" && !form.playwright} onChange={setHeaded} />
              <Toggle label="Wait for verification" checked={form.waitForUser} disabled={!form.headed || (form.mode === "page" && !form.playwright)} onChange={(checked) => updateForm("waitForUser", checked)} />
              <Toggle label="Overwrite files" checked={form.overwrite} onChange={(checked) => updateForm("overwrite", checked)} />
            </div>
          </div>

          <AnimatePresence>
            {error && (
              <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="mt-5 flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-400/20 dark:bg-red-400/10 dark:text-red-300">
                <X className="mt-0.5 shrink-0" size={16} />
                <span className="flex-1">{error}</span>
                <button onClick={() => setError("")} aria-label="Dismiss error"><X size={15} /></button>
              </motion.div>
            )}
          </AnimatePresence>

          <div className="mt-7 flex flex-col-reverse gap-3 border-t border-slate-200 pt-6 sm:flex-row sm:items-center sm:justify-between dark:border-white/10">
            <ActivityDialog logs={logs} status={status} savedCount={savedCount} expectedOutputs={expectedOutputs} />
            <div className="flex flex-wrap gap-2 sm:justify-end">
              <motion.button whileHover={{ y: -2 }} whileTap={{ scale: 0.97 }} onClick={openOutput} className="inline-flex h-11 items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 text-sm font-bold text-slate-700 dark:border-white/10 dark:bg-white/[0.055] dark:text-slate-200">
                <ExternalLink size={16} /> Open output
              </motion.button>
              {running ? (
                <motion.button whileTap={{ scale: 0.97 }} onClick={stopExtraction} className="inline-flex h-11 items-center gap-2 rounded-xl bg-red-600 px-5 text-sm font-bold text-white shadow-lg shadow-red-600/20">
                  <CircleStop size={17} /> Stop
                </motion.button>
              ) : (
                <motion.button whileHover={{ y: -2 }} whileTap={{ scale: 0.97 }} onClick={startExtraction} className="inline-flex h-11 items-center gap-2 rounded-xl bg-blue-600 px-5 text-sm font-bold text-white shadow-lg shadow-blue-600/25">
                  <Play size={17} fill="currentColor" /> Start extraction
                </motion.button>
              )}
            </div>
          </div>
        </motion.section>

        <AnimatePresence>
          {(running || savedCount > 0) && (
            <motion.section initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="glass-card mt-5 overflow-hidden p-5">
              <div className="flex items-center gap-4">
                <div className={cn("grid size-10 shrink-0 place-items-center rounded-xl", verificationNeeded ? "bg-amber-100 text-amber-700 dark:bg-amber-400/10 dark:text-amber-300" : "bg-blue-100 text-blue-700 dark:bg-blue-400/10 dark:text-blue-300")}>
                  {running ? <LoaderCircle className="animate-spin" size={19} /> : <Check size={19} />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-3">
                    <p className="truncate text-sm font-extrabold">{status}</p>
                    <p className="shrink-0 text-xs font-bold text-slate-500 dark:text-slate-400">{savedCount} / {expectedOutputs}</p>
                  </div>
                  <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-white/10">
                    <motion.div className="h-full rounded-full bg-blue-600" animate={{ width: `${progress}%` }} transition={spring} />
                  </div>
                </div>
                {verificationNeeded && (
                  <motion.button initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} whileTap={{ scale: 0.97 }} onClick={confirmVerification} className="shrink-0 rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-bold text-white">
                    Verification complete
                  </motion.button>
                )}
              </div>
            </motion.section>
          )}
        </AnimatePresence>

        <footer className="mt-auto pt-8 text-center text-xs text-slate-500 dark:text-slate-500">
          Runs locally. Respects robots.txt and normal site access controls.
        </footer>
      </main>
    </div>
  )
}

function ModePicker({ mode, onChange }: { mode: Mode; onChange: (mode: Mode) => void }) {
  const options = [
    { id: "page" as const, icon: Globe2, title: "Web page", description: "Extract one article, lesson, or public page." },
    { id: "book" as const, icon: BookOpen, title: "Whole book", description: "Extract a numbered chapter range in one session." },
  ]
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {options.map((option) => {
        const selected = mode === option.id
        const Icon = option.icon
        return (
          <motion.button
            key={option.id}
            layout
            whileHover={{ y: -3 }}
            whileTap={{ scale: 0.985 }}
            transition={spring}
            onClick={() => onChange(option.id)}
            className={cn(
              "relative overflow-hidden rounded-2xl border p-4 text-left transition-colors sm:p-5",
              selected
                ? "border-blue-500 bg-blue-600 text-white shadow-xl shadow-blue-600/20"
                : "border-slate-200 bg-white/80 text-slate-900 backdrop-blur-xl hover:border-slate-300 dark:border-white/10 dark:bg-slate-950/70 dark:text-white dark:hover:border-white/20",
            )}
          >
            {selected && <motion.div layoutId="mode-glow" className="absolute inset-0 bg-[radial-gradient(circle_at_85%_15%,rgba(255,255,255,0.22),transparent_38%)]" />}
            <div className="relative flex items-start gap-4">
              <div className={cn("grid size-11 shrink-0 place-items-center rounded-xl", selected ? "bg-white/15" : "bg-slate-100 text-blue-600 dark:bg-white/[0.07] dark:text-blue-400")}>
                <Icon size={20} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-3">
                  <p className="font-extrabold">{option.title}</p>
                  <ChevronRight className={selected ? "opacity-100" : "opacity-30"} size={17} />
                </div>
                <p className={cn("mt-1 text-sm leading-5", selected ? "text-blue-100" : "text-slate-500 dark:text-slate-400")}>{option.description}</p>
              </div>
            </div>
          </motion.button>
        )
      })}
    </div>
  )
}

function Field({ label, className, children }: { label: string; className?: string; children: React.ReactNode }) {
  return <label className={cn("min-w-0", className)}><span className="field-label">{label}</span>{children}</label>
}

function Toggle({ label, checked, disabled = false, onChange }: { label: string; checked: boolean; disabled?: boolean; onChange: (checked: boolean) => void }) {
  return (
    <motion.button
      whileTap={disabled ? undefined : { scale: 0.98 }}
      onClick={() => !disabled && onChange(!checked)}
      className={cn("flex min-h-11 items-center gap-3 rounded-xl border px-3.5 py-2.5 text-left text-sm font-semibold transition", checked ? "border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-400/20 dark:bg-blue-400/10 dark:text-blue-200" : "border-slate-200 bg-slate-50 text-slate-600 dark:border-white/10 dark:bg-white/[0.035] dark:text-slate-400", disabled && "cursor-not-allowed opacity-65")}
      aria-pressed={checked}
    >
      <span className={cn("grid size-5 shrink-0 place-items-center rounded-md border", checked ? "border-blue-600 bg-blue-600 text-white" : "border-slate-300 bg-white dark:border-white/20 dark:bg-white/5")}>
        {checked && <Check size={13} strokeWidth={3} />}
      </span>
      <span>{label}</span>
    </motion.button>
  )
}

function ThemeSwitcher({ theme, onChange }: { theme: Theme; onChange: (theme: Theme) => void }) {
  const choices = [{ id: "light" as const, icon: Sun }, { id: "system" as const, icon: Laptop }, { id: "dark" as const, icon: Moon }]
  return (
    <div className="flex rounded-xl border border-slate-200 bg-white/80 p-1 shadow-sm backdrop-blur-xl dark:border-white/10 dark:bg-white/[0.055]">
      {choices.map(({ id, icon: Icon }) => (
        <button key={id} onClick={() => onChange(id)} className={cn("relative grid size-8 place-items-center rounded-lg text-slate-500 transition dark:text-slate-400", theme === id && "text-slate-950 dark:text-white")} title={`${id[0].toUpperCase()}${id.slice(1)} theme`}>
          {theme === id && <motion.span layoutId="theme-pill" className="absolute inset-0 rounded-lg bg-slate-100 shadow-sm dark:bg-white/10" transition={spring} />}
          <Icon className="relative" size={15} />
        </button>
      ))}
    </div>
  )
}

function ActivityDialog({ logs, status, savedCount, expectedOutputs }: { logs: string[]; status: string; savedCount: number; expectedOutputs: number }) {
  const logText = useMemo(() => logs.join("").trim() || "Activity will appear here after extraction starts.", [logs])
  return (
    <MorphingDialog transition={{ type: "spring", bounce: 0.04, duration: 0.42 }}>
      <MorphingDialogTrigger className="flex h-11 items-center gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 text-left dark:border-white/10 dark:bg-white/[0.035]">
        <ScrollText size={17} className="text-blue-600 dark:text-blue-400" />
        <span><span className="block text-xs font-extrabold">Activity</span><span className="block text-[0.68rem] text-slate-500 dark:text-slate-400">{savedCount} of {expectedOutputs} saved</span></span>
      </MorphingDialogTrigger>
      <MorphingDialogContainer>
        <MorphingDialogContent className="relative mx-4 w-full max-w-2xl rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl dark:border-white/10 dark:bg-[#0d1420] sm:p-7">
          <MorphingDialogTitle className="flex items-center gap-3 pr-10">
            <div className="grid size-10 place-items-center rounded-xl bg-blue-100 text-blue-700 dark:bg-blue-400/10 dark:text-blue-300"><FileText size={18} /></div>
            <div><h3 className="text-lg font-extrabold">Extraction activity</h3><p className="text-sm text-slate-500 dark:text-slate-400">{status}</p></div>
          </MorphingDialogTitle>
          <MorphingDialogDescription className="mt-5" variants={{ initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 }, exit: { opacity: 0, y: 8 } }}>
            <pre className="max-h-[55vh] min-h-48 overflow-auto whitespace-pre-wrap rounded-2xl border border-slate-200 bg-slate-950 p-4 font-mono text-xs leading-5 text-slate-300 dark:border-white/10">{logText}</pre>
          </MorphingDialogDescription>
          <MorphingDialogClose className="icon-button top-5 right-5"><X size={17} /></MorphingDialogClose>
        </MorphingDialogContent>
      </MorphingDialogContainer>
    </MorphingDialog>
  )
}

export default App
